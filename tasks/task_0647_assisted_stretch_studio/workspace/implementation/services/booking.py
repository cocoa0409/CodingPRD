"""Booking creation gauntlet, overlap checks, transitions, fees, cascades.

Implements PRD §3.3, §3.4, §3.5 and scaffold Booking state machines + validations.
"""
from datetime import timedelta

from db import store
from errors import (
    err, ERR_NOT_FOUND, ERR_LOCATION_MISMATCH, ERR_INVALID_STATE,
    ERR_MEMBER_SUSPENDED, ERR_INTRO_REQUIRED, ERR_OUTSIDE_BUSINESS_HOURS,
    ERR_TABLE_UNAVAILABLE, ERR_FLEXOLOGIST_UNAVAILABLE,
    ERR_FLEXOLOGIST_NOT_CERTIFIED, ERR_INSUFFICIENT_CREDITS, ERR_LOCATION_CLOSED,
)
from util import now_clock, parse_iso, minute_of_day
from services.common import make_full, bump
from services.calc import no_show_fee_late_cancel
from services.wallet import wallet_available, reconcile_creditpack_status
from services.strikes import create_no_show_event

# A booking still occupies its resources while it is non-terminal.
NON_TERMINAL_SCHEDULE = {"REQUESTED", "CONFIRMED"}


def _resolve_wallet(funding_source, funding_id):
    """Return the wallet record for the polymorphic funding pointer, or None."""
    if funding_source == "MEMBERSHIP":
        return store.memberships.get(funding_id)
    if funding_source == "CREDIT_PACK":
        return store.credit_packs.get(funding_id)
    return None


def _overlapping_table_bookings(table_id, start, end, exclude_id=None):
    """Half-open [start,end) overlap on the same table; adjacency allowed."""
    for b in store.bookings.values():
        if b["id"] == exclude_id:
            continue
        if b["table_id"] != table_id:
            continue
        if b["schedule_status"] not in NON_TERMINAL_SCHEDULE:
            continue
        b_start = parse_iso(b["session_start_utc"])
        b_end = parse_iso(b["session_end_utc"])
        # overlap iff start < b_end AND b_start < end (half-open).
        if start < b_end and b_start < end:
            return True
    return False


def _flexologist_conflict(flexologist_id, start, end, buffer_minutes, exclude_id=None):
    """Conflict iff gap between consecutive sessions < buffer (PRD §3.3).

    A new session conflicts when its start is strictly earlier than a prior
    session's end + buffer, OR symmetrically when an existing session's start
    is strictly earlier than this new session's end + buffer.
    """
    buf = timedelta(minutes=buffer_minutes)
    for b in store.bookings.values():
        if b["id"] == exclude_id:
            continue
        if b["flexologist_id"] != flexologist_id:
            continue
        if b["schedule_status"] not in NON_TERMINAL_SCHEDULE:
            continue
        b_start = parse_iso(b["session_start_utc"])
        b_end = parse_iso(b["session_end_utc"])
        # require gap >= buffer on both sides.
        if start < b_end + buf and b_start < end + buf:
            return True
    return False


