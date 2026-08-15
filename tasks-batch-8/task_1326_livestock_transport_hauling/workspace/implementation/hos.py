"""Driver hours-of-service replay (PRD 3.1, driver_hos_replay / hos_status_evaluation).

Events are replayed chronologically (occurred_at ASC, created seq ASC). All
intervals are half-open; open intervals count up to the current logical clock.
"""
from datetime import timedelta

import db
from util import minutes_between

SESSION_DRIVE_LIMIT_MIN = 660
LONG_REST_MIN = 600
DUTY_WINDOW_MIN = 840
BREAK_REQUIRED_AFTER_DRIVE_MIN = 480
BREAK_QUALIFYING_MIN = 30
CYCLE_ON_DUTY_LIMIT_MIN = 4200
CYCLE_WINDOW_MIN = 11520
SUSPENSION_CRITICAL_COUNT = 2
SUSPENSION_WINDOW_DAYS = 90

# duty sub-states
OFF, DUTY, DRIVING, ON_BREAK = "off", "duty", "driving", "break"


def driver_events(driver_id):
    evs = [e for e in db.store["duty_events"].values() if e["driver_id"] == driver_id]
    evs.sort(key=lambda e: (e["occurred_at"], e["seq"]))
    return evs


def _overlap_minutes(start, end, lo, hi):
    """Minutes of [start, end) intersected with [lo, hi]; end None means hi."""
    e = hi if end is None else min(end, hi)
    s = max(start, lo)
    if e <= s:
        return 0
    return minutes_between(s, e)


