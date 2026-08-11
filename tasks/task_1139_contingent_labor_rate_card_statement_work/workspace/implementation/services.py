"""Business logic: calculations, cascades, ledger, invoices, audits.

Every rule here traces to SCAFFOLD.yaml section 1.3 (calculations) and
PRD section 3 (workflows). Money is integer cents; rounding is
round-half-up wherever a rounding step is specified.
"""

import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import now_iso, stamp_new, stamp_new_light, store, today, today_str, touch

# ---- constants (scaffold 1.3) ----
TIER_MARKUP_CAP = {
    "PREFERRED": Decimal("0.25"),
    "APPROVED": Decimal("0.20"),
    "PROBATION": Decimal("0.15"),
}
PARALLEL_CAP = {"PREFERRED": 5, "APPROVED": 3}
DISTRIBUTION_FANOUT = 3
NULL_SCORE_AS = 70
RESPONSE_WINDOW_DAYS = 7
MIN_PLACEMENTS_FOR_SCORING = 3
FEE_TIER_THRESHOLD_CENTS = 10000000
FEE_RATE_BELOW = Decimal("0.015")
FEE_RATE_AT_OR_ABOVE = Decimal("0.010")
LINE_INVOICE_FEE_CENTS = 5000
CONVERSION_BASE_FEE_CENTS = 2500000
PRORATA_HORIZON_DAYS = 730
TENURE_LIMIT_DAYS = 730
TENURE_RISK_WARN_DAYS = 700
BUDGET_AUDIT_THRESHOLD_PCT = 95


def parse_d(s):
    return date.fromisoformat(s)


def round_cents(d):
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ------------------------------------------------------------------
# markup_transparency_check (integer cross-multiplication, no floats)
# ------------------------------------------------------------------
def markup_allowed(bill_rate_cents, pay_rate_cents, card, tier):
    cap = min(Decimal(str(card["max_markup_pct"])), TIER_MARKUP_CAP[tier])
    cap_bp = round_cents(cap * 10000)
    return bill_rate_cents * 10000 <= pay_rate_cents * (10000 + cap_bp)


# ------------------------------------------------------------------
# governing rate card resolution (half-open window contains clock date)
# ------------------------------------------------------------------
def governing_card(role_code, skill_code, geo_code, on_date=None):
    on_date = on_date or today()
    for c in store.rate_cards.values():
        if (
            c["status"] == "ACTIVE"
            and c["role_code"] == role_code
            and c["skill_code"] == skill_code
            and c["geo_code"] == geo_code
            and parse_d(c["effective_from"]) <= on_date < parse_d(c["effective_to"])
        ):
            return c
    return None


# ------------------------------------------------------------------
# tenure_accumulation (closed, both-endpoints-inclusive day spans)
# ------------------------------------------------------------------
def _assignment_span_days(a, through_date):
    start = parse_d(a["start_date"])
    if a["status"] in ("COMPLETED", "TERMINATED"):
        eff = parse_d(a["actual_end_date"])
    elif a["status"] == "PENDING":
        eff = parse_d(a["end_date"])
    else:  # ACTIVE
        eff = min(parse_d(a["end_date"]), through_date)
    end = min(eff, through_date)
    return max(0, (end - start).days + 1)


def worker_assignments(worker_id):
    return [a for a in store.assignments.values() if a["worker_id"] == worker_id]


def cumulative_tenure(worker):
    through = today()
    total = worker["tenure_carryover_days"]
    for a in worker_assignments(worker["id"]):
        total += _assignment_span_days(a, through)
    return total


def projected_tenure_on_create(worker, start_date_str, end_date_str):
    """Cumulative tenure as it would stand with the new assignment booked.

    The new (PENDING) assignment contributes its full closed span
    start..end; existing assignments contribute their current spans.
    """
    total = worker["tenure_carryover_days"]
    for a in worker_assignments(worker["id"]):
        total += _assignment_span_days(a, today())
    total += max(0, (parse_d(end_date_str) - parse_d(start_date_str)).days + 1)
    return total


def projected_tenure_on_extend(worker, subject, new_end_date_str):
    """Cumulative tenure with the subject assignment's end_date replaced."""
    total = worker["tenure_carryover_days"]
    for a in worker_assignments(worker["id"]):
        if a["id"] == subject["id"]:
            start = parse_d(a["start_date"])
            total += max(0, (parse_d(new_end_date_str) - start).days + 1)
        else:
            total += _assignment_span_days(a, today())
    return total


