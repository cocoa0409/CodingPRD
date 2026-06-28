"""Order endpoints (PRD §3.2). Open / get / list / transition.

The order is the escrow-trust root. Its three escrow figures are computed live
(serializers) from POSTED deposits and WIRED disbursements. The status machine is
OPENED -> IN_TITLE -> COMMITTED -> CLEAR_TO_CLOSE -> CLOSED, with CANCELLED from
any non-terminal state; cancellation from IN_TITLE/COMMITTED fires Cascade A.
"""

from flask import Blueprint, request, g

import errors
from db import db, new_id, now_ts, next_seq
from middleware import require_roles
from response import success, list_success
from serializers import serialize_order
from services.domain import (
    touch, escrow_balance, require_agency_owns_order,
    order_current_issued_commitment, commitment_open_exception_count,
    cascade_a_cancel_order,
)
from helpers import (
    get_body, require_str, require_int_min, require_enum,
    parse_pagination, paginate, sort_by_created,
)

bp = Blueprint("orders", __name__)

TRANSACTION_TYPES = {"PURCHASE", "REFINANCE", "REISSUE"}
ORDER_STATUSES = {"OPENED", "IN_TITLE", "COMMITTED", "CLEAR_TO_CLOSE", "CLOSED", "CANCELLED"}
READ_ROLES = ("Agency", "TitleOfficer", "Underwriter")


def get_order_or_404(order_id):
    order = db.orders.get(order_id)
    if order is None:
        raise errors.not_found("Order not found")
    return order


@bp.route("/title/orders", methods=["POST"])
@require_roles("Agency")
def create_order():
    body = get_body()
    agency_id = require_str(body, "agency_id")
    parcel_id = require_str(body, "parcel_id")
    county = require_str(body, "county")
    transaction_type = require_enum(body, "transaction_type", TRANSACTION_TYPES)
    sales_price_cents = require_int_min(body, "sales_price_cents", 0)
    loan_amount_cents = require_int_min(body, "loan_amount_cents", 0)

    # Existence (priority 3): the referenced agency must exist.
    agency = db.agencies.get(agency_id)
    if agency is None:
        raise errors.not_found("Agency not found")
    # Authorization (priority 2): an Agency may open orders only for itself.
    if agency_id != g.user_id:
        raise errors.unauthorized("agency_id must equal the acting Agency's X-User-ID")

    ts = now_ts()
    oid = new_id()
    record = {
        "id": oid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
        "agency_id": agency_id,
        "parcel_id": parcel_id,
        "county": county,
        "transaction_type": transaction_type,
        "sales_price_cents": sales_price_cents,
        "loan_amount_cents": loan_amount_cents,
        "status": "OPENED",
        "gap_open": False,
    }
    db.orders[oid] = record
    return success(serialize_order(record), status=201)


