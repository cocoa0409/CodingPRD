"""Claim pricing helpers (PRD §3.9, SCAFFOLD §1.3 claim_total)."""
import datetime

from clock import parse_iso, to_utc_date
from services import calc, lookups


def _period_dates(claim):
    """Inclusive list of UTC calendar dates in [period_start_at, period_end_at]."""
    start = to_utc_date(parse_iso(claim["period_start_at"]))
    end = to_utc_date(parse_iso(claim["period_end_at"]))
    days = []
    d = start
    while d <= end:
        days.append(d)
        d += datetime.timedelta(days=1)
    return days


def _stay_day_index(admit_at_iso, day_date):
    admit_d = to_utc_date(parse_iso(admit_at_iso))
    return (day_date - admit_d).days + 1


def _unpaid_bed_hold_dates(admission_id):
    """Set of UTC dates that are unpaid bed-hold days, from CLOSED/CONVERTED
    bed-holds (PRD §3.9 final variant).

    For each such hold, the window [leave_start_at, end) has leave_day_count
    midnights; the first paid_day_count of those midnights are paid; the
    remaining (unpaid) midnight-days are removed. We treat the days in
    chronological order: paid days come first, the rest are unpaid.
    """
    unpaid = set()
    for bh in lookups.bed_holds_for_admission(admission_id):
        if bh["status"] not in ("CLOSED", "CONVERTED_TO_DISCHARGE"):
            continue
        start = to_utc_date(parse_iso(bh["leave_start_at"]))
        end_iso = bh.get("actual_return_at") or bh["expected_return_at"]
        end = to_utc_date(parse_iso(end_iso))
        paid = bh.get("paid_day_count", 0)
        # Enumerate midnight-days (half-open): start .. end-1 inclusive.
        d = start
        idx = 0
        while d < end:
            if idx >= paid:
                unpaid.add(d)
            idx += 1
            d += datetime.timedelta(days=1)
    return unpaid


def price_claim(claim, admission, assessment, variant):
    """Return (billed_day_count, total_cents) for the given variant.

    variant == 'estimated': every calendar day in the inclusive period,
        projected as fully covered (no bed-hold deductions).
    variant == 'final': the same period minus unpaid bed-hold days.
    """
    days = _period_dates(claim)
    if variant == "final":
        unpaid = _unpaid_bed_hold_dates(admission["id"])
        days = [d for d in days if d not in unpaid]
    indices = [_stay_day_index(admission["admit_at"], d) for d in days]
    groups = calc.resolve_pricing_groups(assessment)
    rates = lookups.active_rates()
    total = calc.claim_total(indices, groups, rates)
    return len(days), total
