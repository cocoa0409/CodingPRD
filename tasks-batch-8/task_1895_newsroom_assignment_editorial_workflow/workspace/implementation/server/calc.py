"""Calculation rules per SCAFFOLD Table 3 / PRD sections 3.2, 3.3, 3.7.

All money arithmetic uses Decimal with ROUND_HALF_UP. Scores are rounded
half-up to 2 decimal places; money to integer cents (0 dp).
"""

from datetime import timedelta

from .store import STORE, now

# --- story_priority_score constants ---
URGENCY_WEIGHT = {"STANDARD": 10, "URGENT": 25, "BREAKING": 40}
DESK_WEIGHT = {"METRO": 5, "BUSINESS": 4, "SPORTS": 3, "FEATURES": 2}
TIME_PRESSURE_HORIZON_HOURS = 72
TIME_PRESSURE_MAX_POINTS = 30
ANALYTICS_DESK_FRACTION = 0.6
ANALYTICS_TRACK_FRACTION = 0.4

# --- assignment_cost constants ---
WEEKLY_REGULAR_MINUTES = 2400
OT_MULTIPLIER = 1.5

# --- performance_score constants ---
TIER_MULT = {"A": 1.25, "B": 1.0, "C": 0.8}
REALTIME_DAMPEN = 0.9

# --- breaking news constants ---
BUMP_FLOOR = {1: 9999, 2: 60, 3: 30}
CALL_IN_TTL_MINUTES = 60


def _round_half_up(value, places):
    """Round a float-ish numeric half-up to the given decimal places.
    Returns int when places == 0, else float with exactly `places` dp."""
    from decimal import Decimal, ROUND_HALF_UP

    q = Decimal(1).scaleb(-places)
    d = Decimal(repr(value)).quantize(q, rounding=ROUND_HALF_UP)
    if places == 0:
        return int(d)
    return float(d)


def desk_base_score(pitch):
    """DESK_FORWARD base score: round_half_up(urgency_w*2 + desk_w + time_pressure*30, 2)."""
    urgency_w = URGENCY_WEIGHT[pitch["urgency"]]
    desk_w = DESK_WEIGHT[pitch["desk"]]
    delta_seconds = (pitch["deadline_at"] - now()).total_seconds()
    hours_to_deadline = delta_seconds / 3600.0
    time_pressure = (TIME_PRESSURE_HORIZON_HOURS - hours_to_deadline) / float(
        TIME_PRESSURE_HORIZON_HOURS
    )
    if time_pressure < 0:
        time_pressure = 0.0
    elif time_pressure > 1:
        time_pressure = 1.0
    base = urgency_w * 2 + desk_w + time_pressure * TIME_PRESSURE_MAX_POINTS
    return _round_half_up(base, 2)


def author_track_record(author_staff_id):
    """Mean of ACTIVE, SETTLED analytics performance_score over the author's
    PUBLISHED/RETRACTED stories; 0 when empty; rounded half-up to 2 dp."""
    scores = []
    for a in STORE.analytics.values():
        if a["status"] != "ACTIVE" or a["variant"] != "SETTLED":
            continue
        story = STORE.stories.get(a["story_id"])
        if story is None:
            continue
        if story["author_staff_id"] != author_staff_id:
            continue
        if story["status"] not in ("PUBLISHED", "RETRACTED"):
            continue
        scores.append(a["performance_score"])
    if not scores:
        return 0
    return _round_half_up(sum(scores) / len(scores), 2)


def priority_score(pitch, variant):
    """DESK -> stored desk-forward base; ANALYTICS -> 0.6*base + 0.4*track_record."""
    base = desk_base_score(pitch)
    if variant == "ANALYTICS":
        track = author_track_record(pitch["submitting_staff_id"])
        blended = ANALYTICS_DESK_FRACTION * base + ANALYTICS_TRACK_FRACTION * track
        return _round_half_up(blended, 2)
    return base


def provisional_cost_cents(planned_effort_minutes, hourly_rate_cents):
    rate_per_minute = hourly_rate_cents / 60.0
    return _round_half_up(planned_effort_minutes * rate_per_minute, 0)


def payroll_week_bounds(week_start_date):
    """Return (start_dt, end_dt) for a Monday date."""
    start = week_start_date
    end = start + timedelta(days=7)
    return start, end


def monday_of(dt):
    """Monday 00:00:00Z of the payroll week containing dt."""
    day = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return day - timedelta(days=day.weekday())


def week_completed_assignments(staff_id, week_start):
    """COMPLETED assignments of staff whose completed_at falls in
    [week_start, week_start + 7d), ordered completed_at ASC, tie created_at ASC."""
    week_end = week_start + timedelta(days=7)
    items = [
        a
        for a in STORE.assignments.values()
        if a["staff_id"] == staff_id
        and a["status"] == "COMPLETED"
        and a["completed_at"] is not None
        and week_start <= a["completed_at"] < week_end
    ]
    items.sort(key=lambda a: (a["completed_at"], a["created_at"], a["_seq"]))
    return items


def allocate_week(staff_id, week_start):
    """Chronological weekly overtime allocation.

    Returns list of (assignment, reg, ot, final_cost_cents) tuples in
    chronological order."""
    items = week_completed_assignments(staff_id, week_start)
    running = 0
    out = []
    for a in items:
        staff = STORE.staff[a["staff_id"]]
        rate_per_minute = staff["hourly_rate_cents"] / 60.0
        actual = a["actual_effort_minutes"]
        room = WEEKLY_REGULAR_MINUTES - running
        if room < 0:
            room = 0
        reg = min(actual, room)
        ot = actual - reg
        final = _round_half_up((reg + ot * OT_MULTIPLIER) * rate_per_minute, 0)
        out.append((a, reg, ot, final))
        running += actual
    return out


def reallocate_week_for(staff_id, completed_at):
    """Re-run FINAL allocation for the payroll week containing completed_at and
    persist final_cost_cents on each COMPLETED assignment in that week."""
    week_start = monday_of(completed_at)
    for a, _reg, _ot, final in allocate_week(staff_id, week_start):
        a["final_cost_cents"] = final


def performance_score(views, engagement_minutes, variant):
    """Three-stage pinned evaluation: raw -> tier -> multiplier.

    Returns (raw_score, tier, performance_score)."""
    raw = _round_half_up((views * 6 + engagement_minutes * 4) / 100.0, 2)
    if raw >= 100:
        tier = "A"
    elif raw >= 40:
        tier = "B"
    else:
        tier = "C"
    if variant == "REALTIME":
        score = _round_half_up(raw * TIER_MULT[tier] * REALTIME_DAMPEN, 2)
    else:
        score = _round_half_up(raw * TIER_MULT[tier], 2)
    return raw, tier, score


def recompute_active_assignment_count(staff_id):
    staff = STORE.staff.get(staff_id)
    if staff is None:
        return
    count = sum(
        1
        for a in STORE.assignments.values()
        if a["staff_id"] == staff_id and a["status"] in ("PROPOSED", "ACCEPTED")
    )
    staff["active_assignment_count"] = count


def recompute_slot_reserved_count(slot_id):
    slot = STORE.slots.get(slot_id)
    if slot is None:
        return
    count = sum(
        1
        for s in STORE.stories.values()
        if s.get("slot_id") == slot_id and s["status"] == "SCHEDULED"
    )
    slot["reserved_count"] = count
