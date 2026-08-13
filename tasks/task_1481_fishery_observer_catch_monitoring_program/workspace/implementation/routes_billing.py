"""Cost recovery: invoices, payments, adjustments, disputes, waivers,
the operations checkpoint, and the logical clock (PRD 3.9, 2.7)."""

from datetime import timedelta

from flask import Blueprint

import logic
import store
from core import (
    ALL_ROLES, ApiError, body, err_forbidden, err_invalid, err_state,
    get_or_404, is_int, list_response, ok, parse_dt, req_int, req_str,
    require_roles,
)

bp = Blueprint("billing", __name__, url_prefix="/observer-program")

PAYABLE_STATUSES = ("ISSUED", "PARTIALLY_PAID", "OVERDUE")
ADJUSTABLE_STATUSES = ("ISSUED", "OVERDUE", "DISPUTED")


# ---------------------------------------------------------------------------
# Invoice generation
# ---------------------------------------------------------------------------


@bp.post("/coverage-plans/<pid>/invoices/generate")
def generate_invoices(pid):
    require_roles("ProgramCoordinator")
    plan = get_or_404("coverage_plans", pid, "CoveragePlan")
    if plan["status"] not in ("SELECTION_COMPLETED", "CLOSED"):
        raise ApiError("ERR_PLAN_NOT_PUBLISHED", 409,
                       "Invoice generation requires a SELECTION_COMPLETED or CLOSED plan")
    created, skipped = logic.generate_invoices_for_plan(plan)
    return ok({"created_invoice_ids": created, "skipped_vessel_ids": skipped}, status=201)


# ---------------------------------------------------------------------------
# Invoice reads
# ---------------------------------------------------------------------------


@bp.get("/invoices")
def list_invoices():
    require_roles(*ALL_ROLES)
    return list_response("invoices", {
        "coverage_plan_id": "coverage_plan_id",
        "vessel_id": "vessel_id",
        "operator_id": "operator_id",
        "status": "status",
    })


@bp.get("/invoices/<iid>")
def get_invoice(iid):
    require_roles(*ALL_ROLES)
    return ok(get_or_404("invoices", iid, "Invoice"))


# ---------------------------------------------------------------------------
# Invoice lifecycle
# ---------------------------------------------------------------------------


@bp.post("/invoices/<iid>/issue")
def issue_invoice(iid):
    a = require_roles("ProgramCoordinator")
    inv = get_or_404("invoices", iid, "Invoice")
    if inv["status"] != "DRAFT":
        raise err_state("Only a DRAFT invoice can be issued")
    clock = store.clock_now()
    inv["issued_by_user_id"] = a["id"]
    inv["issue_date"] = store.fmt_clock(clock)
    inv["due_date"] = store.fmt_clock(clock + timedelta(days=logic.INVOICE_DUE_DAYS))
    inv["status"] = "ISSUED"
    store.touch(inv)
    return ok(inv)


def _operator_owns_invoice(a, inv):
    if inv["operator_id"] != a["id"]:
        raise err_forbidden("The acting operator does not own this invoice")


@bp.post("/invoices/<iid>/payments")
def make_payment(iid):
    a = require_roles("VesselOperator")
    inv = get_or_404("invoices", iid, "Invoice")
    _operator_owns_invoice(a, inv)
    b = body()
    amount = b.get("amount_cents")
    if amount is None or not is_int(amount):
        raise err_invalid("Field 'amount_cents' is required and must be an integer")
    if inv["status"] not in PAYABLE_STATUSES:
        raise ApiError("ERR_INVOICE_NOT_ISSUED", 409,
                       "Payments are accepted only on ISSUED, PARTIALLY_PAID, or OVERDUE invoices")
    outstanding = logic.invoice_outstanding(inv)
    if amount <= 0:
        raise ApiError("ERR_PAYMENT_NOT_POSITIVE", 422,
                       "Payment amount_cents must be positive")
    if amount > outstanding:
        raise ApiError("ERR_PAYMENT_EXCEEDS_OUTSTANDING", 422,
                       "Payment exceeds the outstanding balance")
    inv["amount_paid_cents"] += amount
    inv["amount_outstanding_cents"] = logic.invoice_outstanding(inv)
    if inv["amount_outstanding_cents"] == 0:
        inv["status"] = "PAID"
        op = store.db["operators"].get(inv["operator_id"])
        if op is not None:
            logic.restore_standing_if_clear(op)
    elif inv["status"] == "ISSUED":
        inv["status"] = "PARTIALLY_PAID"
    store.touch(inv)
    return ok(inv, status=201)


