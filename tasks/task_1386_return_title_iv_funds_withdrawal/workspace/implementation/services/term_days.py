"""term_day_counts calculation (SCAFFOLD §1.3).

calendar_days = (end_date - start_date) + 1
Breaks of a term are sorted by start_date ASC, then created_at ASC, and swept
greedily: a break merges into the current group when its start_date falls no
later than one calendar day after the group's current end. A group's span is
(group_end - group_start) + 1 and is deductible iff span >= 5. The group's
earliest break carries the whole span as its deductible_days; every other
break carries 0.
"""

from datetime import date, timedelta

import db

MIN_DEDUCTIBLE_BREAK_DAYS = 5

ONE_DAY = timedelta(days=1)


def parse_date(value):
    """Parse an ISO YYYY-MM-DD date string. Returns None on failure."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def date_str(d: date) -> str:
    return d.isoformat()


def recompute_term_day_counts(term_id: str) -> None:
    """Recompute deductible groups and the term's day-count figures."""
    term = db.terms[term_id]
    start = parse_date(term["start_date"])
    end = parse_date(term["end_date"])
    calendar_days = (end - start).days + 1

    term_breaks = [b for b in db.breaks.values() if b["term_id"] == term_id]
    term_breaks.sort(key=lambda b: (b["start_date"], b["_seq"]))

    # Reset deductible_days, then walk groups.
    for b in term_breaks:
        b["deductible_days"] = 0
        b["length_days"] = (parse_date(b["end_date"]) - parse_date(b["start_date"])).days + 1

    deductible_total = 0
    group_breaks = []
    group_end = None

    def close_group():
        nonlocal deductible_total, group_breaks
        if not group_breaks:
            return
        g_start = parse_date(group_breaks[0]["start_date"])
        span = (group_end - g_start).days + 1
        if span >= MIN_DEDUCTIBLE_BREAK_DAYS:
            deductible_total += span
            group_breaks[0]["deductible_days"] = span
        group_breaks = []

    for b in term_breaks:
        b_start = parse_date(b["start_date"])
        b_end = parse_date(b["end_date"])
        if not group_breaks:
            group_breaks = [b]
            group_end = b_end
        elif b_start <= group_end + ONE_DAY:
            group_breaks.append(b)
            if b_end > group_end:
                group_end = b_end
        else:
            close_group()
            group_breaks = [b]
            group_end = b_end
    close_group()

    term["calendar_days"] = calendar_days
    term["deductible_break_days"] = deductible_total
    term["total_days"] = calendar_days - deductible_total


def deductible_days_within(term_id: str, range_start: date, range_end: date) -> int:
    """Sum of deductible group days (whole group spans attributed to the
    earliest break) whose attributed break lies inside [range_start, range_end].

    For completed_days we need the deductible group days falling inside
    [term.start_date, withdrawal_date]. Since withdrawal_date is always inside
    the term and deductible groups are contiguous spans, the deductible days in
    range equal the sum over deductible groups of the overlap of the group span
    with [range_start, range_end]. We recompute groups here by replaying the
    merge from the breaks' deductible_days attribution: the earliest break of a
    deductible group carries the span, and its group's end is start + span - 1.
    """
    term_breaks = [b for b in db.breaks.values() if b["term_id"] == term_id]
    term_breaks.sort(key=lambda b: (b["start_date"], b["_seq"]))
    total = 0
    for b in term_breaks:
        span = b.get("deductible_days", 0)
        if span and span >= MIN_DEDUCTIBLE_BREAK_DAYS:
            g_start = parse_date(b["start_date"])
            g_end = g_start + timedelta(days=span - 1)
            lo = max(g_start, range_start)
            hi = min(g_end, range_end)
            if lo <= hi:
                total += (hi - lo).days + 1
    return total