# ------------------------------------------------------------------
# misclassification_risk
# ------------------------------------------------------------------
def misclassification_risk(eng):
    if eng["engagement_type"] == "SOW" and (
        eng["payment_basis"] == "HOURLY" or eng["supervision_level"] == "DAILY"
    ):
        return "HIGH"
    if eng["engagement_type"] == "REQUISITION" and eng["payment_basis"] == "FIXED":
        return "HIGH"
    return "LOW"


# ------------------------------------------------------------------
# distribution_selector (deterministic total order; id never ranks)
# ------------------------------------------------------------------
def select_suppliers():
    pool = []
    for s in store.suppliers.values():
        if s["status"] != "ACTIVE":
            continue
        if s["tier"] not in ("PREFERRED", "APPROVED"):
            continue
        if s["open_offers_count"] >= PARALLEL_CAP[s["tier"]]:
            continue
        pool.append(s)
    pool.sort(
        key=lambda s: (
            0 if s["tier"] == "PREFERRED" else 1,
            -(s["tier_score"] if s["tier_score"] is not None else NULL_SCORE_AS),
            s["created_at"],
            s["supplier_code"],
        )
    )
    return pool[:DISTRIBUTION_FANOUT]


# ------------------------------------------------------------------
# supplier_tier_score
# ------------------------------------------------------------------
def run_tier_evaluation(sup):
    if sup["completed_assignments_count"] < MIN_PLACEMENTS_FOR_SCORING:
        return  # insufficient data: tier_score stays null, tier unchanged
    fill = min(
        Decimal(1),
        Decimal(sup["offers_filled_count"]) / max(1, sup["offers_made_count"]),
    )
    compliance = max(
        Decimal(0),
        1 - Decimal(sup["open_violation_count"]) / max(1, sup["completed_assignments_count"]),
    )
    acceptance = min(
        Decimal(1),
        Decimal(sup["milestones_accepted_count"]) / max(1, sup["milestones_delivered_count"]),
    )
    score = round_cents(
        100
        * (
            Decimal("0.4") * fill
            + Decimal("0.4") * compliance
            + Decimal("0.2") * acceptance
        )
    )
    sup["tier_score"] = score
    if score >= 85:
        sup["tier"] = "PREFERRED"
    elif score >= 70:
        sup["tier"] = "APPROVED"
    else:
        sup["tier"] = "PROBATION"


# ------------------------------------------------------------------
# conversion_fee (SCHEDULE step function vs PRORATA linear decay)
# ------------------------------------------------------------------
def conversion_fee(tenure_days, prorata_flag, tier):
    if prorata_flag and tier == "PREFERRED":
        factor = max(Decimal(0), 1 - Decimal(tenure_days) / Decimal(PRORATA_HORIZON_DAYS))
        fee = round_cents(Decimal(CONVERSION_BASE_FEE_CENTS) * factor)
        return "PRORATA", fee
    if tenure_days < 180:
        band = Decimal("1.00")
    elif tenure_days <= 364:
        band = Decimal("0.75")
    elif tenure_days <= 544:
        band = Decimal("0.50")
    else:
        band = Decimal("0.00")
    return "SCHEDULE", int(Decimal(CONVERSION_BASE_FEE_CENTS) * band)


# ------------------------------------------------------------------
# committed_spend + 95% budget-utilization audit cascade
# ------------------------------------------------------------------
def recompute_committed(eng):
    total = 0
    for t in store.timesheets.values():
        a = store.assignments.get(t["assignment_id"])
        if a and a["engagement_id"] == eng["id"] and t["status"] == "APPROVED":
            total += t["final_amount_cents"] or 0
    for m in store.milestones.values():
        if m["engagement_id"] == eng["id"] and m["acceptance_status"] == "ACCEPTED":
            total += m["amount_cents"]
    eng["committed_spend_cents"] = total
    return total


def maybe_raise_budget_audit(eng, supplier_id, committed_before):
    """Raise BUDGET_UTILIZATION on a below->at-or-above 95% crossing, once."""
    if eng["budget_audit_raised"]:
        return
    budget = eng["budget_cents"]
    after = eng["committed_spend_cents"]
    if committed_before * 100 < BUDGET_AUDIT_THRESHOLD_PCT * budget <= after * 100:
        create_audit(
            supplier_id=supplier_id,
            finding="BUDGET_UTILIZATION",
            severity="HIGH",
            details=(
                f"Committed spend {after} reached at least "
                f"{BUDGET_AUDIT_THRESHOLD_PCT}% of budget {budget}."
            ),
            engagement_id=eng["id"],
        )
        eng["budget_audit_raised"] = True