def replay(driver_id, now):
    """Return (derived_fields, sub_state) for a driver at time `now`."""
    events = driver_events(driver_id)
    driving_intervals = []   # (start, end|None)
    duty_intervals = []      # (start, end|None)
    break_intervals = []     # (start, end|None)
    gaps = []                # off-duty gaps (start, end|None)
    duty_ons = []            # (t_on, preceding_off_minutes|None-for-first)

    state = OFF
    d_on = dr_on = br_on = None
    prev_off_start = None

    for ev in events:
        t = ev["occurred_at"]
        et = ev["event_type"]
        if et == "DUTY_ON":
            if state == OFF:
                if prev_off_start is not None:
                    gaps.append((prev_off_start, t))
                    duty_ons.append((t, minutes_between(prev_off_start, t)))
                else:
                    duty_ons.append((t, None))
                state = DUTY
                d_on = t
        elif et == "DRIVING_ON":
            if state == DUTY:
                state = DRIVING
                dr_on = t
        elif et == "DRIVING_OFF":
            if state == DRIVING:
                driving_intervals.append((dr_on, t))
                dr_on = None
                state = DUTY
        elif et == "BREAK_START":
            if state == DUTY:
                state = ON_BREAK
                br_on = t
        elif et == "BREAK_END":
            if state == ON_BREAK:
                break_intervals.append((br_on, t))
                br_on = None
                state = DUTY
        elif et == "DUTY_OFF":
            if state in (DUTY, DRIVING, ON_BREAK):
                if state == DRIVING:
                    driving_intervals.append((dr_on, t))
                    dr_on = None
                if state == ON_BREAK:
                    break_intervals.append((br_on, t))
                    br_on = None
                duty_intervals.append((d_on, t))
                d_on = None
                state = OFF
                prev_off_start = t

    on_duty_now = state in (DUTY, DRIVING, ON_BREAK)
    if state == DRIVING:
        driving_intervals.append((dr_on, None))
    if state == ON_BREAK:
        break_intervals.append((br_on, None))
    if on_duty_now:
        duty_intervals.append((d_on, None))
    if state == OFF and prev_off_start is not None:
        gaps.append((prev_off_start, None))

    first_event_at = events[0]["occurred_at"] if events else None

    # ---- session window: end of last >=600-min rest, else first event
    session_start = first_event_at
    for g0, g1 in gaps:
        g1_eff = g1 if g1 is not None else now
        if minutes_between(g0, g1_eff) >= LONG_REST_MIN:
            session_start = g1 if g1 is not None else now

    session_driving = 0
    if session_start is not None:
        for s, e in driving_intervals:
            session_driving += _overlap_minutes(s, e, session_start, now)

    # ---- break credit: BREAK pair >= 30 min or off-duty gap >= 30 min
    credit_ends = []
    for b0, b1 in break_intervals:
        b1_eff = b1 if b1 is not None else now
        if minutes_between(b0, b1_eff) >= BREAK_QUALIFYING_MIN:
            credit_ends.append(b1_eff)
    for g0, g1 in gaps:
        g1_eff = g1 if g1 is not None else now
        if minutes_between(g0, g1_eff) >= BREAK_QUALIFYING_MIN:
            credit_ends.append(g1_eff)

    since = None
    if credit_ends:
        since = max(credit_ends)
    elif session_start is not None:
        since = session_start
    driving_since_break = 0
    if since is not None:
        for s, e in driving_intervals:
            driving_since_break += _overlap_minutes(s, e, since, now)

    # ---- duty-window anchor: latest DUTY_ON preceded by >=600 min off duty,
    #      else first DUTY_ON; cleared while an open >=600-min off-duty stretch
    anchor = None
    for t_on, preceding_min in duty_ons:
        if preceding_min is None:
            if anchor is None:
                anchor = t_on
        elif preceding_min >= LONG_REST_MIN:
            anchor = t_on
    if state == OFF and prev_off_start is not None:
        if minutes_between(prev_off_start, now) >= LONG_REST_MIN:
            anchor = None
    duty_window_expires_at = anchor + timedelta(minutes=DUTY_WINDOW_MIN) if anchor else None

    # ---- cycle on-duty minutes over trailing 8 days
    window_start = now - timedelta(minutes=CYCLE_WINDOW_MIN)
    cycle_minutes = 0
    for s, e in duty_intervals:
        cycle_minutes += _overlap_minutes(s, e, window_start, now)

    # ---- calendar-day driving minutes (UTC midnight .. now)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    calendar_day_driving = 0
    for s, e in driving_intervals:
        calendar_day_driving += _overlap_minutes(s, e, midnight, now)

    # ---- hos_status: pinned priority order, thresholds inclusive
    if cycle_minutes >= CYCLE_ON_DUTY_LIMIT_MIN:
        hos_status = "CYCLE_EXHAUSTED"
    elif session_driving >= SESSION_DRIVE_LIMIT_MIN:
        hos_status = "SESSION_EXHAUSTED"
    elif on_duty_now and duty_window_expires_at is not None and now > duty_window_expires_at:
        hos_status = "WINDOW_CLOSED"
    elif driving_since_break >= BREAK_REQUIRED_AFTER_DRIVE_MIN:
        hos_status = "BREAK_REQUIRED"
    else:
        hos_status = "ELIGIBLE"

    critical_count = 0
    cutoff = now - timedelta(days=SUSPENSION_WINDOW_DAYS)
    for inc in db.store["incidents"].values():
        if (
            inc["driver_id"] == driver_id
            and inc["severity"] == "CRITICAL"
            and inc["status"] == "CLOSED"
            and inc["occurred_at"] >= cutoff
        ):
            critical_count += 1

    fields = {
        "session_driving_minutes": session_driving,
        "calendar_day_driving_minutes": calendar_day_driving,
        "cycle_on_duty_minutes_8d": cycle_minutes,
        "driving_since_break_minutes": driving_since_break,
        "duty_window_expires_at": duty_window_expires_at,
        "hos_status": hos_status,
        "critical_incident_count_90d": critical_count,
    }
    return fields, state


def hos_snapshot(driver_id, now):
    return replay(driver_id, now)[0]


def duty_sub_state(driver_id, now):
    return replay(driver_id, now)[1]
