"""Insurance certificate endpoints."""

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object, success_list
from services.helpers import (
    get_pagination, paginate, require_fields, get_str, get_enum, get_int, touch,
)
from services.serializers import insurance_certificate_view

bp = Blueprint("insurance", __name__)


CERT_TYPES = ("GENERAL_LIABILITY", "AUTO_LIABILITY", "UMBRELLA", "WORKERS_COMP")


def lazy_cert_expiry(c: dict):
    if c.get("status") == "ISSUED" and c.get("expires_at"):
        exp = db.parse_iso(c["expires_at"])
        if db.now_utc() > exp:
            c["status"] = "EXPIRED"
            touch(c)


@bp.route("/api/v1/insurance-certificates", methods=["POST"])
def create_certificate():
    user_id, role = require_roles("Customer", "ComplianceOfficer")
    payload = request.get_json(silent=True) or {}
    require_fields(payload, "order_id", "venue_name", "venue_address", "certificate_type", "coverage_amount_cents")
    order_id = get_str(payload, "order_id", required=True)
    venue_name = get_str(payload, "venue_name", required=True)
    venue_address = get_str(payload, "venue_address", required=True)
    certificate_type = get_enum(payload, "certificate_type", CERT_TYPES, required=True)
    coverage_amount_cents = get_int(payload, "coverage_amount_cents", required=True)

    o = db.orders.get(order_id)
    if o is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "order not found")
    if role == "Customer" and o.get("customer_id") != user_id:
        raise errors.make_error(errors.ERR_UNAUTHORIZED, "Customer may only request certificates for own orders")

    cid = db.new_id()
    now = db.iso_now()
    c = {
        "id": cid,
        "order_id": order_id,
        "venue_name": venue_name,
        "venue_address": venue_address,
        "certificate_type": certificate_type,
        "coverage_amount_cents": coverage_amount_cents,
        "status": "REQUESTED",
        "issued_at": None,
        "expires_at": None,
        "certificate_number": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.insurance_certificates[cid] = c
    return success_object(insurance_certificate_view(c), status=201)


@bp.route("/api/v1/insurance-certificates", methods=["GET"])
def list_certificates():
    user_id, role = require_roles("ComplianceOfficer", "PlatformAdmin", "Customer")
    limit, offset = get_pagination()
    status = request.args.get("status")
    order_id = request.args.get("order_id")
    items = sorted(db.insurance_certificates.values(), key=lambda x: x["created_at"])
    for c in items:
        lazy_cert_expiry(c)
    if role == "Customer":
        items = [c for c in items if db.orders.get(c.get("order_id")) and db.orders[c["order_id"]].get("customer_id") == user_id]
    if status:
        items = [c for c in items if c.get("status") == status]
    if order_id:
        items = [c for c in items if c.get("order_id") == order_id]
    page, total = paginate(items, limit, offset)
    return success_list([insurance_certificate_view(c) for c in page], limit, offset, total)


@bp.route("/api/v1/insurance-certificates/<cid>", methods=["GET"])
def get_certificate(cid):
    user_id, role = require_roles("ComplianceOfficer", "PlatformAdmin", "Customer")
    c = db.insurance_certificates.get(cid)
    if c is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "certificate not found")
    if role == "Customer":
        o = db.orders.get(c.get("order_id"))
        if not o or o.get("customer_id") != user_id:
            raise errors.make_error(errors.ERR_UNAUTHORIZED, "Customer may only access own certificates")
    lazy_cert_expiry(c)
    return success_object(insurance_certificate_view(c))


@bp.route("/api/v1/insurance-certificates/<cid>/issue", methods=["POST"])
def issue_certificate(cid):
    require_roles("ComplianceOfficer")
    c = db.insurance_certificates.get(cid)
    if c is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "certificate not found")
    if c["status"] != "REQUESTED":
        raise errors.make_error(errors.ERR_INVALID_STATE, f"certificate is in state {c['status']}, cannot issue")

    o = db.orders.get(c["order_id"])
    if o is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "order not found")
    if o["status"] not in ("CONFIRMED", "ASSIGNED", "IN_PROGRESS"):
        raise errors.make_error(errors.ERR_INVALID_STATE, f"order is in state {o['status']}, cannot issue certificate")

    quote = db.quotes.get(o["quote_id"])
    if quote is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "quote not found")

    vehicle = db.vehicles.get(o.get("assigned_vehicle_id")) if o.get("assigned_vehicle_id") else None
    if vehicle:
        trip_date = db.parse_iso(quote["trip_date"])
        if db.parse_iso(vehicle["insurance_expiry"]) <= trip_date:
            raise errors.make_error(errors.ERR_INSURANCE_EXPIRED, "vehicle insurance expired before trip date")

    now = db.now_utc()
    c["issued_at"] = db.iso_now()
    c["certificate_number"] = db.next_cert_number()

    # expires_at = min(vehicle.insurance_expiry, quote.return_date)
    return_date = db.parse_iso(quote["return_date"])
    if vehicle:
        insurance_expiry = db.parse_iso(vehicle["insurance_expiry"])
        c["expires_at"] = db.to_iso(min(insurance_expiry, return_date))
    else:
        c["expires_at"] = db.to_iso(return_date)

    c["status"] = "ISSUED"
    touch(c)
    return success_object(insurance_certificate_view(c))


@bp.route("/api/v1/insurance-certificates/<cid>/revoke", methods=["POST"])
def revoke_certificate(cid):
    require_roles("ComplianceOfficer")
    c = db.insurance_certificates.get(cid)
    if c is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "certificate not found")
    if c["status"] != "ISSUED":
        raise errors.make_error(errors.ERR_INVALID_STATE, f"certificate is in state {c['status']}, cannot revoke")
    payload = request.get_json(silent=True) or {}
    reason = payload.get("reason")
    if not reason or not isinstance(reason, str):
        raise errors.make_error(errors.ERR_INVALID_REQUEST, "reason is required")
    c["status"] = "REVOKED"
    touch(c)
    return success_object(insurance_certificate_view(c))
