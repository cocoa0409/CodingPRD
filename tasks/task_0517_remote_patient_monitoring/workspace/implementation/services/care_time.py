"""Care-time aggregation with the daily cap (PRD §3.7 / care_time_aggregation).

counted_minutes per CareActivity:
  cap the per-calendar-day sum of minutes (by performed_at UTC date) at 60;
  when a day's logged minutes exceed the cap, allocate the cap to activities in
  ascending performed_at order (ties broken by created_at ASC, then creation
  sequence ASC), filling earlier activities first; later activities on that day
  receive 0 counted_minutes.

period total = sum of counted_minutes over all CareActivity rows whose
  performed_at falls within the billing month AND billing_period_id == period.id.
"""
from clock import parse_iso8601

MAX_MINUTES_PER_DAY = 60


def _day_key(activity):
    dt = parse_iso8601(activity["performed_at"])
    return dt.date().isoformat()


def _order_key(activity):
    # ascending performed_at, ties broken by created_at ASC, then _seq ASC
    return (activity["performed_at"], activity["created_at"], activity["_seq"])


def compute_counted_minutes(period_activities):
    """Given the list of CareActivity records belonging to one period (already
    filtered to in-month, same billing_period_id), return a dict
    {activity_id: counted_minutes} applying the per-day cap allocation.
    """
    by_day = {}
    for a in period_activities:
        by_day.setdefault(_day_key(a), []).append(a)

    result = {}
    for day, acts in by_day.items():
        ordered = sorted(acts, key=_order_key)
        remaining = MAX_MINUTES_PER_DAY
        for a in ordered:
            m = a["minutes"]
            if remaining <= 0:
                result[a["id"]] = 0
            elif m <= remaining:
                result[a["id"]] = m
                remaining -= m
            else:
                result[a["id"]] = remaining
                remaining = 0
    return result


def period_total(counted_map):
    return sum(counted_map.values())