@bp.post("/invoices/<iid>/adjustments")
def post_adjustment(iid):
    a = require_roles("ProgramAdmin")
    inv = get_or_404("invoices", iid, "Invoice")
    # Segregation of duties (priority 2): the issuer may not adjust.
    if inv["issued_by_user_id"] is not None and inv["issued_by_user_id"] == a["id"]:
        raise ApiError("ERR_INVOICE_ADJUSTMENT_FORBIDDEN", 403,
                       "The issuer of an invoice may not adjust it")
    b = body()
    adjustment = b.get("adjustment_cents")
    if adjustment is None or not is_int(adjustment):
        raise err_invalid("Field 'adjustment_cents' is required and must be an integer")
    req_str(b, "reason")
    expected = b.get("expected_invoice_version")
    if expected is None or not is_int(expected):
        raise err_invalid("Field 'expected_invoice_version' is required and must be an integer")
    if expected != inv["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_invoice_version does not match the invoice's current version")
    if inv["status"] not in ADJUSTABLE_STATUSES:
        raise err_state("Adjustments are permitted only on ISSUED, OVERDUE, or DISPUTED invoices")
    if logic.invoice_outstanding(inv) + adjustment < 0:
        raise ApiError("ERR_ADJUSTMENT_WOULD_UNDERFLOW", 422,
                       "The adjustment would drive the outstanding balance below zero")
    inv["amount_adjusted_cents"] += adjustment
    inv["amount_outstanding_cents"] = logic.invoice_outstanding(inv)
    store.touch(inv)
    return ok(inv, status=201)


@bp.post("/invoices/<iid>/dispute")
def dispute_invoice(iid):
    a = require_roles("VesselOperator")
    inv = get_or_404("invoices", iid, "Invoice")
    _operator_owns_invoice(a, inv)
    b = body()
    req_str(b, "reason")
    if inv["status"] != "ISSUED":
        raise err_state("Only an ISSUED invoice can be disputed")
    inv["status"] = "DISPUTED"
    store.touch(inv)
    return ok(inv)


@bp.post("/invoices/<iid>/resolve-dispute")
def resolve_dispute(iid):
    require_roles("ProgramCoordinator")
    inv = get_or_404("invoices", iid, "Invoice")
    if inv["status"] != "DISPUTED":
        raise err_state("Only a DISPUTED invoice can be resolved")
    inv["status"] = "ISSUED"
    store.touch(inv)
    return ok(inv)


@bp.post("/invoices/<iid>/waive")
def waive_invoice(iid):
    a = require_roles("ProgramAdmin")
    inv = get_or_404("invoices", iid, "Invoice")
    if inv["issued_by_user_id"] is not None and inv["issued_by_user_id"] == a["id"]:
        raise ApiError("ERR_INVOICE_ADJUSTMENT_FORBIDDEN", 403,
                       "The issuer of an invoice may not waive it")
    b = body()
    req_str(b, "reason")
    if inv["status"] not in ADJUSTABLE_STATUSES:
        raise err_state("Only an ISSUED, DISPUTED, or OVERDUE invoice can be waived")
    inv["amount_adjusted_cents"] = inv["amount_paid_cents"] - inv["amount_due_cents"]
    inv["amount_outstanding_cents"] = 0
    inv["status"] = "WAIVED"
    op = store.db["operators"].get(inv["operator_id"])
    if op is not None:
        logic.restore_standing_if_clear(op)
    store.touch(inv)
    return ok(inv)


# ---------------------------------------------------------------------------
# Operations checkpoint + logical clock
# ---------------------------------------------------------------------------


@bp.post("/ops/run")
def ops_run():
    require_roles("ProgramAdmin", "ProgramCoordinator")
    clock = store.clock_now()
    counters = {
        "expired_notice_count": 0,
        "overdue_invoice_count": 0,
        "delinquent_operator_count": 0,
        "suspended_vessel_count": 0,
        "cancelled_deployment_count": 0,
    }
    # Sweep 1: expire lapsed ISSUED notices.
    notices = [
        n for n in store.db["selection_notices"].values()
        if n["status"] == "ISSUED" and parse_dt(n["response_deadline"]) < clock
    ]
    notices.sort(key=lambda n: (n["created_at"], n["_seq"]))
    for n in notices:
        n["status"] = "EXPIRED"
        store.touch(n)
        counters["expired_notice_count"] += 1
    # Sweep 2: past-due invoices -> OVERDUE, then the delinquency cascade.
    invoices = [
        inv for inv in store.db["invoices"].values()
        if inv["status"] in ("ISSUED", "PARTIALLY_PAID")
        and inv["due_date"] is not None
        and parse_dt(inv["due_date"]) < clock
        and logic.invoice_outstanding(inv) > 0
    ]
    invoices.sort(key=lambda inv: (inv["created_at"], inv["_seq"]))
    for inv in invoices:
        inv["status"] = "OVERDUE"
        store.touch(inv)
        counters["overdue_invoice_count"] += 1
        logic.run_delinquency_cascade(inv, counters)
    return ok(counters)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("ProgramAdmin")
    b = body()
    target = b.get("to_iso8601")
    if target is None:
        raise err_invalid("Field 'to_iso8601' is required")
    dt = parse_dt(target)
    store.clock_set(dt)
    return ok({"current_utc": store.fmt_clock(store.clock_now())})
