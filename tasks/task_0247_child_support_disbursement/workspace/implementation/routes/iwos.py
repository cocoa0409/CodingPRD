"""IncomeWithholdingOrder routes."""

from flask import Blueprint, request

import errors
import lookup
from common import (
    stamp_create, touch, get_body, as_int, as_str, fk,
    pagination, paginate, sort_by_created,
)
from db import store, parse_iso
from middleware import require_roles
from response import object_response, array_response
from services import serialize

bp = Blueprint("iwos", __name__)


@bp.route("/income-withholding-orders", methods=["POST"])
@require_roles("CaseWorker")
def create_iwo(auth):
    body = get_body()
    # Existence (priority 3), left-to-right.
    order = lookup.support_order(fk(body, "support_order_id"))
    employer = lookup.employer(fk(body, "employer_id"))
    # Structural validity (priority 5).
    ordered_amount_cents = as_int(body, "ordered_amount_cents")
    start_raw = as_str(body, "effective_start_at")
    end_raw = as_str(body, "effective_end_at")
    start = parse_iso(start_raw)
    end = parse_iso(end_raw)
    if start is None or end is None:
        raise errors.invalid_request("effective_start_at / effective_end_at must be ISO 8601")
    # ERR_INVALID_AMOUNT (priority 13): ordered amount must be > 0.
    if ordered_amount_cents <= 0:
        raise errors.invalid_amount()
    # ERR_IWO_PERIOD_OVERLAP (priority 18): half-open [start, end) vs any
    # non-TERMINATED IWO on the same order; adjacency (end == next start) ok.
    for other in store.income_withholding_orders.values():
        if other["support_order_id"] != order["id"]:
            continue
        if other["status"] == "TERMINATED":
            continue
        o_start = parse_iso(other["effective_start_at"])
        o_end = parse_iso(other["effective_end_at"])
        # Half-open overlap: start < o_end AND o_start < end.
        if start < o_end and o_start < end:
            raise errors.iwo_period_overlap()
    rec = stamp_create({
        "support_order_id": order["id"],
        "employer_id": employer["id"],
        "ordered_amount_cents": ordered_amount_cents,
        "effective_start_at": start_raw,
        "effective_end_at": end_raw,
        "status": "ISSUED",
    })
    store.income_withholding_orders[rec["id"]] = rec
    return object_response(serialize.income_withholding_order(rec), 201)


@bp.route("/income-withholding-orders/<rid>", methods=["GET"])
@require_roles("CaseWorker", "FinanceOfficer", "Employer")
def get_iwo(auth, rid):
    rec = lookup.iwo(rid)
    lookup.require(lookup.owns_iwo(auth, rec))
    return object_response(serialize.income_withholding_order(rec), 200)


@bp.route("/income-withholding-orders", methods=["GET"])
@require_roles("CaseWorker", "FinanceOfficer", "Employer")
def list_iwos(auth):
    so_id = request.args.get("support_order_id")
    emp_id = request.args.get("employer_id")
    items = list(store.income_withholding_orders.values())
    if so_id is not None:
        items = [i for i in items if i["support_order_id"] == so_id]
    if emp_id is not None:
        items = [i for i in items if i["employer_id"] == emp_id]
    # Employer ownership scope on list reads.
    if auth.role == "Employer":
        items = [i for i in items if i["employer_id"] == auth.user_id]
    items = sort_by_created(items)
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return array_response([serialize.income_withholding_order(i) for i in page],
                          limit, offset, total, 200)


@bp.route("/income-withholding-orders/<rid>/acknowledge", methods=["POST"])
@require_roles("Employer")
def acknowledge_iwo(auth, rid):
    rec = lookup.iwo(rid)
    lookup.require(lookup.owns_iwo(auth, rec))
    if rec["status"] != "ISSUED":
        raise errors.invalid_state()
    rec["status"] = "ACKNOWLEDGED"
    touch(rec)
    return object_response(serialize.income_withholding_order(rec), 200)


@bp.route("/income-withholding-orders/<rid>/terminate", methods=["POST"])
@require_roles("CaseWorker")
def terminate_iwo(auth, rid):
    rec = lookup.iwo(rid)
    if rec["status"] not in ("ISSUED", "ACKNOWLEDGED"):
        raise errors.invalid_state()
    rec["status"] = "TERMINATED"
    touch(rec)
    return object_response(serialize.income_withholding_order(rec), 200)
