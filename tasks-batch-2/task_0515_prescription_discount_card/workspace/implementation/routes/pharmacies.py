"""Pharmacy endpoints (PRD §3.1)."""
from flask import Blueprint, request
import db
import response
import common
import errors
import middleware
from services import serializers

bp = Blueprint("pharmacies", __name__)

READ_ROLES = ["Anonymous", "Member", "PlatformAdmin", "PharmacyOperator"]


@bp.route("/pharmacies", methods=["POST"])
def create_pharmacy():
    middleware.require_auth(["PlatformAdmin"])
    body = common.get_body()
    name = common.req_str(body, "name")
    chain_code = common.req_str(body, "chain_code")
    state_code = common.req_str(body, "state_code")
    common.validate_state_code(state_code)
    dispense_fee_cents = common.req_int(body, "dispense_fee_cents")
    if dispense_fee_cents < 0:
        raise errors.invalid_request("dispense_fee_cents must be >= 0.")
    is_mail_order = common.opt_bool(body, "is_mail_order", False)

    rec = {
        "name": name,
        "chain_code": chain_code,
        "state_code": state_code,
        "is_mail_order": is_mail_order,
        "dispense_fee_cents": dispense_fee_cents,
        "status": "ACTIVE",
    }
    db.stamp_create(rec, common_fields=True)
    db.pharmacies[rec["id"]] = rec
    return response.object_response(serializers.serialize(rec), 201)


@bp.route("/pharmacies/<pid>", methods=["GET"])
def get_pharmacy(pid):
    middleware.require_auth(READ_ROLES)
    rec = common.must_exist(db.pharmacies, pid, "Pharmacy")
    return response.object_response(serializers.serialize(rec), 200)


@bp.route("/pharmacies", methods=["GET"])
def list_pharmacies():
    middleware.require_auth(READ_ROLES)
    limit, offset = common.parse_pagination()
    state_code = request.args.get("state_code")
    items = list(db.pharmacies.values())
    if state_code is not None:
        items = [p for p in items if p["state_code"] == state_code]
    window, total = common.paginate(items, limit, offset)
    return response.array_response(serializers.serialize_list(window), limit, offset, total, 200)


@bp.route("/pharmacies/<pid>/suspend", methods=["POST"])
def suspend_pharmacy(pid):
    middleware.require_auth(["PlatformAdmin"])
    rec = common.must_exist(db.pharmacies, pid, "Pharmacy")
    if rec["status"] != "ACTIVE":
        raise errors.invalid_state("Pharmacy is not ACTIVE.")
    rec["status"] = "SUSPENDED"
    db.touch(rec)
    # cascade: PUBLISHED quotes -> EXPIRED (only PUBLISHED)
    for quote in db.price_quotes.values():
        if quote["pharmacy_id"] == pid and quote["status"] == "PUBLISHED":
            quote["status"] = "EXPIRED"
            db.touch(quote)
    return response.object_response(serializers.serialize(rec), 200)


@bp.route("/pharmacies/<pid>/reactivate", methods=["POST"])
def reactivate_pharmacy(pid):
    middleware.require_auth(["PlatformAdmin"])
    rec = common.must_exist(db.pharmacies, pid, "Pharmacy")
    if rec["status"] != "SUSPENDED":
        raise errors.invalid_state("Pharmacy is not SUSPENDED.")
    rec["status"] = "ACTIVE"
    db.touch(rec)
    return response.object_response(serializers.serialize(rec), 200)
