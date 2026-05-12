"""Reservation lifecycle, space selector, and reservation_charge calculation."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
import math

import db
from clock import now, parse_iso, iso
from errors import err
from services.payment import create_payment
from services.revenue import create_revenue_entry, round_half_up_to_int
from services.zones import recompute_zone_counts


MATCH_DISCOUNT_BPS = Decimal("1000")  # 10%


def intervals_overlap(a_start, a_end, b_start, b_end) -> bool:
    """Half-open interval overlap [a_start, a_end) vs [b_start, b_end)."""
    return a_start < b_end and b_start < a_end


def select_space(lot: dict, zone_id: str, scheduled_start_at, scheduled_end_at, *,
                 exclude_reservation_id=None):
    """Run the space selector for a reservation request.

    Returns the chosen Space dict or raises an error.
    """
    candidates = []
    tow_grace = int(lot.get("tow_grace_minutes", 5))
    for s in db.spaces.values():
        if s.get("zone_id") != zone_id:
            continue
        # Eligibility
        ok_free = s.get("occupancy_status") == "FREE"
        in_grace = False
        last_exit = s.get("last_exited_at")
        if last_exit is not None:
            try:
                le = parse_iso(last_exit)
                if scheduled_start_at < le + timedelta(minutes=tow_grace):
                    in_grace = True
            except Exception:
                pass
        if not ok_free:
            # Per scaffold: candidate if scheduled_start_at >= last_exited_at + tow_grace
            # but only when the space is FREE; OCCUPIED spaces cannot be reserved.
            continue
        if last_exit is not None and in_grace:
            # Space is in tow-grace buffer → not bookable
            continue
        # No overlap with existing HELD or MATCHED
        has_overlap = False
        for r in db.reservations.values():
            if exclude_reservation_id and r["id"] == exclude_reservation_id:
                continue
            if r.get("space_id") != s["id"]:
                continue
            if r.get("status") not in ("HELD", "MATCHED"):
                continue
            try:
                rs = parse_iso(r["scheduled_start_at"])
                re_ = parse_iso(r["scheduled_end_at"])
            except Exception:
                continue
            if intervals_overlap(scheduled_start_at, scheduled_end_at, rs, re_):
                has_overlap = True
                break
        if has_overlap:
            continue
        candidates.append(s)

    if not candidates:
        raise err("ERR_NO_SPACE_AVAILABLE", "No bookable space in the requested window")

    # Sort: lex-smallest label, tie-break by id ascending
    candidates.sort(key=lambda s: (s.get("label") or "", s.get("id") or ""))
    return candidates[0]


def check_space_bookable_for_create(lot: dict, zone_id: str, scheduled_start_at, scheduled_end_at):
    """Pre-checks: ERR_RESERVATION_OVERLAP / ERR_SPACE_NOT_BOOKABLE per priorities 9, 10.

    These need to apply BEFORE the selector picks a candidate, but the selector
    skips overlapping/grace spaces. To surface the right error, we first check
    if any space in the zone is overlap-blocked vs grace-blocked vs simply none.
    """
    # If we got here from the selector raising NO_SPACE_AVAILABLE we use a
    # secondary classification — implemented inline in the route via try/catch.
    # Helper kept for future use.
    pass


def cancel_window_penalty_cents(lot: dict) -> int:
    """Half the no_show_penalty rounded HALF_UP."""
    base = int(lot.get("no_show_penalty_cents", 0))
    return round_half_up_to_int(Decimal(base) / Decimal(2))


def expire_no_show_reservations() -> int:
    """For each HELD reservation past scheduled_start_at + reservation_hold_minutes,
    transition to EXPIRED_NO_SHOW with side effects. Returns count.
    """
    n = 0
    for r in list(db.reservations.values()):
        if r.get("status") != "HELD":
            continue
        if r.get("matched_session_id"):
            continue
        lot = db.parking_lots.get(r.get("lot_id"))
        if lot is None:
            continue
        try:
            sched = parse_iso(r["scheduled_start_at"])
        except Exception:
            continue
        hold = int(lot.get("reservation_hold_minutes", 15))
        if now() < sched + timedelta(minutes=hold):
            continue
        _transition_to_expired_no_show(r, lot)
        n += 1
    return n


def _transition_to_expired_no_show(r: dict, lot: dict):
    """Apply EXPIRED_NO_SHOW transition + side effects."""
    r["status"] = "EXPIRED_NO_SHOW"
    penalty = int(lot.get("no_show_penalty_cents", 0))
    r["penalty_charged_cents"] = penalty
    db.stamp_update(r)
    # Free the space's reservation_lock if it was holding
    if r.get("space_id"):
        space = db.spaces.get(r["space_id"])
        if space and space.get("reservation_lock") == "RESERVED":
            space["reservation_lock"] = "UNRESERVED"
            db.stamp_update(space)
            recompute_zone_counts(space["zone_id"])
    # Penalty payment + revenue entry
    if penalty > 0:
        card_id = r.get("card_id")
        if card_id:
            try:
                create_payment(
                    kind="NO_SHOW_PENALTY",
                    subject_id=r["id"],
                    amount_cents=penalty,
                    card_id=card_id,
                )
            except Exception:
                pass  # Even if duplicate-ref or insufficient — don't crash sweep.
        else:
            create_payment(
                kind="NO_SHOW_PENALTY",
                subject_id=r["id"],
                amount_cents=penalty,
                card_id=None,
            )
        zone_id = None
        if r.get("space_id"):
            sp = db.spaces.get(r["space_id"])
            zone_id = sp.get("zone_id") if sp else r.get("zone_id")
        else:
            zone_id = r.get("zone_id")
        create_revenue_entry(
            lot_id=lot["id"],
            zone_id=zone_id,
            billing_type="NO_SHOW_PENALTY",
            source_kind="RESERVATION",
            source_id=r["id"],
            gross_amount_cents=penalty,
        )


def reservation_match_credit(r: dict, lot: dict) -> int:
    """Compute the discount magnitude for a MATCHED reservation."""
    try:
        s = parse_iso(r["scheduled_start_at"])
        e = parse_iso(r["scheduled_end_at"])
    except Exception:
        return 0
    sec = (e - s).total_seconds()
    hours = math.ceil(max(sec, 0) / 3600)
    hourly = int(lot.get("hourly_rate_cents", 0))
    daily = int(lot.get("daily_cap_cents", 0))
    reference = min(hours * hourly, daily)
    discount = round_half_up_to_int(Decimal(reference) * MATCH_DISCOUNT_BPS / Decimal("10000"))
    return discount
