"""StreetPermit endpoints (PRD section 3.4)."""
from flask import Blueprint, request

from db import db
from errors import err
from helpers import (
    get_order, get_permit, check_order_owner, paginate, current_date,
)
from middleware import require_auth, require_role
from response import success
from serialize import street_permit as ser
import validate

bp = Blueprint("street_permits", __name__)


def _windows_overlap(a_from, a_until, b_from, b_until):
    """Closed-interval overlap: sharing any single calendar day counts."""
    return a_from <= b_until and b_from <= a_until


@bp.post("/street-permits")
def create_permit():
    user_id, role = require_auth()
    require_role(role, ["PermitOfficer", "Dispatcher", "Contractor"])
    body = validate.get_json_body()
    validate.require_fields(body, [
        "order_id", "municipality", "permit_fee_cents", "valid_from", "valid_until",
    ])
    order_id = validate.require_string(body, "order_id")
    municipality = validate.require_string(body, "municipality")
    permit_fee_cents = validate.require_non_negative_int(body, "permit_fee_cents")
    valid_from = validate.require_date(body, "valid_from")
    valid_until = validate.require_date(body, "valid_until")

    # existence of FK + ownership (priority 3, 4).
    order = get_order(order_id)
    check_order_owner(order, role, user_id)

    # date range well-formedness (priority 12): valid_until >= valid_from.
    if valid_until < valid_from:
        raise err("ERR_INVALID_DATE_RANGE", "valid_until must be >= valid_from")

    rec = db.insert_with_common(db.street_permits, {
        "order_id": order_id,
        "municipality": municipality,
        "permit_fee_cents": permit_fee_cents,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "status": "REQUESTED",
    })
    return success(ser(rec), status=201)


@bp.get("/street-permits")
def list_permits():
    user_id, role = require_auth()
    require_role(role, ["YardAdmin", "Dispatcher", "PermitOfficer", "Contractor"])
    limit, offset = validate.get_pagination()
    records = list(db.street_permits.values())
    if role == "Contractor":
        owned_orders = {o["id"] for o in db.rental_orders.values()
                        if o["account_id"] == user_id}
        records = [r for r in records if r["order_id"] in owned_orders]
    order_id = request.args.get("order_id")
    status = request.args.get("status")
    if order_id is not None:
        records = [r for r in records if r["order_id"] == order_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return paginate(records, ser, limit, offset)


@bp.get("/street-permits/<permit_id>")
def get_permit_ep(permit_id):
    user_id, role = require_auth()
    require_role(role, ["YardAdmin", "Dispatcher", "PermitOfficer", "Contractor"])
    rec = get_permit(permit_id)
    if role == "Contractor":
        order = db.rental_orders.get(rec["order_id"])
        if order is None or order["account_id"] != user_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Contractor does not own this permit")
    return success(ser(rec), status=200)


@bp.post("/street-permits/<permit_id>/approve")
def approve_permit(permit_id):
    _, role = require_auth()
    require_role(role, ["PermitOfficer"])
    permit = get_permit(permit_id)
    # state (priority 5).
    if permit["status"] != "REQUESTED":
        raise err("ERR_PERMIT_NOT_REQUESTED", "Permit is not REQUESTED")
    # window-passed first (priority 10): current_date <= valid_until.
    cur = current_date()
    if cur is not None and cur > permit["valid_until"]:
        raise err("ERR_PERMIT_WINDOW_PASSED", "Permit window has passed")
    # window-overlap second (priority 11).
    for p in db.street_permits.values():
        if (p["id"] != permit_id and p["order_id"] == permit["order_id"]
                and p["status"] == "APPROVED"
                and _windows_overlap(permit["valid_from"], permit["valid_until"],
                                     p["valid_from"], p["valid_until"])):
            raise err("ERR_PERMIT_WINDOW_OVERLAP",
                      "Another approved permit window overlaps this one")
    permit["status"] = "APPROVED"
    db.touch(permit)
    return success(ser(permit), status=200)


@bp.post("/street-permits/<permit_id>/deny")
def deny_permit(permit_id):
    _, role = require_auth()
    require_role(role, ["PermitOfficer"])
    permit = get_permit(permit_id)
    if permit["status"] != "REQUESTED":
        raise err("ERR_PERMIT_NOT_REQUESTED", "Permit is not REQUESTED")
    permit["status"] = "DENIED"
    db.touch(permit)
    return success(ser(permit), status=200)


@bp.post("/street-permits/<permit_id>/expire-check")
def expire_check(permit_id):
    _, role = require_auth()
    require_role(role, ["PermitOfficer"])
    permit = get_permit(permit_id)
    if permit["status"] != "APPROVED":
        raise err("ERR_PERMIT_NOT_APPROVED", "Permit is not APPROVED")
    cur = current_date()
    # requires current_date strictly after valid_until.
    if cur is None or cur <= permit["valid_until"]:
        raise err("ERR_PERMIT_NOT_EXPIRED", "Permit window has not yet passed")
    permit["status"] = "EXPIRED"
    db.touch(permit)
    return success(ser(permit), status=200)
