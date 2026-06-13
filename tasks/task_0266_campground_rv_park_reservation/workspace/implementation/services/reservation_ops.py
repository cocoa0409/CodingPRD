"""Reservation & site business operations: locking, state transitions, cascades.

Implements PRD §3.3 (site lifecycle + retire cascade), §3.5 (reservation
lifecycle), §3.6 (pricing recompute), §3.7 (checkout reconciliation), §3.8
(cancellation refund tiers).
"""
from datetime import timedelta

from db import store, new_id, now_iso_ms
import errors
from services.common import parse_date, clock_date, touch, stamp_common
from services import pricing
from services.serializers import ACTIVE_RES_STATUSES


# ---------------------------------------------------------------------------
# Date / overlap geometry
# ---------------------------------------------------------------------------
def _half_open_overlap(a_start, a_end, b_start, b_end):
    """True when half-open intervals [a_start,a_end) and [b_start,b_end) overlap.

    Back-to-back (a_end == b_start) does NOT overlap (PRD §3.5).
    """
    return a_start < b_end and b_start < a_end


def check_date_overlap(site_id, check_in, check_out, exclude_reservation_id=None):
    """Raise ERR_DATE_OVERLAP if [check_in, check_out) overlaps a live reservation."""
    for r in store.reservations.values():
        if r["site_id"] != site_id:
            continue
        if exclude_reservation_id is not None and r["id"] == exclude_reservation_id:
            continue
        if r["reservation_status"] not in ACTIVE_RES_STATUSES:
            continue
        r_in = parse_date(r["check_in_date"])
        r_out = parse_date(r["check_out_date"])
        if _half_open_overlap(check_in, check_out, r_in, r_out):
            raise errors.err(
                errors.ERR_DATE_OVERLAP,
                "Reservation window overlaps another live reservation",
            )


def check_maintenance_conflict(site, check_in, check_out):
    """Raise ERR_MAINTENANCE_CONFLICT on overlap with a buffered ACTIVE hold window.

    Buffered window is the CLOSED interval [start - buffer, end + buffer]; the
    requested interval is half-open [check_in, check_out). The reservation
    interval overlaps the closed buffered window when check_in <= buffered_end
    and check_out > buffered_start.
    """
    buffer = site["turnover_buffer_days"]
    for h in store.maintenance_holds.values():
        if h["site_id"] != site["id"] or h["status"] != "ACTIVE":
            continue
        h_start = parse_date(h["start_date"]) - timedelta(days=buffer)
        h_end = parse_date(h["end_date"]) + timedelta(days=buffer)
        # closed buffered window [h_start, h_end] vs half-open [check_in, check_out)
        if check_in <= h_end and check_out > h_start:
            raise errors.err(
                errors.ERR_MAINTENANCE_CONFLICT,
                "Reservation window collides with an active maintenance hold",
            )


# ---------------------------------------------------------------------------
# Reservation creation (lock)
# ---------------------------------------------------------------------------
def create_reservation(site, guest, check_in_date_str, check_out_date_str):
    """Build a REQUESTED/UNPAID reservation with provisional pricing.

    Assumes max-stay, availability, maintenance-buffer, and date-overlap guards
    have already been enforced by the caller (priority order, PRD §3.5).
    """
    park = store.parks[site["park_id"]]
    rate_plan = store.rate_plans[site["rate_plan_id"]]

    check_in = parse_date(check_in_date_str)
    check_out = parse_date(check_out_date_str)
    nights = (check_out - check_in).days

    threshold = park["long_stay_nights_threshold"]
    stay_class = "LONG_TERM" if nights >= threshold else "SHORT_TERM"

    rid = new_id()
    res = {
        "id": rid,
        "site_id": site["id"],
        "guest_id": guest["id"],
        "check_in_date": check_in_date_str,
        "check_out_date": check_out_date_str,
        "nights": nights,
        "actual_check_out_date": None,
        "stay_class": stay_class,
        "reservation_status": "REQUESTED",
        "payment_status": "UNPAID",
        "discount_cents": 0,
        "priced_nights": nights,
    }
    stamp_common(res)

    # Provisional pricing over the full requested nights, discount = 0.
    totals = pricing.compute_totals(
        res, park, site, rate_plan, nights, discount_cents=0
    )
    res["stay_charge_cents"] = totals["stay_charge_cents"]
    res["season_surcharge_cents"] = totals["season_surcharge_cents"]
    res["addon_total_cents"] = totals["addon_total_cents"]
    res["tax_cents"] = totals["tax_cents"]
    res["total_due_cents"] = totals["total_due_cents"]
    res["deposit_due_cents"] = pricing.deposit_due(totals["total_due_cents"], park)

    store.reservations[rid] = res

    # booked_night_count is computed on read; locking the site still bumps the
    # site's version (PRD §3.5).
    touch(site)
    return res


