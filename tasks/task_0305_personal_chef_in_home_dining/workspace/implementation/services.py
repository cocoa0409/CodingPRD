"""Shared domain services: time parsing, chef aggregate recomputation, booking
quote recomputation, availability overlap checks. (PRD §2.6-§2.10, §3.4-§3.8)"""
from datetime import datetime, timezone, timedelta

import calculations as calc
from db import DB
from errors import err
from models import touch


# ---------------------------------------------------------------------------
# Datetime parsing
# ---------------------------------------------------------------------------
def parse_datetime(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.
    Returns None if unparseable."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def event_date_from_start(event_start_dt):
    """PRD §3.3: event_date = calendar date YYYY-MM-DD in UTC from event_start_utc."""
    return event_start_dt.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Availability / overlap (PRD §2.7)
# ---------------------------------------------------------------------------
def occupied_window(booking, chef):
    """A booking's occupied window: [event_start - prep_buffer, event_end)."""
    start = parse_datetime(booking["event_start_utc"])
    end = parse_datetime(booking["event_end_utc"])
    buffered_start = start - timedelta(minutes=chef["prep_buffer_minutes"])
    return buffered_start, end


def intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap: one starts strictly before the other ends
    and ends strictly after the other starts. Back-to-back does NOT overlap."""
    return a_start < b_end and a_end > b_start


def held_blocks_for_chef(chef_id, exclude_booking_id=None):
    """All HELD AvailabilityBlocks of the chef, optionally excluding the hold of one booking."""
    result = []
    for blk in DB.availability_blocks.values():
        if blk["chef_id"] != chef_id:
            continue
        if blk["status"] != "HELD":
            continue
        if exclude_booking_id is not None and blk.get("booking_id") == exclude_booking_id:
            continue
        result.append(blk)
    return result


def window_conflicts(chef_id, win_start, win_end, exclude_booking_id=None):
    """True if [win_start, win_end) overlaps any HELD block of the chef."""
    for blk in held_blocks_for_chef(chef_id, exclude_booking_id):
        b_start = parse_datetime(blk["window_start_utc"])
        b_end = parse_datetime(blk["window_end_utc"])
        if intervals_overlap(win_start, win_end, b_start, b_end):
            return True
    return False


# ---------------------------------------------------------------------------
# Travel zone resolution (PRD §3.3)
# ---------------------------------------------------------------------------
def resolve_travel_zone(chef_id, service_zip):
    """Prefix-match service_zip against the chef's zones. Must match exactly one.
    Returns the matched zone, or raises ERR_ZIP_OUTSIDE_SERVICE_AREA."""
    matches = []
    for zone in DB.travel_zones.values():
        if zone["chef_id"] != chef_id:
            continue
        for prefix in zone["zip_prefixes"]:
            if service_zip.startswith(prefix):
                matches.append(zone)
                break
    if len(matches) != 1:
        raise err("ERR_ZIP_OUTSIDE_SERVICE_AREA",
                  "service_zip does not prefix-match exactly one chef travel zone")
    return matches[0]


# ---------------------------------------------------------------------------
# Booking quote recomputation (PRD §3.4)
# ---------------------------------------------------------------------------
def has_finalized_grocery_run(booking_id):
    for gr in DB.grocery_runs.values():
        if gr["booking_id"] == booking_id and gr["status"] == "FINALIZED":
            return True
    return False


def recompute_quote(booking):
    """PRD §3.4 quote & balance. grocery_basis = actual if a FINALIZED run exists
    else estimated; quote = labor + grocery_basis + travel; balance = quote - captured.
    Selection precedes the sum. No version bump here — caller decides."""
    if has_finalized_grocery_run(booking["id"]):
        grocery_basis = booking["actual_grocery_total_cents"]
    else:
        grocery_basis = booking["estimated_grocery_total_cents"]
    booking["quote_total_cents"] = (
        booking["labor_total_cents"] + grocery_basis + booking["travel_fee_cents"]
    )
    booking["balance_due_cents"] = (
        booking["quote_total_cents"] - booking["amount_captured_cents"]
    )


def recompute_booking_money_mirrors(booking):
    """PRD §3.3/§3.6: amount_captured_cents / amount_refunded_cents from this
    booking's Payments. Then recompute quote/balance."""
    captured = 0
    refunded = 0
    for p in DB.payments.values():
        if p["booking_id"] != booking["id"]:
            continue
        if p["status"] in ("CAPTURED", "REFUNDED"):
            captured += p["amount_cents"]
        refunded += p["refunded_cents"]
    booking["amount_captured_cents"] = captured
    booking["amount_refunded_cents"] = refunded
    recompute_quote(booking)


# ---------------------------------------------------------------------------
# Chef aggregate recomputation (PRD §3.6, §3.7, §2.10)
# ---------------------------------------------------------------------------
def chef_bookings(chef_id):
    return [b for b in DB.bookings.values() if b["chef_id"] == chef_id]


def chef_payments(chef_id):
    """All Payments across this chef's bookings."""
    booking_ids = {b["id"] for b in DB.bookings.values() if b["chef_id"] == chef_id}
    return [p for p in DB.payments.values() if p["booking_id"] in booking_ids]


def _terminal_bookings_ordered(chef_id):
    """This chef's terminal bookings, chronological: event_start_utc ASC,
    tie-break created_at ASC (never id). (PRD §3.7)"""
    terminal = [b for b in chef_bookings(chef_id)
                if b["lifecycle_status"] in ("COMPLETED", "DECLINED", "CANCELLED")]
    terminal.sort(key=lambda b: (b["event_start_utc"], b["created_at"]))
    return terminal


def recompute_chef_money(chef):
    """PRD §3.6/§2.10 conserved money invariant."""
    pays = chef_payments(chef["id"])
    captured = sum(p["amount_cents"] for p in pays if p["status"] in ("CAPTURED", "REFUNDED"))
    refunded = sum(p["refunded_cents"] for p in pays)
    chef["captured_payments_cents"] = captured
    chef["refunded_payments_cents"] = refunded
    chef["payout_accrued_cents"] = captured - refunded


def recompute_chef_counts(chef):
    """active_booking_count = bookings in {CONFIRMED, IN_PREP};
    completed_bookings_count = bookings COMPLETED. (PRD §2.10, §3.1)"""
    bookings = chef_bookings(chef["id"])
    chef["active_booking_count"] = sum(
        1 for b in bookings if b["lifecycle_status"] in ("CONFIRMED", "IN_PREP")
    )
    chef["completed_bookings_count"] = sum(
        1 for b in bookings if b["lifecycle_status"] == "COMPLETED"
    )


def recompute_chef_scores(chef):
    """PRD §3.7 settled + projected reliability scores."""
    terminal = _terminal_bookings_ordered(chef["id"])
    active_count = sum(
        1 for b in chef_bookings(chef["id"]) if b["lifecycle_status"] in ("CONFIRMED", "IN_PREP")
    )
    chef["settled_reliability_score"] = calc.settled_reliability_score(terminal)
    chef["projected_reliability_score"] = calc.projected_reliability_score(terminal, active_count)


def recompute_chef_all(chef):
    """Recompute every chef-level computed field, then record the mutation."""
    recompute_chef_money(chef)
    recompute_chef_counts(chef)
    recompute_chef_scores(chef)
    touch(chef)


# ---------------------------------------------------------------------------
# Lead time (PRD §3.8)
# ---------------------------------------------------------------------------
def lead_days(event_start_dt):
    """Whole days from current clock to event_start: floor((event_start - now)/86400s)."""
    now = DB.now()
    delta_seconds = (event_start_dt - now).total_seconds()
    import math
    return math.floor(delta_seconds / 86400.0)
