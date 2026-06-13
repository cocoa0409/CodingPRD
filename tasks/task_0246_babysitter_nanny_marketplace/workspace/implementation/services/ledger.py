"""Ledger conservation + derived-field reconciliation helpers.

Family escrow:  escrow_reserved_cents + escrow_available_cents == wallet_balance_cents
Family tax:     cash_wages_ytd_cents, tax_withheld_ytd_cents, is_w2_obligated
Caregiver:      pending_earnings_cents, lifetime_paid_cents, rating_avg, rating_count
"""

from decimal import Decimal, ROUND_HALF_UP

from db import store
from services.calc import FICA_ANNUAL_WAGE_THRESHOLD_CENTS


def recompute_escrow_available(family):
    """escrow_available = wallet_balance - escrow_reserved (never negative)."""
    avail = family["wallet_balance_cents"] - family["escrow_reserved_cents"]
    family["escrow_available_cents"] = avail if avail > 0 else 0


def tax_year_of(iso_ts):
    """Return the calendar year (int) of an ISO timestamp string."""
    # format: YYYY-MM-DDTHH:MM:SS.mmmZ
    return int(iso_ts[:4])


def recompute_w2_obligation(family):
    """is_w2_obligated true iff any single caregiver's grouped COMPLETED-session
    gross wages (this family, that caregiver, that tax year) is strictly greater
    than the federal threshold (§3.9). Strictly greater-than.

    Grouping uses COMPLETED sessions whose gross has been counted toward
    cash_wages, decremented by reversed payouts. We recompute from authoritative
    session + payout state so it is exact under reversals.
    """
    # group[(caregiver_id, tax_year)] = gross wages
    groups = {}
    fam_id = family["id"]
    # Map session_id -> whether its gross is currently "live" (not reversed out).
    # cash_wages accrues on clock-out and is decremented on payout reversal of
    # the gross. We mirror that exact accounting here by computing from sessions
    # minus reversed payout grosses per (caregiver, year).
    for s in store.sessions.values():
        if s["status"] != "COMPLETED":
            continue
        bk = store.bookings.get(s["booking_id"])
        if not bk or bk["family_id"] != fam_id:
            continue
        cg = s["caregiver_id"]
        yr = tax_year_of(s["window_start_iso"])
        groups[(cg, yr)] = groups.get((cg, yr), 0) + s["gross_pay_cents"]

    # Subtract gross of REVERSED payouts (compensation already applied to
    # cash_wages_ytd at reverse time; mirror it in the obligation grouping).
    for p in store.payouts.values():
        if p["family_id"] != fam_id or p["status"] != "REVERSED":
            continue
        cg = p["caregiver_id"]
        for sid in p["session_ids"]:
            s = store.sessions.get(sid)
            if not s:
                continue
            yr = tax_year_of(s["window_start_iso"])
            if (cg, yr) in groups:
                groups[(cg, yr)] -= s["gross_pay_cents"]

    obligated = any(total > FICA_ANNUAL_WAGE_THRESHOLD_CENTS for total in groups.values())
    family["is_w2_obligated"] = obligated


def recompute_caregiver_rating(caregiver):
    """rating_avg = mean of rating_value over PUBLISHED reviews (2dp, 0 when none);
    rating_count = count of those PUBLISHED reviews (§3.10)."""
    cg_id = caregiver["id"]
    values = [
        r["rating_value"]
        for r in store.reviews.values()
        if r["caregiver_id"] == cg_id and r["status"] == "PUBLISHED"
    ]
    count = len(values)
    if count == 0:
        caregiver["rating_avg"] = 0.0
        caregiver["rating_count"] = 0
        return
    avg = Decimal(sum(values)) / Decimal(count)
    avg = avg.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    caregiver["rating_avg"] = float(avg)
    caregiver["rating_count"] = count
