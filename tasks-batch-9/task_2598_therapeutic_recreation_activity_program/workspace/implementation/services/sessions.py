"""Session rosters, weighted supervision load and staffing requirement."""
from db import overlaps, parse_datetime
from services import clinical
from services import constants as C
from services.numbers import ceil_int, dec, divide, rhu

BLOCKING_SESSION_STATUSES = ("SCHEDULED", "IN_PROGRESS", "DOCUMENTED")


def roster(st, session_id):
    return [r for r in st.participation.values() if r["session_id"] == session_id]


def active_roster(st, session_id):
    return [r for r in roster(st, session_id) if r["status"] != "VOID"]


def session_interval(session):
    return parse_datetime(session["starts_at"]), parse_datetime(session["ends_at"])


def tier_of_record(st, record):
    resident = st.residents.get(record["resident_id"])
    if resident is None:
        return None
    return resident.get("supervision_tier")


def weighted_load(st, session, extra_tiers=()):
    """Per-tier subtotal rounded to 2dp, then the sum rounded to 2dp."""
    tiers = [tier_of_record(st, r) for r in active_roster(st, session["id"])]
    tiers.extend(extra_tiers)
    total = dec(0)
    for tier in C.TIERS:
        count = len([t for t in tiers if t == tier])
        if not count:
            continue
        total += rhu(dec(C.TIER_WEIGHT[tier]) * count, 2)
    return rhu(total, 2)


def required_staff(load, denominator):
    return ceil_int(divide(load, denominator))


def staffing_for(st, session, extra_tiers=()):
    program = st.programs.get(session["program_id"])
    denominator = program["staffing_ratio_denominator"] if program else 1
    load = weighted_load(st, session, extra_tiers)
    return float(load), required_staff(load, denominator)


def recompute_session_counters(st, session, ctx, force_bump=False):
    load, needed = staffing_for(st, session)
    values = {
        "enrolled_count": len(active_roster(st, session["id"])),
        "weighted_supervision_load": load,
        "required_staff_count": needed,
    }
    if force_bump:
        for key, value in values.items():
            session[key] = value
        ctx.bump(session)
    else:
        ctx.set_fields(session, values)


def effective_capacity(st, session):
    program = st.programs.get(session["program_id"])
    room = st.rooms.get(session["room_id"])
    return min(program["max_group_size"], room["capacity"])


def room_conflict(st, room, starts_at, ends_at, ignore_session_id=None):
    """Turnover buffer widens the candidate interval on both sides."""
    from datetime import timedelta

    buffer_minutes = room.get("buffer_minutes", 0) or 0
    lo = starts_at - timedelta(minutes=buffer_minutes)
    hi = ends_at + timedelta(minutes=buffer_minutes)
    for other in st.sessions.values():
        if other["room_id"] != room["id"]:
            continue
        if ignore_session_id and other["id"] == ignore_session_id:
            continue
        if other["status"] not in BLOCKING_SESSION_STATUSES:
            continue
        o_lo, o_hi = session_interval(other)
        if overlaps(lo, hi, o_lo, o_hi):
            return other
    return None


def has_active_roster(st, session_id):
    return len(active_roster(st, session_id)) > 0


def pending_rows(st, session_id):
    return [r for r in roster(st, session_id) if r["status"] == "PLANNED"]
