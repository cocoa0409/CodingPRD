"""Anniversary windows (PRD §3.4) and the system clock sweep (§3.3/§3.4)."""

import db
from timeutil import add_years, window_index_for
from services.common import new_id, stamp_new, touch


def window_bounds(joined, idx):
    start = add_years(joined, idx)
    end = add_years(joined, idx + 1)
    return start, end


def get_period(agent_id, idx):
    for p in db.anniversary_periods.values():
        if p["agent_id"] == agent_id and p["window_index"] == idx:
            return p
    return None


def ensure_period(agent, idx):
    """Materialize the window row lazily; status derived from the clock at
    creation (CLOSED when window_end <= clock date, else OPEN)."""
    existing = get_period(agent["id"], idx)
    if existing is not None:
        return existing
    joined = agent["_joined_date"]
    start, end = window_bounds(joined, idx)
    status = "CLOSED" if end <= db.clock_date() else "OPEN"
    period = {
        "id": new_id(),
        "agent_id": agent["id"],
        "window_index": idx,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "company_dollar_accrued_cents": 0,
        "royalty_accrued_cents": 0,
        "status": status,
    }
    stamp_new(period)
    db.anniversary_periods[period["id"]] = period
    return period


def materialize_through_clock(agent):
    """Materialize every window from the agent's join date through the window
    containing the clock date, and close every OPEN window whose end has been
    reached. Returns list of closed window ids (this call only)."""
    joined = agent["_joined_date"]
    cdate = db.clock_date()
    if joined > cdate:
        target = 0
    else:
        target = window_index_for(joined, cdate)
    for idx in range(0, target + 1):
        ensure_period(agent, idx)
    closed = []
    for p in db.anniversary_periods.values():
        if p["agent_id"] != agent["id"] or p["status"] != "OPEN":
            continue
        from timeutil import parse_date
        if parse_date(p["window_end"]) <= cdate:
            p["status"] = "CLOSED"
            touch(p)
            closed.append(p["id"])
    return closed


def sweep_clock():
    """System sweep on clock advance: activate due SCHEDULED enrollments
    (superseding the current ACTIVE one), materialize windows for every
    non-ONBOARDING agent, close elapsed windows.

    Returns (activated_enrollment_ids, closed_window_ids)."""
    from services.enrollment import activate_enrollment
    activated = []
    closed = []
    cdate = db.clock_date()

    # Enrollment activation sweep
    from timeutil import parse_date
    due = [
        e for e in db.enrollments.values()
        if e["status"] == "SCHEDULED" and parse_date(e["effective_from"]) <= cdate
    ]
    due.sort(key=lambda e: (e["effective_from"], e["created_at"], e["id"]))
    for enr in due:
        activate_enrollment(enr, bump_agent_version=True)
        activated.append(enr["id"])

    # Window materialization + close sweep for every non-ONBOARDING agent
    for agent in db.agents.values():
        if agent["status"] == "ONBOARDING":
            continue
        closed.extend(materialize_through_clock(agent))

    return activated, closed
