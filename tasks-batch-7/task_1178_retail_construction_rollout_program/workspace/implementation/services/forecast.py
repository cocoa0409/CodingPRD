"""opening_date_forecast (§3.8): conservative/optimistic forecasts, slip,
protection posture. Evaluation order pinned: budget ratios -> slip factor ->
forecast dates -> protection posture.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock
from db import store
from util import apply_changes, parse_date

PUNCH_BUFFER_DAYS = 10
VENDOR_ORDER = ("FIXTURE", "IT", "SIGNAGE")


def slip_factor_bp(site):
    prov = site["variance_ratio_provisional_bp"]
    if prov <= 500:
        return 0
    if prov <= 1500:
        return 500
    return 1500


def _permit_block_days(site, today, conservative):
    days = 0
    for p in store.permits.values():
        if p["site_id"] != site["id"] or p["status"] not in ("FILED", "UNDER_REVIEW"):
            continue
        if conservative:
            profile = store.municipalities.get(p["_profile_id"])
            observed = profile["observed_avg_review_days"] if profile else 0
            due = parse_date(p["filed_at"]) + timedelta(days=observed)
        else:
            due = parse_date(p["review_due_on"])
        days = max(days, max(0, (due - today).days))
    return days


def _vendor_chain_days(site, today, slip_bp, conservative):
    cursor = today
    mobs = [m for m in store.mobilizations.values() if m["site_id"] == site["id"]]
    for vtype in VENDOR_ORDER:
        typed = [m for m in mobs if m["vendor_type"] == vtype]
        if any(m["status"] == "COMPLETE" for m in typed):
            continue
        live = [m for m in typed if m["status"] in ("PLANNED", "SCHEDULED", "ON_SITE")]
        if not live:
            continue  # no scheduled work prices as zero days
        m = min(live, key=lambda x: (x["created_at"], x["_seq"]))
        start = parse_date(m["planned_start_on"])
        end = parse_date(m["planned_end_on"])
        if m["status"] == "ON_SITE":
            cursor = max(cursor, today)
            cursor = cursor + timedelta(days=max(0, (end - cursor).days))
        else:
            planned = (end - start).days
            if conservative:
                padded = Decimal(planned) * (
                    Decimal(10000 + slip_bp) / Decimal(10000))
                planned = int(padded.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            begin = max(cursor, start)
            cursor = begin + timedelta(days=planned)
    return (cursor - today).days


def compute_forecast(site):
    """Returns (forecast_open_on, forecast_optimistic_on, slip_days, posture).

    Caller guarantees site not in {OPEN, REMOVED}.
    """
    today = clock.today()
    committed = parse_date(site["target_open_date"])
    commitment = commitment_of_site(site)
    if commitment is not None:
        committed = parse_date(commitment["committed_open_on"])
    factor = slip_factor_bp(site)

    cons = (_permit_block_days(site, today, True)
            + _vendor_chain_days(site, today, factor, True)
            + PUNCH_BUFFER_DAYS)
    opt = (_permit_block_days(site, today, False)
           + _vendor_chain_days(site, today, 0, False)
           + PUNCH_BUFFER_DAYS)
    forecast_open = today + timedelta(days=cons)
    forecast_opt = today + timedelta(days=opt)
    slip = max(0, (forecast_open - committed).days)

    if today >= committed:
        posture = "BREACHED"
    elif slip == 0:
        posture = "PROTECTED"
    elif slip <= 7:
        posture = "WATCH"
    elif slip <= 21:
        posture = "AT_RISK"
    else:
        posture = "BREACHED"
    return forecast_open.isoformat(), forecast_opt.isoformat(), slip, posture


def commitment_of_site(site):
    for c in store.commitments.values():
        if c["site_id"] == site["id"]:
            return c
    return None


def recompute_commitment(commitment):
    """Recompute one commitment. Sites in OPEN pin posture MET; REMOVED sites
    are outside the forecast input set and are left untouched."""
    site = store.sites.get(commitment["site_id"])
    if site is None:
        return False
    if site["status"] == "OPEN":
        return apply_changes(commitment, {"protection_posture": "MET"})
    if site["status"] == "REMOVED":
        return False
    forecast_open, forecast_opt, slip, posture = compute_forecast(site)
    return apply_changes(commitment, {
        "forecast_open_on": forecast_open,
        "forecast_optimistic_on": forecast_opt,
        "slip_days": slip,
        "protection_posture": posture,
    })


def recompute_commitment_for_site(site):
    commitment = commitment_of_site(site)
    if commitment is not None:
        recompute_commitment(commitment)
