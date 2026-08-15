"""Shared domain logic: calculations, cascades, recomputations, selectors."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

import db
import errors

# ---------------------------------------------------------------------------
# Calculation constants (scaffold §1.3)
# ---------------------------------------------------------------------------

# project_incentive_amount
TIER1_KWH = 2000
TIER1_RATE_PER_KWH_CENTS = 25
TIER2_RATE_PER_KWH_CENTS = 12
INCENTIVE_CAP_CENTS = 80000
MEASURE_COST_BASELINE_CENTS = 500000

# contractor_qa_score
QA_WINDOW_DEFAULT = 10
QA_SUSPENSION_THRESHOLD_BPS = 5000

# trc_cost_effectiveness
MEASURE_LIFE_YEARS = 12
DISCOUNT_RATE = Decimal("0.04")
AVOIDED_COST_PER_KWH_CENTS = 11

# complaint_recency_window
COMPLAINT_WINDOW_DAYS = 90

# remediation window (scaffold references REMEDIATION_WINDOW_DAYS but doesn't
# pin the value; PRD §3.6 says "a fixed number of days". We use 30.)
REMEDIATION_WINDOW_DAYS = 30


# ---------------------------------------------------------------------------
# Incentive calculation (project_incentive_amount + incentive_final_amount)
# ---------------------------------------------------------------------------


def compute_incentive(project: dict, variant: str) -> int:
    """variant: "PROVISIONAL" (floor) or "FINAL" (round-half-up with cost
    overrun adjustment)."""
    savings = Decimal(str(project["estimated_annual_kwh_savings"]))
    cost = Decimal(str(project["measure_cost_cents"]))
    if variant == "FINAL" and cost > MEASURE_COST_BASELINE_CENTS:
        ratio = Decimal(MEASURE_COST_BASELINE_CENTS) / cost
        if ratio > Decimal("1.0"):
            ratio = Decimal("1.0")
        savings = savings * ratio
    tier1 = savings if savings < TIER1_KWH else Decimal(TIER1_KWH)
    tier2 = savings - TIER1_KWH
    if tier2 < 0:
        tier2 = Decimal(0)
    raw = tier1 * TIER1_RATE_PER_KWH_CENTS + tier2 * TIER2_RATE_PER_KWH_CENTS
    capped = raw if raw < INCENTIVE_CAP_CENTS else Decimal(INCENTIVE_CAP_CENTS)
    if variant == "PROVISIONAL":
        return int(capped.quantize(Decimal("1"), rounding=ROUND_FLOOR))
    return int(capped.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Contractor recomputes
# ---------------------------------------------------------------------------


def recorded_inspections_for_contractor(contractor_id: str):
    """All RECORDED inspections for projects executed by this contractor,
    newest first by updated_at (recorded time)."""
    out = []
    for insp in db.inspections.values():
        if insp.get("status") != "RECORDED":
            continue
        proj = db.projects.get(insp.get("project_id"))
        if proj is None:
            continue
        if proj.get("contractor_id") != contractor_id:
            continue
        out.append(insp)
    out.sort(key=lambda r: (r.get("updated_at") or "", r.get("created_at") or ""), reverse=True)
    return out


def recompute_qa_score(contractor: dict) -> None:
    window = contractor.get("qa_window_size", QA_WINDOW_DEFAULT)
    recorded = recorded_inspections_for_contractor(contractor["id"])[:window]
    if not recorded:
        contractor["qa_score_bps"] = 10000
        db.touch(contractor)
        return
    total = sum(int(i.get("score_bps") or 0) for i in recorded)
    mean = (Decimal(total) / Decimal(len(recorded))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    contractor["qa_score_bps"] = int(mean)
    db.touch(contractor)


def recompute_install_counts(contractor: dict) -> None:
    on_time = 0
    late = 0
    for wo in db.work_orders.values():
        if wo.get("contractor_id") != contractor["id"]:
            continue
        if wo.get("status") != "COMPLETED":
            continue
        completed_on = wo.get("completed_on")
        scheduled_on = wo.get("scheduled_on")
        if not completed_on or not scheduled_on:
            continue
        if db.parse_dt(completed_on) <= db.parse_dt(scheduled_on):
            on_time += 1
        else:
            late += 1
    contractor["on_time_installs"] = on_time
    contractor["late_installs"] = late
    db.touch(contractor)


def recompute_complaint_count(contractor: dict) -> None:
    cutoff = db.get_clock() - timedelta(days=COMPLAINT_WINDOW_DAYS)
    n = 0
    for c in db.complaints.values():
        if c.get("contractor_id") != contractor["id"]:
            continue
        if c.get("status") not in ("OPEN", "IN_REVIEW", "ESCALATED"):
            continue
        created = db.parse_dt(c["created_at"])
        if created >= cutoff:
            n += 1
    contractor["complaint_count_90d"] = n
    db.touch(contractor)


def recompute_active_cert_count(contractor: dict) -> None:
    n = sum(
        1
        for cert in db.certifications.values()
        if cert.get("contractor_id") == contractor["id"] and cert.get("status") == "ACTIVE"
    )
    contractor["active_certification_count"] = n


def has_active_certification(contractor_id: str, measure_type: str | None = None) -> bool:
    for cert in db.certifications.values():
        if cert.get("contractor_id") != contractor_id:
            continue
        if cert.get("status") != "ACTIVE":
            continue
        if measure_type is not None and cert.get("measure_type") != measure_type:
            continue
        return True
    return False


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------


def expire_offered_leads(contractor_id: str) -> None:
    """Cascade used on contractor suspension: OFFERED leads -> EXPIRED and
    assigned_contractor_id cleared."""
    for lead in db.leads.values():
        if lead.get("status") != "OFFERED":
            continue
        if lead.get("assigned_contractor_id") != contractor_id:
            continue
        lead["status"] = "EXPIRED"
        lead["assigned_contractor_id"] = None
        db.touch(lead)


def withdraw_open_leads(contractor_id: str) -> None:
    """Cascade used on contractor termination: NEW or OFFERED leads assigned
    to this contractor -> WITHDRAWN (clears assigned_contractor_id when set)."""
    for lead in db.leads.values():
        if lead.get("status") not in ("NEW", "OFFERED"):
            continue
        if lead.get("assigned_contractor_id") != contractor_id:
            continue
        lead["status"] = "WITHDRAWN"
        lead["assigned_contractor_id"] = None
        db.touch(lead)


def suspend_contractor(contractor: dict) -> None:
    """Shared suspension logic (manual or automatic)."""
    if contractor.get("status") != "APPROVED":
        return
    contractor["status"] = "SUSPENDED"
    db.touch(contractor)
    expire_offered_leads(contractor["id"])


def count_escalated_complaints(contractor_id: str) -> int:
    return sum(
        1
        for c in db.complaints.values()
        if c.get("contractor_id") == contractor_id and c.get("status") == "ESCALATED"
    )


# ---------------------------------------------------------------------------
# Calendar overlap (half-open [start, start+duration) on the same date)
# ---------------------------------------------------------------------------


def intervals_overlap(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end


def has_calendar_conflict(contractor_id: str, scheduled_on_iso: str, duration_hours: int, exclude_wo_id: str | None = None) -> bool:
    new_start = db.parse_dt(scheduled_on_iso)
    new_end = new_start + timedelta(hours=int(duration_hours))
    new_date = new_start.date()
    for wo in db.work_orders.values():
        if wo.get("contractor_id") != contractor_id:
            continue
        if exclude_wo_id is not None and wo.get("id") == exclude_wo_id:
            continue
        if wo.get("status") not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if wo.get("direct_install"):
            continue
        ex_start = db.parse_dt(wo["scheduled_on"])
        if ex_start.date() != new_date:
            continue
        ex_end = ex_start + timedelta(hours=int(wo.get("duration_hours") or 0))
        if intervals_overlap(new_start, new_end, ex_start, ex_end):
            return True
    return False


# ---------------------------------------------------------------------------
# TRC report computation
# ---------------------------------------------------------------------------


def compute_report_fields(program: dict, period_start, period_end, total_admin_cost_cents: int):
    ps = db.parse_dt(period_start)
    pe = db.parse_dt(period_end)

    completed_projects = [
        p
        for p in db.projects.values()
        if p.get("program_id") == program["id"]
        and p.get("status") == "COMPLETED"
        and ps <= db.parse_dt(p["updated_at"]) < pe
    ]
    project_ids = {p["id"] for p in completed_projects}

    total_avoided_kwh = sum(int(p.get("estimated_annual_kwh_savings") or 0) for p in completed_projects)

    total_incentive_paid = 0
    for pay in db.payments.values():
        if pay.get("project_id") not in project_ids:
            continue
        if pay.get("status") not in ("PAID", "RECONCILED"):
            continue
        total_incentive_paid += int(pay.get("amount_cents") or 0)

    customer_incremental = 0
    for p in completed_projects:
        diff = int(p.get("measure_cost_cents") or 0) - int(p.get("incentive_amount_cents") or 0)
        if diff > 0:
            customer_incremental += diff

    # Benefit: 4-decimal intermediate precision, end-of-year discounting.
    benefit = Decimal(0)
    annual_value = (Decimal(total_avoided_kwh) * Decimal(AVOIDED_COST_PER_KWH_CENTS)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    for t in range(1, MEASURE_LIFE_YEARS + 1):
        term = annual_value / ((Decimal(1) + DISCOUNT_RATE) ** t)
        term = term.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        benefit += term
    benefit = benefit.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    denominator = Decimal(total_incentive_paid) + Decimal(total_admin_cost_cents) + Decimal(customer_incremental)
    if denominator <= 0:
        raise errors.ApiError(
            errors.ERR_INVALID_STATE,
            "Report denominator must be greater than zero",
            409,
        )
    trc_ratio = (benefit / denominator).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    threshold = Decimal(str(program.get("trc_threshold")))
    if trc_ratio >= threshold:
        flag = "PASS"
    elif trc_ratio >= (threshold - Decimal("0.10")):
        flag = "MARGINAL"
    else:
        flag = "FAIL"

    return {
        "total_incentive_paid_cents": int(total_incentive_paid),
        "total_avoided_kwh": int(total_avoided_kwh),
        "trc_ratio": float(trc_ratio),
        "trc_flag": flag,
    }


# ---------------------------------------------------------------------------
# Lead distribution selector
# ---------------------------------------------------------------------------


def eligible_contractors_for_lead(lead: dict):
    program = db.programs.get(lead["program_id"])
    customer = db.customers.get(lead["customer_id"])
    if program is None or customer is None:
        return []
    out = []
    for c in db.contractors.values():
        if c.get("status") != "APPROVED":
            continue
        if c.get("sector") != program.get("sector"):
            continue
        if customer.get("service_zip") not in (c.get("service_zip_codes") or []):
            continue
        if not has_active_certification(c["id"], lead.get("measure_type")):
            continue
        out.append(c)
    return out


def any_contractor_with_measure_cert(measure_type: str) -> bool:
    """True when at least one APPROVED contractor carries an ACTIVE cert for
    this measure type (used for the distribute ordering rule)."""
    for c in db.contractors.values():
        if c.get("status") != "APPROVED":
            continue
        if has_active_certification(c["id"], measure_type):
            return True
    return False


def rank_candidates(candidates):
    """Rank per selector: qa_score_bps DESC, complaint_count_90d ASC,
    created_at ASC. Returns (winner, ranking_key, tie_break_used)."""
    def sort_key(c):
        return (
            -int(c.get("qa_score_bps") or 0),
            int(c.get("complaint_count_90d") or 0),
            c.get("created_at") or "",
            c.get("id") or "",
        )

    ordered = sorted(candidates, key=sort_key)
    winner = ordered[0]
    if len(ordered) == 1:
        return winner, "qa_score_bps", False
    first, second = ordered[0], ordered[1]
    if int(first.get("qa_score_bps") or 0) != int(second.get("qa_score_bps") or 0):
        return winner, "qa_score_bps", False
    if int(first.get("complaint_count_90d") or 0) != int(second.get("complaint_count_90d") or 0):
        return winner, "complaint_count_90d", True
    return winner, "created_at", True