# ------------------------------------------------------------------
# compliance audit rows
# ------------------------------------------------------------------
def create_audit(supplier_id, finding, severity, details, engagement_id=None,
                 timesheet_id=None, assignment_id=None):
    rec = {
        "supplier_id": supplier_id,
        "engagement_id": engagement_id,
        "timesheet_id": timesheet_id,
        "assignment_id": assignment_id,
        "finding": finding,
        "severity": severity,
        "status": "OPEN",
        "details": details,
        "resolution_note": None,
    }
    stamp_new(rec)
    store.audits[rec["id"]] = rec
    sup = store.suppliers.get(supplier_id)
    if sup is not None:
        sup["open_violation_count"] += 1
        touch(sup)
    return rec


# ------------------------------------------------------------------
# spend ledger (append-only)
# ------------------------------------------------------------------
def append_ledger(supplier, engagement_id, entry_type, delta_cents,
                  timesheet_id=None, milestone_id=None):
    supplier["spend_ytd_cents"] += delta_cents
    touch(supplier)
    rec = {
        "supplier_id": supplier["id"],
        "engagement_id": engagement_id,
        "timesheet_id": timesheet_id,
        "milestone_id": milestone_id,
        "invoice_id": None,
        "entry_type": entry_type,
        "delta_cents": delta_cents,
        "running_balance_cents": supplier["spend_ytd_cents"],
    }
    stamp_new_light(rec)
    store.ledger[rec["id"]] = rec
    return rec


# ------------------------------------------------------------------
# invoice consolidation (per-line rounding pinned upstream)
# ------------------------------------------------------------------
def get_open_invoice(supplier_id):
    for inv in store.invoices.values():
        if inv["supplier_id"] == supplier_id and inv["status"] == "OPEN":
            return inv
    return None


def get_or_create_open_invoice(supplier_id):
    inv = get_open_invoice(supplier_id)
    if inv is not None:
        return inv
    d = today()
    last_day = calendar.monthrange(d.year, d.month)[1]
    rec = {
        "supplier_id": supplier_id,
        "period_start": d.replace(day=1).isoformat(),
        "period_end": d.replace(day=last_day).isoformat(),
        "status": "OPEN",
        "line_count": 0,
        "subtotal_cents": 0,
        "processing_fee_cents": 0,
        "total_cents": 0,
        "consolidation_savings_cents": 0,
        "finalized_by_user_id": None,
        "paid_by_user_id": None,
        "void_reason": None,
    }
    stamp_new(rec)
    store.invoices[rec["id"]] = rec
    return rec


def invoice_lines_of(invoice_id):
    return [l for l in store.invoice_lines.values() if l["invoice_id"] == invoice_id]


def recompute_invoice(inv):
    lines = invoice_lines_of(inv["id"])
    inv["line_count"] = len(lines)
    inv["subtotal_cents"] = sum(l["amount_cents"] for l in lines)
    inv["total_cents"] = inv["subtotal_cents"] + inv["processing_fee_cents"]


def attach_invoice_line(inv, amount_cents, timesheet_id=None, milestone_id=None):
    rec = {
        "invoice_id": inv["id"],
        "timesheet_id": timesheet_id,
        "milestone_id": milestone_id,
        "amount_cents": amount_cents,
    }
    stamp_new_light(rec)
    store.invoice_lines[rec["id"]] = rec
    recompute_invoice(inv)
    return rec


# ------------------------------------------------------------------
# worker offboarding cascade
# ------------------------------------------------------------------
def worker_offboard_cascade(worker):
    """Worker with no remaining PENDING/ACTIVE assignment -> OFFBOARDING."""
    if worker["status"] not in ("ONBOARDING", "ACTIVE"):
        return
    for a in worker_assignments(worker["id"]):
        if a["status"] in ("PENDING", "ACTIVE"):
            return
    worker["status"] = "OFFBOARDING"
    touch(worker)


# ------------------------------------------------------------------
# approval cascade shared by timesheet approve and milestone accept
# ------------------------------------------------------------------
def run_billable_event(eng, supplier, amount_cents, entry_type,
                       timesheet_id=None, milestone_id=None):
    committed_before = eng["committed_spend_cents"]
    append_ledger(supplier, eng["id"], entry_type, amount_cents,
                  timesheet_id=timesheet_id, milestone_id=milestone_id)
    inv = get_or_create_open_invoice(supplier["id"])
    attach_invoice_line(inv, amount_cents, timesheet_id=timesheet_id,
                        milestone_id=milestone_id)
    recompute_committed(eng)
    maybe_raise_budget_audit(eng, supplier["id"], committed_before)
    touch(eng)
