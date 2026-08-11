"""Core business logic helpers: calendar arithmetic, validation primitives,
serialization, and cross-entity cascade utilities.

Per PRD §2.7: deadline arithmetic adds whole calendar days and preserves
time-of-day; one-second precision; floor division for percentages; strict
integer comparison for brief limits; half-open intervals for conflicts.
"""
from datetime import timedelta

from db import STORE, now_iso, parse_iso, fmt_iso, new_id, new_confirmation_number
from errors import ApiError


# ---------------------------------------------------------------------------
# Field / payload validation
# ---------------------------------------------------------------------------

def get_body():
    from flask import request
    if not request.is_json:
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be JSON", 400)
    try:
        body = request.get_json(force=False, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Malformed JSON body", 400)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be an object", 400)
    return body


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{field}' must be a non-empty string", 400)
    return v


def opt_str(body, field, default=None):
    v = body.get(field, default)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{field}' must be a string", 400)
    return v


def req_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{field}' must be an integer", 400)
    return v


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{field}' must be a boolean", 400)
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST",
                       f"Field '{field}' must be one of {sorted(allowed)}", 400)
    return v


def req_str_list(body, field):
    v = body.get(field)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{field}' must be an array of strings", 400)
    return list(v)


def req_iso(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{field}' must be an ISO8601 string", 400)
    try:
        parse_iso(v)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{field}' is not a valid ISO8601 timestamp", 400)
    return v


def opt_iso(body, field, default=None):
    v = body.get(field, default)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{field}' must be an ISO8601 string", 400)
    try:
        parse_iso(v)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{field}' is not a valid ISO8601 timestamp", 400)
    return v


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------

def pagination_params():
    from flask import request
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_PAGINATION", "limit must be an integer in 1..100", 400)
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_PAGINATION", "offset must be a non-negative integer", 400)
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError("ERR_PAGINATION", "limit must be 1..100 and offset >= 0", 400)
    return limit, offset


def sort_items(items):
    """List responses sorted by created_at ascending; sequence number breaks ties."""
    return sorted(items, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))


def paginate(items):
    limit, offset = pagination_params()
    ordered = sort_items(items)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    for r in page:
        r.pop("_seq", None)
    return page, limit, offset, total


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------

def _lookup(table, entity_id, err):
    row = table.get(entity_id)
    if row is None:
        raise ApiError(err[0], err[1], err[2])
    return row


def path_court(cid):
    return _lookup(STORE.courts, cid, ("ERR_NOT_FOUND", "Court not found", 404))


def path_attorney(aid):
    return _lookup(STORE.attorneys, aid, ("ERR_NOT_FOUND", "Attorney not found", 404))


def path_case(cid):
    return _lookup(STORE.cases, cid, ("ERR_NOT_FOUND", "Case not found", 404))


def path_event(eid):
    return _lookup(STORE.events, eid, ("ERR_NOT_FOUND", "Event not found", 404))


def path_deadline(did):
    return _lookup(STORE.deadlines, did, ("ERR_NOT_FOUND", "Deadline not found", 404))


def path_record(rid):
    return _lookup(STORE.records, rid, ("ERR_NOT_FOUND", "Record not found", 404))


def path_transcript(tid):
    return _lookup(STORE.transcript_orders, tid, ("ERR_NOT_FOUND", "Transcript order not found", 404))


def path_schedule(sid):
    return _lookup(STORE.briefing_schedules, sid, ("ERR_NOT_FOUND", "Briefing schedule not found", 404))


def path_brief(bid):
    return _lookup(STORE.briefs, bid, ("ERR_NOT_FOUND", "Brief not found", 404))


def path_toa(tid):
    return _lookup(STORE.toas, tid, ("ERR_NOT_FOUND", "Table of authorities not found", 404))


def path_citation(cid):
    return _lookup(STORE.citations, cid, ("ERR_NOT_FOUND", "Citation not found", 404))


def path_motion(mid):
    return _lookup(STORE.extension_motions, mid, ("ERR_NOT_FOUND", "Extension motion not found", 404))


def path_filing(fid):
    return _lookup(STORE.filings, fid, ("ERR_NOT_FOUND", "Filing not found", 404))


def path_argument(aid):
    return _lookup(STORE.oral_arguments, aid, ("ERR_NOT_FOUND", "Oral argument not found", 404))


def path_decision(did):
    return _lookup(STORE.decisions, did, ("ERR_NOT_FOUND", "Decision not found", 404))


def path_petition(pid):
    return _lookup(STORE.petitions, pid, ("ERR_NOT_FOUND", "Petition not found", 404))


def fk_court(cid):
    if not isinstance(cid, str):
        raise ApiError("ERR_INVALID_REQUEST", "court_id must be a string", 400)
    return _lookup(STORE.courts, cid, ("ERR_FK_NOT_FOUND", "court_id not found", 404))


