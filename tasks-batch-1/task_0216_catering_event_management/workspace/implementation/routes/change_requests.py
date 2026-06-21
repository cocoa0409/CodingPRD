"""Change-request routes: open, fetch, counter, revise, accept, reject
(PRD §3.10). Acceptance carries OCC against the parent Order.
"""
from flask import Blueprint

from common import (
    get_json, stamp_create, touch, parse_dt, require, require_int,
)
from db import db
from errors import (
    err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_BELOW_MIN_HEADCOUNT, ERR_NOT_RESOURCE_OWNER,
)
from middleware import authenticate, authorize
from response import success
from serializers import ser_change_request
from services import calculations
from services.helpers import (
    get_or_404, append_ledger, parse_order_version, check_order_version,
)

bp = Blueprint("change_requests", __name__)


def _check_cr_ownership(user_id, role, order):
    if role == "Client" and order["client_id"] != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "client does not own the parent order")


@bp.route("/catering/change-requests", methods=["POST"])
def open_change_request():
    user_id, role = authenticate()
    authorize(role, {"Client"})
    body = get_json()

    order_id = require(body, "order_id")
    if not isinstance(order_id, str):
        raise err(ERR_INVALID_REQUEST, "order_id must be a string")
    order = get_or_404(db.orders, order_id)
    _check_cr_ownership(user_id, role, order)

    # permitted only against CONFIRMED or GUARANTEED order (PRD §3.10)
    if order["lifecycle_status"] not in ("CONFIRMED", "GUARANTEED"):
        raise err(ERR_INVALID_STATE, "order is not CONFIRMED or GUARANTEED")

    requested_headcount = require_int(body, "requested_headcount", minimum=1)
    requested_event_start = parse_dt(require(body, "requested_event_start"))

    package = db.packages[order["package_id"]]
    if requested_headcount < package["min_headcount"]:
        raise err(ERR_BELOW_MIN_HEADCOUNT, "requested_headcount below package min_headcount")

    rec = {
        "order_id": order_id,
        "requested_headcount": requested_headcount,
        "requested_event_start": requested_event_start,
        "counter_headcount": None,
        "change_fee_cents": 0,
        "status": "PROPOSED",
    }
    stamp_create(rec)
    db.change_requests[rec["id"]] = rec
    return success(ser_change_request(rec), status=201)


@bp.route("/catering/change-requests/<crid>", methods=["GET"])
def get_change_request(crid):
    user_id, role = authenticate()
    authorize(role, {"CateringAdmin", "Client", "SalesCoordinator"})
    rec = get_or_404(db.change_requests, crid)
    order = db.orders[rec["order_id"]]
    _check_cr_ownership(user_id, role, order)
    return success(ser_change_request(rec))


@bp.route("/catering/change-requests/<crid>/counter", methods=["POST"])
def counter_change_request(crid):
    _, role = authenticate()
    authorize(role, {"SalesCoordinator"})
    cr = get_or_404(db.change_requests, crid)
    order = db.orders[cr["order_id"]]
    body = get_json()
    counter_headcount = require_int(body, "counter_headcount", minimum=1)

    if cr["status"] != "PROPOSED":
        raise err(ERR_INVALID_STATE, "change request is not PROPOSED")
    if order["lifecycle_status"] not in ("CONFIRMED", "GUARANTEED"):
        raise err(ERR_INVALID_STATE, "parent order is not CONFIRMED or GUARANTEED")

    cr["counter_headcount"] = counter_headcount
    cr["status"] = "COUNTERED"
    touch(cr)
    return success(ser_change_request(cr))


@bp.route("/catering/change-requests/<crid>/revise", methods=["POST"])
def revise_change_request(crid):
    user_id, role = authenticate()
    authorize(role, {"Client"})
    cr = get_or_404(db.change_requests, crid)
    order = db.orders[cr["order_id"]]
    _check_cr_ownership(user_id, role, order)
    body = get_json()
    requested_headcount = require_int(body, "requested_headcount", minimum=1)

    if cr["status"] != "COUNTERED":
        raise err(ERR_INVALID_STATE, "change request is not COUNTERED")

    cr["requested_headcount"] = requested_headcount
    cr["counter_headcount"] = None
    cr["status"] = "PROPOSED"
    touch(cr)
    return success(ser_change_request(cr))


