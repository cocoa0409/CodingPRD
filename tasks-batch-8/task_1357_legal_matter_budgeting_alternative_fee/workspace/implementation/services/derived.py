"""Derived-aggregate recomputation for matters and phase budgets (PRD §3.5).

Every event that changes inputs (time entry approve, write-down apply,
budget amendment approve, phase budget activate/void, ETC update) recomputes
the matter's derived aggregates in the same operation; each recomputation is
a mutation of the matter (updated_at refresh + version increment, §2.4).
"""
from decimal import Decimal, ROUND_HALF_UP

import db
import util

WATCH_THRESHOLD_BP = 500
WARNING_THRESHOLD_BP = 1000
BREACH_THRESHOLD_BP = 2000


def _round_half_up_bp(numer, denom):
    """round(10000 * numer / denom) with ROUND_HALF_UP."""
    val = (Decimal(10000) * Decimal(int(numer))) / Decimal(int(denom))
    return int(val.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def phases_of(matter_id):
    return [p for p in db.phase_budgets.values() if p.get("matter_id") == matter_id]


def entries_of(matter_id):
    return [e for e in db.time_entries.values() if e.get("matter_id") == matter_id]


def amendments_of(matter_id):
    return [a for a in db.budget_amendments.values() if a.get("matter_id") == matter_id]


def write_downs_of(matter_id):
    return [w for w in db.write_down_requests.values() if w.get("matter_id") == matter_id]


def reports_of(matter_id):
    return [r for r in db.accrual_reports.values() if r.get("matter_id") == matter_id]


def arrangements_of(matter_id):
    return [a for a in db.fee_arrangements.values() if a.get("matter_id") == matter_id]


def true_ups_of(matter_id):
    return [t for t in db.collar_true_ups.values() if t.get("matter_id") == matter_id]


def recompute_phase_actuals(matter_id):
    """actual_to_date_cents per phase: sum of billable_amount_cents over the
    matter's time entries in APPROVED/BILLED whose task_code matches."""
    phases = phases_of(matter_id)
    entries = entries_of(matter_id)
    for phase in phases:
        total = 0
        for e in entries:
            if e.get("status") in ("APPROVED", "BILLED") and e.get("task_code") == phase.get("task_code"):
                total += int(e.get("billable_amount_cents", 0))
        if phase.get("actual_to_date_cents") != total:
            phase["actual_to_date_cents"] = total
            util.touch(phase)


def recompute_matter(matter, bump=True):
    """Recompute every derived aggregate on the matter (net reading)."""
    mid = matter["id"]
    phases = phases_of(mid)
    entries = entries_of(mid)

    budget_total = sum(
        int(p.get("current_budget_cents", 0))
        for p in phases if p.get("status") in ("ACTIVE", "AMENDED")
    )

    actual_fees = 0
    for e in entries:
        if e.get("status") in ("APPROVED", "BILLED"):
            actual_fees += int(e.get("billable_amount_cents", 0))
        elif e.get("status") == "WRITTEN_DOWN":
            actual_fees += int(e.get("billable_amount_cents", 0)) - int(e.get("written_down_amount_cents", 0))

    write_down_total = sum(
        int(w.get("approved_amount_cents") or 0)
        for w in write_downs_of(mid) if w.get("status") == "APPLIED"
    )

    variance = actual_fees - budget_total
    if budget_total == 0:
        variance_pct = None
    else:
        variance_pct = _round_half_up_bp(variance, budget_total)

    # PRD §3.5: two readings of variance exist — the gross reading (used for
    # early-warning alerting) counts WRITTEN_DOWN entries at their original
    # billable_amount_cents; the net reading (reporting/realization) counts
    # the post-write-down remainder. Alerting therefore thresholds the gross
    # percentage; variance_cents/variance_pct_bp stay on the net reading.
    if budget_total == 0:
        alert = "NONE"
    else:
        gross_variance = (actual_fees + write_down_total) - budget_total
        gross_pct = _round_half_up_bp(gross_variance, budget_total)
        if gross_pct >= BREACH_THRESHOLD_BP:
            alert = "BREACH"
        elif gross_pct >= WARNING_THRESHOLD_BP:
            alert = "WARNING"
        elif gross_pct >= WATCH_THRESHOLD_BP:
            alert = "WATCH"
        else:
            alert = "NONE"

    etc_total = sum(
        int(p.get("etc_cents", 0))
        for p in phases if p.get("status") in ("ACTIVE", "AMENDED")
    )
    revised_forecast = actual_fees + etc_total

    if write_down_total == 0:
        realization = 10000
    else:
        realization = _round_half_up_bp(actual_fees, actual_fees + write_down_total)

    matter["budget_total_cents"] = budget_total
    matter["actual_fees_cents"] = actual_fees
    matter["write_down_total_cents"] = write_down_total
    matter["variance_cents"] = variance
    matter["variance_pct_bp"] = variance_pct
    matter["variance_alert_level"] = alert
    matter["revised_forecast_cents"] = revised_forecast
    matter["realization_rate_bp"] = realization
    if bump:
        util.touch(matter)
