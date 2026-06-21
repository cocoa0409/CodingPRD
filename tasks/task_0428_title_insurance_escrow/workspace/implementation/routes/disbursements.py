"""Disbursement endpoints (PRD §3.7). Request (OCC-guarded create) / get / list /
transition (APPROVE / WIRE / VOID).

The create is the second order-scoped operation guarded by expected_order_version
(§2.7) and always bumps the order's version. APPROVE requires the order to be
disbursable (CLEAR_TO_CLOSE/CLOSED; CLAIM_PAYOUT requires CLOSED). WIRE checks
sufficient escrow and a non-overlapping half-open wire window, then fires Cascade B
(escrow recompute + auto-close from CLEAR_TO_CLOSE when balance hits 0).
"""

from flask import Blueprint, request, g

import errors
from clock import parse_iso8601
from db import db, new_id, now_ts, next_seq
from middleware import require_roles
from response import success, list_success
from serializers import serialize_disbursement
from services.domain import touch, require_agency_owns_order, escrow_balance
from helpers import (
    get_body, require_str, require_int_min, require_int, require_enum,
    parse_pagination, paginate, sort_by_created,
)
from routes.orders import get_order_or_404

bp = Blueprint("disbursements", __name__)

PURPOSES = {"SELLER_PROCEEDS", "PAYOFF", "PREMIUM", "RECORDING_FEE", "CLAIM_PAYOUT"}
DISBURSEMENT_STATUSES = {"REQUESTED", "APPROVED", "WIRED", "VOID"}


def _get_disbursement_or_404(did):
    d = db.disbursements.get(did)
    if d is None:
        raise errors.not_found("Disbursement not found")
    return d


def _parse_dt(value, field):
    try:
        return parse_iso8601(value)
    except (ValueError, TypeError):
        raise errors.invalid_request("%s must be a valid ISO 8601 instant" % field)


@bp.route("/title/orders/<oid>/disbursements", methods=["POST"])
@require_roles("Underwriter")
def create_disbursement(oid):
    order = get_order_or_404(oid)
    body = get_body()
    # Body well-formedness (priority 4).
    payee = require_str(body, "payee")
    amount_cents = require_int_min(body, "amount_cents", 1)
    purpose = require_enum(body, "purpose", PURPOSES)
    wire_window_start = require_str(body, "wire_window_start")
    wire_window_end = require_str(body, "wire_window_end")
    _parse_dt(wire_window_start, "wire_window_start")
    _parse_dt(wire_window_end, "wire_window_end")
    expected_order_version = require_int(body, "expected_order_version")

    # OCC (priority 5): expected_order_version must match the order's version.
    if expected_order_version != order["version"]:
        raise errors.stale_version()

    ts = now_ts()
    did = new_id()
    record = {
        "id": did,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
        "order_id": order["id"],
        "payee": payee,
        "amount_cents": amount_cents,
        "purpose": purpose,
        "status": "REQUESTED",
        "wire_window_start": wire_window_start,
        "wire_window_end": wire_window_end,
    }
    db.disbursements[did] = record
    # Every disbursement create advances the order's version (§2.7).
    order["version"] += 1
    order["updated_at"] = now_ts()
    return success(serialize_disbursement(record), status=201)


@bp.route("/title/orders/<oid>/disbursements", methods=["GET"])
@require_roles("Underwriter", "Agency", "TitleOfficer")
def list_disbursements(oid):
    order = get_order_or_404(oid)
    require_agency_owns_order(order)
    limit, offset = parse_pagination()
    items = [d for d in db.disbursements.values() if d["order_id"] == order["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success([serialize_disbursement(d) for d in page], limit, offset, total)


@bp.route("/title/disbursements/<did>", methods=["GET"])
@require_roles("Underwriter", "Agency")
def get_disbursement(did):
    d = _get_disbursement_or_404(did)
    if g.user_role == "Agency":
        order = db.orders.get(d["order_id"])
        if order is not None:
            require_agency_owns_order(order)
    return success(serialize_disbursement(d), status=200)


def _windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap: they share an interior instant iff
    a_start < b_end and b_start < a_end. Exactly-adjacent windows do not overlap."""
    return a_start < b_end and b_start < a_end


@bp.route("/title/disbursements/<did>/transitions", methods=["POST"])
@require_roles("Underwriter")
def transition_disbursement(did):
    body = get_body()
    d = _get_disbursement_or_404(did)
    to_status = require_enum(body, "to_status", DISBURSEMENT_STATUSES)
    cur = d["status"]

    if to_status == "APPROVED":
        if cur != "REQUESTED":
            raise errors.invalid_state("Disbursement is not REQUESTED")
        order = db.orders.get(d["order_id"])
        # Cross-entity (priority 7): order must be disbursable.
        order_status = order["status"] if order else None
        if d["purpose"] == "CLAIM_PAYOUT":
            disbursable = order_status == "CLOSED"
        else:
            disbursable = order_status in ("CLEAR_TO_CLOSE", "CLOSED")
        if not disbursable:
            raise errors.ApiError(errors.ERR_ORDER_NOT_DISBURSABLE, 409,
                                  "Order is not in a disbursable state")
        d["status"] = "APPROVED"
        touch(d)
    elif to_status == "WIRED":
        if cur != "APPROVED":
            raise errors.invalid_state("Disbursement is not APPROVED")
        order = db.orders.get(d["order_id"])
        # Fiscal (priority 10): amount must not exceed escrow balance.
        if d["amount_cents"] > escrow_balance(d["order_id"]):
            raise errors.ApiError(errors.ERR_INSUFFICIENT_ESCROW, 409,
                                  "Disbursement amount exceeds escrow balance")
        # Temporal (priority 8): half-open wire window must not overlap any other
        # WIRED window on the same order.
        a_start = _parse_dt(d["wire_window_start"], "wire_window_start")
        a_end = _parse_dt(d["wire_window_end"], "wire_window_end")
        for other in db.disbursements.values():
            if other["id"] == d["id"] or other["order_id"] != d["order_id"]:
                continue
            if other["status"] != "WIRED":
                continue
            b_start = _parse_dt(other["wire_window_start"], "wire_window_start")
            b_end = _parse_dt(other["wire_window_end"], "wire_window_end")
            if _windows_overlap(a_start, a_end, b_start, b_end):
                raise errors.ApiError(errors.ERR_WIRE_WINDOW_OVERLAP, 409,
                                      "Wire window overlaps another WIRED disbursement")
        d["status"] = "WIRED"
        touch(d)
        # Cascade B: escrow recomputed (live); auto-close from CLEAR_TO_CLOSE at 0.
        if order is not None and escrow_balance(order["id"]) == 0 \
                and order["status"] == "CLEAR_TO_CLOSE":
            order["status"] = "CLOSED"
            order["gap_open"] = False
            touch(order)
    elif to_status == "VOID":
        if cur not in ("REQUESTED", "APPROVED"):
            raise errors.invalid_state("Disbursement cannot be voided from " + cur)
        d["status"] = "VOID"
        touch(d)
    else:
        raise errors.invalid_state("Unsupported disbursement transition")

    return success(serialize_disbursement(d), status=200)