def fk_attorney(aid, field="attorney_id"):
    if not isinstance(aid, str):
        raise ApiError("ERR_INVALID_REQUEST", f"{field} must be a string", 400)
    return _lookup(STORE.attorneys, aid, ("ERR_FK_NOT_FOUND", f"{field} not found", 404))


def fk_schedule(sid):
    if not isinstance(sid, str):
        raise ApiError("ERR_INVALID_REQUEST", "schedule_id must be a string", 400)
    return _lookup(STORE.briefing_schedules, sid, ("ERR_FK_NOT_FOUND", "schedule_id not found", 404))


def fk_brief(bid):
    if not isinstance(bid, str):
        raise ApiError("ERR_INVALID_REQUEST", "brief_id must be a string", 400)
    return _lookup(STORE.briefs, bid, ("ERR_FK_NOT_FOUND", "brief_id not found", 404))


def fk_decision(did):
    if not isinstance(did, str):
        raise ApiError("ERR_INVALID_REQUEST", "basis_decision_id must be a string", 400)
    return _lookup(STORE.decisions, did, ("ERR_FK_NOT_FOUND", "basis_decision_id not found", 404))


# ---------------------------------------------------------------------------
# Entity construction / mutation helpers
# ---------------------------------------------------------------------------

def new_entity(fields):
    ts = now_iso()
    ent = dict(fields)
    ent["id"] = new_id()
    ent["created_at"] = ts
    ent["updated_at"] = ts
    ent["version"] = 1
    ent["_seq"] = STORE.next_seq()
    return ent


def touch(ent):
    """Increment version and refresh updated_at (PRD §2.4, §2.8)."""
    ent["version"] += 1
    ent["updated_at"] = now_iso()


# ---------------------------------------------------------------------------
# Calendar arithmetic (PRD §2.7)
# ---------------------------------------------------------------------------

def add_calendar_days(iso_ts, days):
    dt = parse_iso(iso_ts)
    return fmt_iso(dt + timedelta(days=days))


# US federal court holidays for 2026-2030 (fixed-date observance).
_HOLIDAYS_MD = {
    (1, 1),   # New Year's Day
    (6, 19),  # Juneteenth
    (7, 4),   # Independence Day
    (11, 11), # Veterans Day
    (12, 25), # Christmas
}


def _observed_holiday_dates(year):
    """Return set of (month, day) for fixed holidays, observed Fri/Mon when on weekend."""
    from datetime import date
    out = set()
    for (m, d) in _HOLIDAYS_MD:
        actual = date(year, m, d)
        wd = actual.weekday()
        if wd == 5:  # Saturday -> observed Friday
            out.add((m, d - 1) if d > 1 else (12, 31))
        elif wd == 6:  # Sunday -> observed Monday
            if m == 12 and d == 25:
                out.add((12, 26))
            elif m == 1 and d == 1:
                out.add((1, 2))
            else:
                out.add((m, d + 1))
        out.add((m, d))
    # Floating holidays
    def nth_weekday(month, weekday, n):
        from datetime import date
        d = date(year, month, 1)
        delta = (weekday - d.weekday()) % 7
        return d + timedelta(days=delta + 7 * (n - 1))

    def last_weekday(month, weekday):
        from datetime import date
        if month == 12:
            d = date(year, 12, 31)
        else:
            d = date(year, month + 1, 1) - timedelta(days=1)
        delta = (d.weekday() - weekday) % 7
        return d - timedelta(days=delta)

    mlk = nth_weekday(1, 0, 3)          # 3rd Monday Jan
    presidents = nth_weekday(2, 0, 3)   # 3rd Monday Feb
    memorial = last_weekday(5, 0)       # last Monday May
    labor = nth_weekday(9, 0, 1)        # 1st Monday Sep
    columbus = nth_weekday(10, 0, 2)    # 2nd Monday Oct
    thanksgiving = nth_weekday(11, 3, 4)  # 4th Thursday Nov
    day_after = thanksgiving + timedelta(days=1)
    for d in (mlk, presidents, memorial, labor, columbus, thanksgiving, day_after):
        out.add((d.month, d.day))
    return out


def is_business_day(dt):
    if dt.weekday() >= 5:
        return False
    md = (dt.month, dt.day)
    if md in _observed_holiday_dates(dt.year):
        return False
    # Handle Jan-1 observed on Dec 31 of previous year
    if dt.month == 12 and dt.day == 31 and dt.weekday() == 4:
        nxt = dt + timedelta(days=1)
        if nxt.weekday() == 5:  # Jan 1 next year is Saturday
            return False
    return True


def roll_forward(iso_ts):
    dt = parse_iso(iso_ts)
    while not is_business_day(dt):
        dt = dt + timedelta(days=1)
    return fmt_iso(dt)


# ---------------------------------------------------------------------------
# Lookups across collections
# ---------------------------------------------------------------------------

def court_for_case(case):
    return STORE.courts.get(case["court_id"])


def record_for_case(case_id):
    for r in STORE.records.values():
        if r["case_id"] == case_id:
            return r
    return None