@bp.route("/catering/change-requests/<crid>/accept", methods=["POST"])
def accept_change_request(crid):
    user_id, role = authenticate()
    authorize(role, {"Client", "SalesCoordinator"})
    cr = get_or_404(db.change_requests, crid)
    order = db.orders[cr["order_id"]]
    # ownership applies to Client-acted ops
    _check_cr_ownership(user_id, role, order)
    body = get_json()
    expected = parse_order_version(body)

    status = cr["status"]
    if status not in ("PROPOSED", "COUNTERED"):
        raise err(ERR_INVALID_STATE, "change request is not in an acceptable state")

    # OCC against parent order version (PRD §2.11, §3.10) — ERR_STALE_ORDER_VERSION
    # (business rule: runs after the state check per PRD §3.12)
    check_order_version(expected, order)

    if status == "PROPOSED":
        # parent order must be CONFIRMED or GUARANTEED; headcount >= min
        if order["lifecycle_status"] not in ("CONFIRMED", "GUARANTEED"):
            raise err(ERR_INVALID_STATE, "parent order is not CONFIRMED or GUARANTEED")
        package = db.packages[order["package_id"]]
        if cr["requested_headcount"] < package["min_headcount"]:
            raise err(ERR_BELOW_MIN_HEADCOUNT, "requested_headcount below package min_headcount")
        new_headcount = cr["requested_headcount"]
    else:  # COUNTERED accepted by Client
        new_headcount = cr["counter_headcount"]

    # change fee from the effective new headcount vs current booked (PRD §3.10)
    fee = calculations.change_fee(order, new_headcount)
    old_deposit = order["deposit_due_cents"]

    # apply new headcount; for PROPOSED also apply requested_event_start
    order["booked_headcount"] = new_headcount
    if status == "PROPOSED":
        order["event_start"] = cr["requested_event_start"]

    # cascade: GUARANTEED order reverts to CONFIRMED (bumps order version once)
    if order["lifecycle_status"] == "GUARANTEED":
        order["lifecycle_status"] = "CONFIRMED"
        order["guaranteed_headcount"] = None
        touch(order)

    # recompute provisional total + deposit
    order["provisional_total_cents"] = calculations.order_grand_total(order, "provisional")
    order["deposit_due_cents"] = calculations.deposit_amount(order)

    # ledger: DEPOSIT_HOLD delta (may be negative) + CHANGE_FEE_DEBIT
    delta = order["deposit_due_cents"] - old_deposit
    append_ledger(order["id"], "DEPOSIT_HOLD", delta, "deposit delta on change accept")
    append_ledger(order["id"], "CHANGE_FEE_DEBIT", fee, "change fee")

    cr["change_fee_cents"] = fee
    cr["status"] = "ACCEPTED"
    touch(cr)

    # acceptance bump of order version (in addition to any cascade revert bump)
    touch(order)
    return success(ser_change_request(cr))


@bp.route("/catering/change-requests/<crid>/reject", methods=["POST"])
def reject_change_request(crid):
    user_id, role = authenticate()
    authorize(role, {"SalesCoordinator", "Client"})
    cr = get_or_404(db.change_requests, crid)
    order = db.orders[cr["order_id"]]
    _check_cr_ownership(user_id, role, order)

    # SalesCoordinator rejects a PROPOSED; Client rejects a COUNTERED (PRD §3.10)
    if cr["status"] not in ("PROPOSED", "COUNTERED"):
        raise err(ERR_INVALID_STATE, "change request is not in a rejectable state")

    cr["status"] = "REJECTED"
    touch(cr)
    return success(ser_change_request(cr))