def recompute_provisional(res):
    """Recompute pricing for a non-checked-out reservation (PRD §3.6).

    Uses the requested night count, the discount currently frozen on the
    reservation (0 before confirm), and recomputes total/deposit.
    """
    site = store.sites[res["site_id"]]
    park = store.parks[site["park_id"]]
    rate_plan = store.rate_plans[site["rate_plan_id"]]
    n = res["nights"]
    totals = pricing.compute_totals(
        res, park, site, rate_plan, n, discount_cents=res["discount_cents"]
    )
    res["stay_charge_cents"] = totals["stay_charge_cents"]
    res["season_surcharge_cents"] = totals["season_surcharge_cents"]
    res["addon_total_cents"] = totals["addon_total_cents"]
    res["tax_cents"] = totals["tax_cents"]
    res["total_due_cents"] = totals["total_due_cents"]


# ---------------------------------------------------------------------------
# Confirm
# ---------------------------------------------------------------------------
def confirm_reservation(res):
    site = store.sites[res["site_id"]]
    park = store.parks[site["park_id"]]
    rate_plan = store.rate_plans[site["rate_plan_id"]]
    guest = store.guests[res["guest_id"]]

    n = res["nights"]
    # Pre-discount subtotal at the requested nights, then freeze discount.
    base = pricing.compute_totals(res, park, site, rate_plan, n, discount_cents=0)
    discount = pricing.compute_discount_at_confirm(base["pre_discount_subtotal"], guest)
    res["discount_cents"] = discount

    totals = pricing.compute_totals(res, park, site, rate_plan, n, discount_cents=discount)
    res["stay_charge_cents"] = totals["stay_charge_cents"]
    res["season_surcharge_cents"] = totals["season_surcharge_cents"]
    res["addon_total_cents"] = totals["addon_total_cents"]
    res["tax_cents"] = totals["tax_cents"]
    res["total_due_cents"] = totals["total_due_cents"]
    res["deposit_due_cents"] = pricing.deposit_due(totals["total_due_cents"], park)

    res["reservation_status"] = "CONFIRMED"
    touch(res)
    touch(site)


# ---------------------------------------------------------------------------
# Check-in
# ---------------------------------------------------------------------------
def check_in_reservation(res):
    res["reservation_status"] = "CHECKED_IN"
    touch(res)


# ---------------------------------------------------------------------------
# Check-out reconciliation (PRD §3.7)
# ---------------------------------------------------------------------------
def check_out_reservation(res):
    site = store.sites[res["site_id"]]
    park = store.parks[site["park_id"]]
    rate_plan = store.rate_plans[site["rate_plan_id"]]
    guest = store.guests[res["guest_id"]]

    check_in = parse_date(res["check_in_date"])
    booked_out = parse_date(res["check_out_date"])
    today = clock_date()
    actual_out = min(booked_out, today)
    if actual_out < check_in:
        actual_out = check_in
    res["actual_check_out_date"] = actual_out.isoformat()

    actual_nights = (actual_out - check_in).days
    priced_nights = max(1, actual_nights)
    res["priced_nights"] = priced_nights

    deposit_floor = res["deposit_due_cents"]
    totals = pricing.compute_totals(
        res, park, site, rate_plan, priced_nights, discount_cents=res["discount_cents"]
    )
    res["stay_charge_cents"] = totals["stay_charge_cents"]
    res["season_surcharge_cents"] = totals["season_surcharge_cents"]
    res["addon_total_cents"] = totals["addon_total_cents"]
    res["tax_cents"] = totals["tax_cents"]
    # Final total floored at deposit_due_cents (deposit never refunded on early
    # departure) — PRD §3.7.
    final_total = max(totals["total_due_cents"], deposit_floor)
    res["total_due_cents"] = final_total

    res["reservation_status"] = "CHECKED_OUT"

    # Auto BALANCE payment if money still owed; then PAID_IN_FULL.
    from services.serializers import compute_amount_paid

    amount_paid = compute_amount_paid(res["id"])
    balance = final_total - amount_paid
    if balance > 0:
        _append_payment(res["id"], "BALANCE", balance, reason=None)
        res["payment_status"] = "PAID_IN_FULL"

    touch(res)
    # Guest lifetime figures are computed on read; bump guest record (cascade).
    touch(guest)
    # Site booked_night_count computed on read; bump site version.
    touch(site)