def schedule_for_case(case_id):
    for s in STORE.briefing_schedules.values():
        if s["case_id"] == case_id:
            return s
    return None


def toa_for_brief(brief_id):
    for t in STORE.toas.values():
        if t["brief_id"] == brief_id:
            return t
    return None


def transcripts_for_record(record_id):
    return [t for t in STORE.transcript_orders.values() if t["record_id"] == record_id]


def briefs_for_schedule(schedule_id):
    return [b for b in STORE.briefs.values() if b["schedule_id"] == schedule_id]


def deadlines_for_case(case_id):
    return [d for d in STORE.deadlines.values() if d["case_id"] == case_id]


def filings_for_case(case_id):
    return [f for f in STORE.filings.values() if f["case_id"] == case_id]


def decisions_for_case(case_id):
    return [d for d in STORE.decisions.values() if d["case_id"] == case_id]


def petitions_for_case(case_id):
    return [p for p in STORE.petitions.values() if p["case_id"] == case_id]


# ---------------------------------------------------------------------------
# Brief limit check (SCAFFOLD calc: brief_limit_check; PRD §3.5)
# ---------------------------------------------------------------------------

def compute_over_limit(brief, court):
    if court["uses_word_count"]:
        limit = court["max_words_reply"] if brief["brief_type"] == "REPLY" else court["max_words_opening"]
        used = brief.get("word_count") or 0
    else:
        limit = court["max_pages_reply"] if brief["brief_type"] == "REPLY" else court["max_pages_opening"]
        used = brief.get("page_count") or 0
    return used > limit


# ---------------------------------------------------------------------------
# Record completeness (SCAFFOLD calc: record_completeness_pct; PRD §3.3)
# ---------------------------------------------------------------------------

def recompute_record_completeness(record):
    orders = transcripts_for_record(record["id"])
    designated = [o for o in orders if o["status"] != "CANCELLED"]
    delivered = [o for o in designated if o["status"] in ("DELIVERED", "FILED")]
    if len(designated) == 0:
        pct = 0
    else:
        pct = (100 * len(delivered)) // len(designated)
    record["completeness_pct"] = pct
    return pct


# ---------------------------------------------------------------------------
# TOA counts (SCAFFOLD calc: toa_unverified_count; PRD §3.5)
# ---------------------------------------------------------------------------

def recompute_toa_counts(toa):
    cits = [c for c in STORE.citations.values() if c["toa_id"] == toa["id"]]
    verified = [c for c in cits if c["verified"]]
    toa["citation_count"] = len(cits)
    toa["verified_count"] = len(verified)
    toa["unverified_count"] = len(cits) - len(verified)


# ---------------------------------------------------------------------------
# Briefing schedule dates (SCAFFOLD calc: briefing_schedule_dates; PRD §3.4)
# ---------------------------------------------------------------------------

DEFAULT_OPENING_DAYS = 40
DEFAULT_RESPONSE_DAYS = 30


def compute_schedule_dates(anchor_iso, court, granted_motions):
    opening = add_calendar_days(anchor_iso, DEFAULT_OPENING_DAYS)
    response = add_calendar_days(opening, DEFAULT_RESPONSE_DAYS)
    reply = add_calendar_days(response, court["reply_brief_window_days"])
    # Apply granted motions chronologically by decided_at, tie-break created_at
    ordered = sorted(
        granted_motions,
        key=lambda m: (m.get("decided_at") or "", m.get("created_at") or "", m.get("_seq", 0)),
    )
    for m in ordered:
        delta = m["granted_days"]
        if m["target"] == "OPENING":
            opening = add_calendar_days(opening, delta)
            response = add_calendar_days(response, delta)
            reply = add_calendar_days(reply, delta)
        elif m["target"] == "RESPONSE":
            response = add_calendar_days(response, delta)
            reply = add_calendar_days(reply, delta)
        elif m["target"] == "REPLY":
            reply = add_calendar_days(reply, delta)
    return opening, response, reply


def granted_motions_for_schedule(schedule_id):
    return [m for m in STORE.extension_motions.values()
            if m["schedule_id"] == schedule_id and m["status"] == "GRANTED"]


BRIEF_TYPE_TO_DEADLINE_KIND = {
    "OPENING": "OPENING_BRIEF",
    "RESPONSE": "RESPONSE_BRIEF",
    "REPLY": "REPLY_BRIEF",
}

DEADLINE_KIND_TO_SCHEDULE_FIELD = {
    "OPENING_BRIEF": "opening_due_at",
    "RESPONSE_BRIEF": "response_due_at",
    "REPLY_BRIEF": "reply_due_at",
}


def schedule_due_for_brief_type(schedule, brief_type):
    if brief_type == "REPLY":
        return schedule.get("reply_due_at")
    if brief_type == "RESPONSE":
        return schedule.get("response_due_at")
    return schedule.get("opening_due_at")