@bp.route("/title/orders/<oid>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_order(oid):
    order = get_order_or_404(oid)
    require_agency_owns_order(order)
    return success(serialize_order(order), status=200)


@bp.route("/title/orders", methods=["GET"])
@require_roles(*READ_ROLES)
def list_orders():
    limit, offset = parse_pagination()
    items = list(db.orders.values())
    # An Agency only sees its own orders.
    if g.user_role == "Agency":
        items = [o for o in items if o["agency_id"] == g.user_id]
    agency_id = request.args.get("agency_id")
    if agency_id is not None:
        items = [o for o in items if o["agency_id"] == agency_id]
    status = request.args.get("status")
    if status is not None:
        items = [o for o in items if o["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success([serialize_order(o) for o in page], limit, offset, total)


# Roles permitted per target transition (PRD §3.2):
#   Agency drives CANCEL; TitleOfficer drives the forward production sequence.
_FORWARD = {"IN_TITLE", "COMMITTED", "CLEAR_TO_CLOSE", "CLOSED"}


@bp.route("/title/orders/<oid>/transitions", methods=["POST"])
@require_roles("Agency", "TitleOfficer")
def transition_order(oid):
    body = get_body()
    order = get_order_or_404(oid)
    require_agency_owns_order(order)
    to_status = require_enum(body, "to_status", ORDER_STATUSES)

    # RBAC on the specific transition target (priority 2): forward steps are the
    # TitleOfficer's; CANCEL is the Agency's.
    if to_status in _FORWARD and g.user_role != "TitleOfficer":
        raise errors.unauthorized("Only a TitleOfficer may advance an order")
    if to_status == "CANCELLED" and g.user_role != "Agency":
        raise errors.unauthorized("Only an Agency may cancel an order")

    cur = order["status"]

    if to_status == "IN_TITLE":
        _to_in_title(order, cur)
    elif to_status == "COMMITTED":
        _to_committed(order, cur)
    elif to_status == "CLEAR_TO_CLOSE":
        _to_clear_to_close(order, cur)
    elif to_status == "CLOSED":
        _to_closed(order, cur)
    elif to_status == "CANCELLED":
        _to_cancelled(order, cur)
    else:
        raise errors.invalid_state("Unsupported order transition")

    return success(serialize_order(order), status=200)


def _to_in_title(order, cur):
    # State (priority 6).
    if cur != "OPENED":
        raise errors.invalid_state("Order is not OPENED")
    # Cross-entity / safety: at least one TitleSearch in ORDERED or IN_EXAM.
    has_search = any(
        s["order_id"] == order["id"] and s["status"] in ("ORDERED", "IN_EXAM")
        for s in db.title_searches.values())
    if not has_search:
        raise errors.invalid_state("Order has no active TitleSearch (ORDERED/IN_EXAM)")
    order["status"] = "IN_TITLE"
    touch(order)


def _to_committed(order, cur):
    if cur != "IN_TITLE":
        raise errors.invalid_state("Order is not IN_TITLE")
    # Cross-entity referential (priority 7) preconditions, in PRD order.
    issued = order_current_issued_commitment(order["id"])
    if issued is None:
        raise errors.ApiError(errors.ERR_NO_ISSUED_COMMITMENT, 409,
                              "Order has no Commitment in ISSUED")
    chain_ok = any(
        s["order_id"] == order["id"] and s["status"] == "COMPLETED" and s["chain_verified"]
        for s in db.title_searches.values())
    if not chain_ok:
        raise errors.ApiError(errors.ERR_CHAIN_NOT_VERIFIED, 409,
                              "Order has no COMPLETED TitleSearch with chain_verified true")
    order["status"] = "COMMITTED"
    touch(order)


def _to_clear_to_close(order, cur):
    if cur != "COMMITTED":
        raise errors.invalid_state("Order is not COMMITTED")
    # Safety (priority 9): the ISSUED commitment must have no open exceptions.
    issued = order_current_issued_commitment(order["id"])
    if issued is None or commitment_open_exception_count(issued["id"]) != 0:
        raise errors.ApiError(errors.ERR_EXCEPTIONS_OPEN, 409,
                              "Order's ISSUED commitment has open exceptions")
    # At least one ISSUED policy on the order.
    has_issued_policy = any(
        p["order_id"] == order["id"] and p["status"] == "ISSUED"
        for p in db.policies.values())
    if not has_issued_policy:
        raise errors.ApiError(errors.ERR_NO_ISSUED_POLICY, 409,
                              "Order has no ISSUED policy")
    order["status"] = "CLEAR_TO_CLOSE"
    touch(order)


def _to_closed(order, cur):
    if cur != "CLEAR_TO_CLOSE":
        raise errors.invalid_state("Order is not CLEAR_TO_CLOSE")
    # Fiscal (priority 10): escrow balance must be exactly 0.
    if escrow_balance(order["id"]) != 0:
        raise errors.ApiError(errors.ERR_ESCROW_NOT_ZERO, 409,
                              "Order escrow balance is not zero")
    order["status"] = "CLOSED"
    order["gap_open"] = False
    touch(order)


def _to_cancelled(order, cur):
    if cur not in ("OPENED", "IN_TITLE", "COMMITTED"):
        raise errors.invalid_state("Order cannot be cancelled from " + cur)
    # Fiscal (priority 10): no posted trust funds left.
    if escrow_balance(order["id"]) != 0:
        raise errors.ApiError(errors.ERR_ESCROW_NOT_ZERO, 409,
                              "Order escrow balance is not zero")
    # Cascade A fires from IN_TITLE / COMMITTED (OPENED has no children).
    if cur in ("IN_TITLE", "COMMITTED"):
        cascade_a_cancel_order(order)
    order["status"] = "CANCELLED"
    order["gap_open"] = False
    touch(order)