# ---------------------------------------------------------------------------
# Cancel (PRD §3.8) — also reused as the site-retire compensation step
# ---------------------------------------------------------------------------
def cancel_reservation(res, reason=None):
    site = store.sites[res["site_id"]]

    res["reservation_status"] = "CANCELLED"

    # Money leg: compute refund per cancellation tier.
    refund = compute_cancellation_refund(res)
    if refund > 0:
        _append_payment(res["id"], "REFUND", refund, reason=reason or "CANCELLATION_REFUND")
        res["payment_status"] = "REFUNDED"

    touch(res)
    # booked nights released (computed on read); bump site version.
    touch(site)


def compute_cancellation_refund(res):
    """Tiered refund on days_before check-in (PRD §3.8)."""
    if res["stay_class"] == "LONG_TERM":
        return 0
    from services.serializers import compute_amount_paid

    amount_paid = compute_amount_paid(res["id"])
    if amount_paid <= 0:
        return 0

    check_in = parse_date(res["check_in_date"])
    today = clock_date()
    days_before = (check_in - today).days

    park = store.parks[store.sites[res["site_id"]]["park_id"]]
    policy = _policy_for_park(park["id"])
    if policy is None:
        # No policy configured: nothing to refund (cannot evaluate tiers).
        return 0

    from services.common import round_half_up

    if days_before >= policy["full_refund_min_days"]:
        return amount_paid
    if days_before >= policy["half_refund_min_days"]:
        return round_half_up(amount_paid * 0.50)
    return 0


def _policy_for_park(park_id):
    """Most-recently-created cancellation policy for the park (by created_at)."""
    policies = [
        c for c in store.cancellation_policies.values() if c["park_id"] == park_id
    ]
    if not policies:
        return None
    policies.sort(key=lambda c: (c["created_at"], c.get("_seq", 0)))
    return policies[-1]


# ---------------------------------------------------------------------------
# Site retire cascade (PRD §3.3)
# ---------------------------------------------------------------------------
def retire_site(site):
    site["status"] = "RETIRED"

    # CASCADE L1: live reservations -> CANCELLED, in ascending created_at order.
    live = [
        r
        for r in store.reservations.values()
        if r["site_id"] == site["id"]
        and r["reservation_status"] in ACTIVE_RES_STATUSES
    ]
    live.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))

    affected_guests = set()
    for res in live:
        res["reservation_status"] = "CANCELLED"
        affected_guests.add(res["guest_id"])
        # CASCADE L2: full refund of amount_paid_cents if positive.
        from services.serializers import compute_amount_paid

        amount_paid = compute_amount_paid(res["id"])
        if amount_paid > 0:
            _append_payment(res["id"], "REFUND", amount_paid, reason="SITE_RETIRED")
            res["payment_status"] = "REFUNDED"
        touch(res)

    # CASCADE L3: recompute affected guests (figures unchanged, but recompute
    # fires -> their records are touched).
    for gid in affected_guests:
        g = store.guests.get(gid)
        if g is not None:
            touch(g)

    # booked_night_count recomputed to 0 (computed on read); bump site version.
    touch(site)


# ---------------------------------------------------------------------------
# Payment ledger append
# ---------------------------------------------------------------------------
def _append_payment(reservation_id, ptype, amount_cents, reason=None):
    pid = new_id()
    payment = {
        "id": pid,
        "reservation_id": reservation_id,
        "type": ptype,
        "amount_cents": amount_cents,
        "reason": reason,
        "created_at": now_iso_ms(),
        "_seq": store.next_seq(),
    }
    store.payments[pid] = payment
    return payment
