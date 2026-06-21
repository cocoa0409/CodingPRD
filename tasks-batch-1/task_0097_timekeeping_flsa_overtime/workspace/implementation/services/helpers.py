"""Shared lookups and cascade helpers."""
from datetime import date, datetime, timedelta, timezone

import db
from errors import err


def get_or_404(collection, resource_id):
    """Existence check (priority 4 / PRD §2.7): ERR_NOT_FOUND if absent."""
    record = collection.get(resource_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "Referenced resource does not exist.")
    return record


def date_of(iso_dt):
    """UTC calendar date (YYYY-MM-DD) of an ISO datetime string."""
    if iso_dt is None:
        return None
    s = iso_dt
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).date().isoformat()


def week_dates(workweek_start):
    start = date.fromisoformat(workweek_start)
    return [(start + timedelta(days=i)).isoformat() for i in range(7)]


def covering_week_for_punch(punch):
    """The TimesheetWeek (if any) covering this punch's workday_date for its
    employee. Used for the frozen-timesheet guard and edit/void cascade."""
    workday = punch.get("workday_date")
    if workday is None:
        return None
    for w in db.timesheet_weeks.values():
        if w.get("employee_id") != punch.get("employee_id"):
            continue
        if workday in week_dates(w["workweek_start"]):
            return w
    return None


def find_week_covering(employee_id, workday_date):
    if workday_date is None:
        return None
    for w in db.timesheet_weeks.values():
        if w.get("employee_id") != employee_id:
            continue
        if workday_date in week_dates(w["workweek_start"]):
            return w
    return None
