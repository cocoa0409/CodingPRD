"""Session billing calculation per PRD §3.5 and SCAFFOLD calculations.session_billing.

Implements provisional and final variants of the tiered hourly tally with
free-period grace and per-calendar-day daily cap.
"""
from datetime import datetime, timedelta, timezone
import math

import pytz

import db
from clock import now, parse_iso


def get_lot_tz(lot: dict):
    try:
        return pytz.timezone(lot.get("timezone") or "UTC")
    except pytz.UnknownTimeZoneError:
        return pytz.UTC


def settlement_day_key(lot: dict, dt: datetime = None) -> str:
    """Return YYYY-MM-DD in lot timezone for the given UTC datetime (default: now())."""
    if dt is None:
        dt = now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    tz = get_lot_tz(lot)
    local = dt.astimezone(tz)
    return local.strftime("%Y-%m-%d")


def _day_segments(entry_at: datetime, exit_clock: datetime, tz):
    """Yield (day_index, day_start_utc, day_end_utc) for each calendar day spanned.

    Day boundaries are defined in the lot's local timezone.
    day_index 0 = day containing entry_at.
    """
    # Convert to local
    local_entry = entry_at.astimezone(tz)
    local_exit = exit_clock.astimezone(tz)
    # Start at midnight of entry day
    cur_local_day = local_entry.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local_day = local_exit.replace(hour=0, minute=0, second=0, microsecond=0)
    idx = 0
    while cur_local_day <= end_local_day:
        # day_start_utc / day_end_utc
        next_day_local = cur_local_day + timedelta(days=1)
        # Use localize to handle DST correctly when constructing tz-aware datetimes.
        # cur_local_day already has tzinfo from astimezone above.
        day_start_utc = cur_local_day.astimezone(timezone.utc)
        day_end_utc = next_day_local.astimezone(timezone.utc)
        yield idx, day_start_utc, day_end_utc
        cur_local_day = next_day_local
        idx += 1


def compute_session_fee(session: dict, *, variant: str = "final"):
    """Compute (fee_cents, billing_kind) for a session.

    variant: 'final' uses Session.exit_at; 'provisional' uses now().
    """
    vehicle = db.vehicles.get(session["vehicle_id"])
    if vehicle is None:
        return 0, "EXEMPT_VEHICLE"
    # Pre-classification: exempt vehicles
    if vehicle.get("kind") in ("EMERGENCY", "DISABLED"):
        return 0, "EXEMPT_VEHICLE"
    # Pre-classification: monthly card coverage
    card_id = session.get("card_id")
    if card_id:
        card = db.cards.get(card_id)
        if card is not None and card.get("card_type") == "MONTHLY" and card.get("status") == "ACTIVE":
            entry_at = parse_iso(session["entry_at"])
            try:
                vfrom = parse_iso(card["valid_from"])
                vuntil = parse_iso(card["valid_until"])
            except Exception:
                vfrom = vuntil = None
            if vfrom is not None and vuntil is not None:
                if (session["vehicle_id"] in card.get("bound_vehicle_ids", [])
                        and vfrom <= entry_at <= vuntil):
                    return 0, "MONTHLY_COVERED"
    # Hourly path
    lot = db.parking_lots.get(session["lot_id"])
    if lot is None:
        return 0, "HOURLY"
    entry_at = parse_iso(session["entry_at"])
    if variant == "final":
        if not session.get("exit_at"):
            # Should not happen — fall back to now
            exit_clock = now()
        else:
            exit_clock = parse_iso(session["exit_at"])
    else:
        exit_clock = now()

    # Free period check (entire-session test)
    free_seconds = int(lot.get("free_minutes", 15)) * 60
    duration_seconds = (exit_clock - entry_at).total_seconds()
    if duration_seconds <= free_seconds:
        return 0, "HOURLY"

    tz = get_lot_tz(lot)
    hourly_rate = int(lot.get("hourly_rate_cents", 0))
    daily_cap = int(lot.get("daily_cap_cents", 0))

    total = 0
    for idx, day_start_utc, day_end_utc in _day_segments(entry_at, exit_clock, tz):
        seg_start = max(day_start_utc, entry_at)
        seg_end = min(day_end_utc, exit_clock)
        seg_seconds = (seg_end - seg_start).total_seconds()
        if seg_seconds <= 0:
            continue
        billable_seconds = seg_seconds - (free_seconds if idx == 0 else 0)
        if billable_seconds < 0:
            billable_seconds = 0
        if billable_seconds == 0:
            continue
        started_hours = math.ceil(billable_seconds / 3600)
        raw_cost = started_hours * hourly_rate
        capped = min(raw_cost, daily_cap)
        total += capped
    return total, "HOURLY"
