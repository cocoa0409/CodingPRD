"""Channel pacing, the throttle cascade and the THROTTLED-outranks-IDLE rule."""

from fractions import Fraction

import db
from services import budget, calc


def recompute_pacing(channel):
    """channel_blended_cpqa_target followed immediately by channel_cpqa."""
    credited = calc.channel_credited_qualified_bp(channel)
    if credited == 0:
        channel["blended_target_cents"] = None
        channel["cpqa_cents"] = None
        channel["pacing_status"] = "PACING_UNKNOWN"
    else:
        channel["blended_target_cents"] = calc.channel_blended_target_cents(channel)
        spent = calc.channel_spent_cents(channel)
        channel["cpqa_cents"] = db.rhu(Fraction(spent * 10000, credited))
        target = channel["blended_target_cents"]
        if target is None:
            channel["pacing_status"] = "ON_TARGET"
        else:
            threshold = db.rhu(Fraction(target * 12, 10))
            channel["pacing_status"] = (
                "THROTTLED" if channel["cpqa_cents"] > threshold else "ON_TARGET")
    if channel["pacing_status"] == "THROTTLED":
        db.mark_throttled(channel["id"])
    return channel["pacing_status"]


def apply_throttle(channel):
    """Pause every ACTIVE flight of a channel that has just become THROTTLED."""
    if channel["pacing_status"] != "THROTTLED":
        return False
    moved_money = False
    flights = sorted(calc.channel_flights(channel["id"]),
                     key=lambda f: f["created_at"])
    for flight in flights:
        if flight["state"] != "ACTIVE":
            continue
        flight["state"] = "PAUSED_PACING"
        flight["release_reason"] = "PACING_THROTTLE"
        flight["reserved_cents"] = 0
        program = calc.program_of_family(db.job_families[flight["job_family_id"]])
        if budget.release(program, flight["id"], "FLIGHT_PACING_THROTTLE"):
            moved_money = True
            db.touch(program)
        db.touch(flight)
    return moved_money


def resolve_idle(channel):
    """Called after a flight leaves ACTIVE; THROTTLED outranks IDLE (PRD 2.10)."""
    if calc.channel_active_flight_count(channel) != 0:
        return
    if db.was_throttled(channel["id"]) or channel["pacing_status"] == "THROTTLED":
        return
    channel["pacing_status"] = "IDLE"
    channel["idle_since"] = db.clock()


def enter_active(channel):
    channel["idle_since"] = None
