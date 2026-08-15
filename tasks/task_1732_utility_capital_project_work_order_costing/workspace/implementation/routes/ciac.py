"""CIACAgreement endpoints (PRD 3.6): pledges, full receipt, lazy expiry."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_INVALID_STATE, ERR_CIAC_EXPIRED
from middleware import authorized
from response import success_object
from services.core import (
    new_record, touch, serialize_ciac, WO_CIAC_PLEDGEABLE_STATUSES,
    WO_CIAC_RECEIVABLE_STATUSES,
)
from util import CLOCK, parse_dt
from validate import (
    get_body, req_int, req_datetime, require_path_resource, require_body_ref,
)
from routes.helpers import list_response, get_one

bp = Blueprint("ciac_agreements", __name__)


@bp.route("/ucp/ciac-agreements", methods=["POST"])
def create_ciac():
    authorized(["RateAnalyst"])
    body = get_body()
    # Priority 3 — body FK existence.
    wo = require_body_ref(body, "work_order_id", "work_orders")
    # Priority 4 — shape.
    pledged_cents = req_int(body, "pledged_cents", positive=True)
    pledge_expiry_at = req_datetime(body, "pledge_expiry_at")
    # Priority 7 — pledges attach only while the order is neither terminal nor
    # completed.
    if wo["status"] not in WO_CIAC_PLEDGEABLE_STATUSES:
        raise_error(ERR_INVALID_STATE, f"work order is {wo['status']}")

    rec = new_record()
    rec.update({
        "work_order_id": wo["id"],
        "pledged_cents": pledged_cents,
        "pledge_expiry_at": pledge_expiry_at,
        "status": "PLEDGED",
        "received_cents": None,
        "applied_cents": None,
        "forfeited_cents": None,
        "refunded_cents": None,
    })
    db["ciac_agreements"][rec["id"]] = rec
    return success_object(serialize_ciac(rec), status=201)


@bp.route("/ucp/ciac-agreements/<ciac_id>", methods=["GET"])
def get_ciac(ciac_id):
    return get_one("ciac_agreements", serialize_ciac, ciac_id)


@bp.route("/ucp/ciac-agreements", methods=["GET"])
def list_ciac():
    filters = {
        "work_order_id": request.args.get("work_order_id"),
        "status": request.args.get("status"),
    }
    return list_response("ciac_agreements", serialize_ciac, filters)


@bp.route("/ucp/ciac-agreements/<ciac_id>/receive", methods=["POST"])
def receive_ciac(ciac_id):
    authorized(["RateAnalyst"])
    agreement = require_path_resource("ciac_agreements", ciac_id)
    # Priority 7 — target from-state, then the work order's state (funds may
    # arrive after in-service but before closeout).
    if agreement["status"] != "PLEDGED":
        raise_error(ERR_INVALID_STATE, f"CIAC agreement is {agreement['status']}")
    wo = db["work_orders"][agreement["work_order_id"]]
    if wo["status"] not in WO_CIAC_RECEIVABLE_STATUSES:
        raise_error(ERR_INVALID_STATE, f"work order is {wo['status']}")
    # Priority 9 — pledge expiry. A receipt attempted after expiry is rejected
    # and the agreement flips to EXPIRED as a side effect of the failed attempt.
    if CLOCK.now() > parse_dt(agreement["pledge_expiry_at"]):
        agreement["status"] = "EXPIRED"
        touch(agreement)
        raise_error(ERR_CIAC_EXPIRED, "pledge has expired")

    # Receipt is all-or-nothing.
    agreement["status"] = "RECEIVED"
    agreement["received_cents"] = agreement["pledged_cents"]
    touch(agreement)
    return success_object(serialize_ciac(agreement))
