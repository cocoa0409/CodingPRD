"""Cleaning-window derivation and work sizing (PRD 3.3, 2.6)."""

from datetime import timedelta

from db import db
from services.money import ceil_int, dec

SIZE_BASE_MINUTES = {"STUDIO": 90, "ONE_BR": 120, "TWO_BR": 150, "THREE_BR_PLUS": 200}
MINUTES_PER_BATHROOM = 12
MINUTES_PER_BED = 8
PET_CLEAN_MULTIPLIER = dec("1.20")
INSPECTION_BUFFER_MINUTES = 30
VACANT_WINDOW_HOURS = 48
TIGHT_SLACK_MINUTES = 45
MAX_LATE_CHECKOUT_MINUTES = 240
SAME_ZONE_BUFFER_MINUTES = 15
CROSS_ZONE_BUFFER_MINUTES = 45
AUDIT_WINDOW_HOURS = 72
MAX_REWORK_ROUNDS = 2


def local_date(instant, offset_minutes):
    """Property-local calendar date of an instant (PRD 2.6)."""
    return (instant + timedelta(minutes=offset_minutes)).date()


def whole_minutes(delta):
    return int(delta.total_seconds() // 60)


def effective_checkout_at(outgoing):
    candidates = [outgoing["checkout_at"]]
    for key in ("late_checkout_until_at", "actual_checkout_at"):
        if outgoing.get(key) is not None:
            candidates.append(outgoing[key])
    return max(candidates)


def effective_checkin_at(incoming):
    candidates = [incoming["checkin_at"]]
    if incoming.get("early_checkin_at") is not None:
        candidates.append(incoming["early_checkin_at"])
    return min(candidates)


def required_minutes(prop, outgoing):
    raw = dec(SIZE_BASE_MINUTES[prop["size_tier"]])
    raw += dec(MINUTES_PER_BATHROOM * prop["bathroom_count"])
    raw += dec(MINUTES_PER_BED * prop["bed_count"])
    if outgoing.get("pet_stay"):
        raw = raw * PET_CLEAN_MULTIPLIER
    return max(prop["min_clean_minutes"], ceil_int(raw))


def derive_window(prop, outgoing, incoming):
    """Boundary instants, raw length and turn type (never mutates anything)."""
    start = effective_checkout_at(outgoing)
    if incoming is None:
        end = start + timedelta(hours=VACANT_WINDOW_HOURS)
        turn_type = "VACANT_GAP"
    else:
        checkin = effective_checkin_at(incoming)
        end = checkin - timedelta(minutes=INSPECTION_BUFFER_MINUTES)
        offset = prop["local_utc_offset_minutes"]
        if local_date(start, offset) == local_date(checkin, offset):
            turn_type = "SAME_DAY"
        else:
            turn_type = "OVERNIGHT"
    return {
        "window_start_at": start,
        "window_end_at": end,
        "raw_window_minutes": whole_minutes(end - start),
        "turn_type": turn_type,
    }


def turnover_boundaries(turnover):
    outgoing = db.bookings[turnover["outgoing_booking_id"]]
    incoming = None
    if turnover.get("incoming_booking_id"):
        incoming = db.bookings.get(turnover["incoming_booking_id"])
    return outgoing, incoming


def preview_recompute(turnover, prop=None, outgoing=None, incoming=None, incoming_is_set=False):
    """The window fields a recomputation would produce for this turnover."""
    if prop is None:
        prop = db.properties[turnover["property_id"]]
    if not incoming_is_set:
        outgoing, incoming = turnover_boundaries(turnover)
    derived = derive_window(prop, outgoing, incoming)
    required = required_minutes(prop, outgoing)
    window_minutes = max(0, derived["raw_window_minutes"])
    slack = window_minutes - required
    derived.update({
        "required_minutes": required,
        "window_minutes": window_minutes,
        "slack_minutes": slack,
        "is_tight": slack < TIGHT_SLACK_MINUTES,
    })
    return derived


def apply_window(turnover, derived):
    """Write derived window fields onto the turnover (caller owns version bump).

    escalation_required is raised when the window no longer covers the work and
    is never silently lowered here (PRD 3.3).
    """
    turnover["window_start_at"] = derived["window_start_at"]
    turnover["window_end_at"] = derived["window_end_at"]
    turnover["window_minutes"] = derived["window_minutes"]
    turnover["required_minutes"] = derived["required_minutes"]
    turnover["slack_minutes"] = derived["slack_minutes"]
    turnover["turn_type"] = derived["turn_type"]
    turnover["is_tight"] = derived["is_tight"]
    if derived["slack_minutes"] < 0:
        turnover["escalation_required"] = True


def is_non_terminal(turnover):
    return turnover["status"] not in ("COMPLETED", "VOID")
