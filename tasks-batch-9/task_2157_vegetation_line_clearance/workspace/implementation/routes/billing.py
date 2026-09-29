"""Billing-line endpoints."""
from datetime import timedelta

from flask import Blueprint, request

import calc
import constants as C
import envelope
import services
import store
import validate as V
from auth import ALL_ROLES, endpoint
from errors import ApiError

bp = Blueprint("billing", __name__)


@bp.post("/vm/work-orders/<wid>/billing-lines")
@endpoint(["BillingAnalyst"])
def draft_line(wid):
    work_order = V.find(store.work_orders, wid, "ERR_WORK_ORDER_NOT_FOUND")
    data = V.body()
    billing_method = V.as_enum(data, "billing_method", C.BILLING_METHODS)
    expected = V.as_integer(data, "expected_work_order_version")

    if expected != int(work_order.get("version") or 0):
        raise ApiError("ERR_STALE_WORK_ORDER_VERSION",
                       "expected_work_order_version does not match the span's version")
    if work_order.get("execution_status") != "COMPLETED":
        raise ApiError("ERR_WORK_ORDER_NOT_COMPLETE",
                       "the span is not COMPLETED")
    if billing_method != work_order.get("billing_method"):
        raise ApiError("ERR_BILLING_METHOD_MISMATCH",
                       "billing_method must equal the span's billing_method")
    existing = services.order_lines(work_order["id"])
    if any(b.get("status") in ("SUBMITTED", "APPROVED", "PAID") for b in existing):
        raise ApiError("ERR_BILLING_LINE_NOT_SUPERSEDABLE",
                       "a non-draft billing line already exists on this span")

    rec = store.new_record()
    rec.update({
        "work_order_id": work_order["id"],
        "billing_method": billing_method,
        "billable_units": 0,
        "density_multiplier": 1.00,
        "gross_cents": 0,
        "retainage_cents": 0,
        "storm_premium_cents": 0,
        "net_payable_cents": 0,
        "mobilization_credit_cents": 0,
        "final_payable_cents": 0,
        "submitted_at": None,
        "superseded_by_billing_line_id": None,
        "status": "DRAFT",
    })
    services.price_line(rec, work_order)
    store.billing_lines[rec["id"]] = rec

    for prior in existing:
        if prior.get("status") == "DRAFT":
            prior["status"] = "VOID"
            prior["superseded_by_billing_line_id"] = rec["id"]
            store.touch(prior)

    services.derive_billing_status(work_order)
    services.recompute_committed(services.plan_of_order(work_order))
    return envelope.created(store.public(rec))


def _budget_guard(line, work_order, prospective_status):
    plan = services.plan_of_order(work_order)
    if plan is None:
        return
    projected = services.committed_with(plan, line, prospective_status)
    if projected > int(plan.get("budget_cents") or 0):
        raise ApiError("ERR_BUDGET_EXCEEDED",
                       "the plan budget ceiling would be exceeded")


@bp.post("/vm/billing-lines/<bid>/submit")
@endpoint(["BillingAnalyst"])
def submit_line(bid):
    line = V.find(store.billing_lines, bid, "ERR_BILLING_LINE_NOT_FOUND")
    services.require_state(line, "billing_line", ["DRAFT"])
    work_order = store.work_orders.get(line.get("work_order_id"))
    if work_order is None or work_order.get("execution_status") != "COMPLETED":
        raise ApiError("ERR_WORK_ORDER_NOT_COMPLETE", "the span is not COMPLETED")
    _budget_guard(line, work_order, "SUBMITTED")

    line["status"] = "SUBMITTED"
    line["submitted_at"] = store.now_iso()
    store.touch(line)
    services.derive_billing_status(work_order)
    services.recompute_committed(services.plan_of_order(work_order))
    return envelope.ok(store.public(line))


@bp.post("/vm/billing-lines/<bid>/review")
@endpoint(["UtilityForester"])
def review_line(bid):
    line = V.find(store.billing_lines, bid, "ERR_BILLING_LINE_NOT_FOUND")
    data = V.body()
    outcome = V.as_enum(data, "outcome", ["APPROVE", "DISPUTE"])
    V.as_string(data, "dispute_reason", required=False)
    services.require_state(line, "billing_line", ["SUBMITTED"])

    if outcome == "DISPUTE":
        submitted = store.parse_datetime(line.get("submitted_at"))
        if submitted is not None and store.now() > submitted + timedelta(
                days=calc.DISPUTE_WINDOW_DAYS):
            raise ApiError("ERR_DISPUTE_WINDOW_EXPIRED",
                           "the 30-day dispute window has closed")
        line["status"] = "DISPUTED"
    else:
        line["status"] = "APPROVED"
    store.touch(line)
    work_order = store.work_orders.get(line.get("work_order_id"))
    if work_order is not None:
        services.derive_billing_status(work_order)
        services.recompute_committed(services.plan_of_order(work_order))
    return envelope.ok(store.public(line))


@bp.post("/vm/billing-lines/<bid>/resubmit")
@endpoint(["BillingAnalyst"])
def resubmit_line(bid):
    line = V.find(store.billing_lines, bid, "ERR_BILLING_LINE_NOT_FOUND")
    services.require_state(line, "billing_line", ["DISPUTED"])
    work_order = store.work_orders.get(line.get("work_order_id"))
    _budget_guard(line, work_order, "SUBMITTED")

    line["status"] = "SUBMITTED"
    line["submitted_at"] = store.now_iso()
    store.touch(line)
    if work_order is not None:
        services.derive_billing_status(work_order)
        services.recompute_committed(services.plan_of_order(work_order))
    return envelope.ok(store.public(line))


@bp.post("/vm/billing-lines/<bid>/void")
@endpoint(["BillingAnalyst"])
def void_line(bid):
    line = V.find(store.billing_lines, bid, "ERR_BILLING_LINE_NOT_FOUND")
    services.require_state(line, "billing_line", ["DRAFT", "DISPUTED"])
    line["status"] = "VOID"
    store.touch(line)
    work_order = store.work_orders.get(line.get("work_order_id"))
    if work_order is not None:
        services.derive_billing_status(work_order)
        services.recompute_committed(services.plan_of_order(work_order))
    return envelope.ok(store.public(line))


@bp.post("/vm/billing-lines/<bid>/pay")
@endpoint(["UtilityForester"])
def pay_line(bid):
    line = V.find(store.billing_lines, bid, "ERR_BILLING_LINE_NOT_FOUND")
    services.require_state(line, "billing_line", ["APPROVED"])
    line["status"] = "PAID"
    store.touch(line)
    work_order = store.work_orders.get(line.get("work_order_id"))
    if work_order is not None:
        services.derive_billing_status(work_order)
        services.recompute_committed(services.plan_of_order(work_order))
    return envelope.ok(store.public(line))


@bp.get("/vm/billing-lines/<bid>")
@endpoint(ALL_ROLES)
def get_line(bid):
    return envelope.ok(store.public(
        V.find(store.billing_lines, bid, "ERR_BILLING_LINE_NOT_FOUND")))


@bp.get("/vm/billing-lines")
@endpoint(ALL_ROLES)
def list_lines():
    return envelope.list_response(list(store.billing_lines.values()), {
        "work_order_id": request.args.get("work_order_id"),
        "superseded_by_billing_line_id": request.args.get("superseded_by_billing_line_id"),
        "status": request.args.get("status"),
        "billing_method": request.args.get("billing_method"),
    })