def validate_booking_slot(member, location, service, flexologist, table,
                          funding_source, wallet, start, end,
                          exclude_booking_id=None):
    """Runs the temporal/resource/credit gauntlet (priorities 9-13).

    Caller has already done auth/forbidden/not-found/location-mismatch/
    suspended/intro/state checks in the correct priority order.
    """
    clock = now_clock()

    # priority 9: temporal feasibility + catalog item bookable state & location.
    if not (start > clock):
        raise err(ERR_OUTSIDE_BUSINESS_HOURS, "session_start_utc must be in the future.")
    start_mod = minute_of_day(start)
    if not (location["open_minute_of_day"] <= start_mod < location["close_minute_of_day"]):
        raise err(ERR_OUTSIDE_BUSINESS_HOURS, "session_start_utc outside business hours.")
    if service["status"] != "ACTIVE":
        raise err(ERR_OUTSIDE_BUSINESS_HOURS, "Service is not bookable.")
    if flexologist["status"] != "ACTIVE":
        raise err(ERR_OUTSIDE_BUSINESS_HOURS, "Flexologist is not bookable.")
    if table["status"] != "ACTIVE":
        raise err(ERR_OUTSIDE_BUSINESS_HOURS, "Table is not bookable.")

    # priority 10: table overlap.
    if _overlapping_table_bookings(table["id"], start, end, exclude_booking_id):
        raise err(ERR_TABLE_UNAVAILABLE, "Table already booked for an overlapping interval.")

    # priority 11: flexologist overlap with buffer.
    if _flexologist_conflict(flexologist["id"], start, end,
                             location["flexologist_buffer_minutes"], exclude_booking_id):
        raise err(ERR_FLEXOLOGIST_UNAVAILABLE, "Flexologist unavailable within buffer window.")

    # priority 12: INTRO requires certified flexologist.
    if service["kind"] == "INTRO" and not flexologist.get("certified_intro", False):
        raise err(ERR_FLEXOLOGIST_NOT_CERTIFIED, "Flexologist is not certified for intro sessions.")

    # priority 13: credit check (wallet available + pack expiry).
    if funding_source == "CREDIT_PACK":
        if wallet["status"] == "EXPIRED":
            raise err(ERR_INSUFFICIENT_CREDITS, "Credit pack is expired.")
        if start >= parse_iso(wallet["expires_utc"]):
            raise err(ERR_INSUFFICIENT_CREDITS, "session_start_utc at/after credit pack expiry.")
    available = wallet_available(funding_source, wallet)
    if available < service["credit_cost"]:
        raise err(ERR_INSUFFICIENT_CREDITS, "Funding wallet has insufficient available credits.")


def build_booking(member, location, service, flexologist, table, funding_source,
                  wallet, start, series_id=None, rescheduled_from_booking_id=None):
    """Create a HELD/REQUESTED booking with snapshots (PRD §3.3). No validation here."""
    end = start + timedelta(minutes=service["duration_minutes"])
    rec = make_full({
        "member_id": member["id"],
        "location_id": location["id"],
        "service_id": service["id"],
        "flexologist_id": flexologist["id"],
        "table_id": table["id"],
        "series_id": series_id,
        "rescheduled_from_booking_id": rescheduled_from_booking_id,
        "session_start_utc": _iso(start),
        "session_end_utc": _iso(end),
        "funding_source": funding_source,
        "funding_id": wallet["id"],
        "credit_cost": service["credit_cost"],
        "list_price_cents": service["list_price_cents"],
        "schedule_status": "REQUESTED",
        "credit_status": "HELD",
        "fee_charged_cents": 0,
        "is_intro": service["kind"] == "INTRO",
    })
    store.bookings[rec["id"]] = rec
    # Hold is reflected by credit_status==HELD; reconcile pack depletion status.
    if funding_source == "CREDIT_PACK":
        reconcile_creditpack_status(wallet)
    return rec


def _iso(dt):
    # Normalize to ...Z form (3 fractional digits if present, else no fraction).
    s = dt.astimezone(dt.tzinfo).isoformat()
    if s.endswith("+00:00"):
        s = s[:-6] + "Z"
    return s


# ---------------------------------------------------------------------------
# Cascade helpers
# ---------------------------------------------------------------------------
def void_addons(booking_id):
    for a in store.add_ons.values():
        if a["booking_id"] == booking_id and not a["voided"]:
            a["voided"] = True


def release_credit(booking):
    """credit_status HELD -> RELEASED (credits returned to available)."""
    booking["credit_status"] = "RELEASED"
    _reconcile_funding(booking)


def forfeit_credit(booking):
    """credit_status HELD -> FORFEITED (lost, counted as consumed-side)."""
    booking["credit_status"] = "FORFEITED"
    _reconcile_funding(booking)


def consume_credit(booking):
    """credit_status HELD -> CONSUMED."""
    booking["credit_status"] = "CONSUMED"
    _reconcile_funding(booking)


def _reconcile_funding(booking):
    if booking["funding_source"] == "CREDIT_PACK":
        pack = store.credit_packs.get(booking["funding_id"])
        if pack is not None:
            reconcile_creditpack_status(pack)


def cascade_cancel_release(booking):
    """Free-cancel a booking via cascade: CANCELLED + RELEASED + addons voided."""
    booking["schedule_status"] = "CANCELLED"
    release_credit(booking)
    void_addons(booking["id"])
    booking["fee_charged_cents"] = 0
    bump(booking)
