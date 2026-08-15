"""Routes: meets, sessions, squads, gymnasts, athlete entries."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

from common import (APPARATUS, ApiError, DB, LEVEL_BAND_SET, RE_GYMNAST,
                    RE_SANCTION, apply_filters, authorize, body, enum_val,
                    fk_or_404, get_or_404, level_compatible, new_entity, now,
                    ok_array, ok_list, ok_object, opt_enum, opt_int, parse_dt,
                    req_enum, req_int, req_str, required, score_field,
                    sort_items, touch)
from logic import (recompute_conflicts_for_session, recompute_panel,
                   run_session_close_computations, run_system_transitions,
                   squad_assignment)
from serialize import (ser_entry, ser_gymnast, ser_meet, ser_session,
                       ser_squad)

bp = Blueprint("core", __name__)

ALL_READ = ["MeetDirector", "MeetReferee", "JudgePanelChief", "Coach",
            "Spectator", "GateAttendant"]
SESSION_READ = ["MeetDirector", "MeetReferee", "JudgePanelChief", "Coach",
                "Spectator"]
STAFF_READ = ["MeetDirector", "MeetReferee", "JudgePanelChief", "Coach"]

MEET_TERMINAL = ("ARCHIVED",)
SESSION_TERMINAL = ("CLOSED",)
ENTRY_TERMINAL = ("COMPLETED", "SCRATCHED")


# ----------------------------------------------------------------------------
# Meets
# ----------------------------------------------------------------------------

@bp.post("/api/v1/meets")
def create_meet():
    authorize(["MeetDirector"])
    data = body()
    meet_name = req_str(data, "meet_name")
    sanction_year = req_int(data, "sanction_year")
    sanction_number = req_str(data, "sanction_number")
    if not RE_SANCTION.match(sanction_number):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "sanction_number must match ^USAG-[0-9]{4}-[0-9]{4}$")
    venue_name = req_str(data, "venue_name")
    start_date = parse_dt(required(data, "start_date"), "start_date")
    end_date = parse_dt(required(data, "end_date"), "end_date")
    if end_date < start_date:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "end_date must not precede start_date")
    tiebreak_policy = opt_enum(data, "tiebreak_policy",
                               {"USAG_CLASSIC", "NCAA_MODIFIED"}, "USAG_CLASSIC")
    qual_rule = opt_enum(data, "qualifying_score_rule",
                         {"ALL_AROUND_ONLY", "PER_EVENT", "BOTH"}, "BOTH")
    inquiry_window = opt_int(data, "inquiry_window_minutes", 5)
    max_per_squad = opt_int(data, "max_athletes_per_squad", 12)

    for m in DB.meets.values():
        if m["sanction_number"] == sanction_number:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "sanction_number must be globally unique")
        if m["meet_name"] == meet_name and m["sanction_year"] == sanction_year:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "meet_name must be unique within sanction_year")

    m = new_entity()
    m.update({
        "meet_name": meet_name,
        "sanction_year": sanction_year,
        "sanction_number": sanction_number,
        "venue_name": venue_name,
        "start_date": start_date,
        "end_date": end_date,
        "posture": "DRAFT",
        "tiebreak_policy": tiebreak_policy,
        "qualifying_score_rule": qual_rule,
        "inquiry_window_minutes": inquiry_window,
        "max_athletes_per_squad": max_per_squad,
    })
    DB.meets[m["id"]] = m
    return ok_object(ser_meet(m), 201)


@bp.get("/api/v1/meets")
def list_meets():
    authorize(ALL_READ)
    items = apply_filters(sort_items(DB.meets.values()),
                          {"posture": ("str", "posture"),
                           "sanction_year": ("int", "sanction_year")})
    return ok_list([ser_meet(m) for m in items])


@bp.get("/api/v1/meets/<mid>")
def get_meet(mid):
    authorize(ALL_READ)
    return ok_object(ser_meet(get_or_404(DB.meets, mid, "Meet")))


def _meet_action(mid, from_state, fn):
    authorize(["MeetDirector"])
    meet = get_or_404(DB.meets, mid, "Meet")
    if meet["posture"] in MEET_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", 409,
                       "Meet is in terminal posture ARCHIVED")
    if meet["posture"] != from_state:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Meet posture is %s, expected %s" % (meet["posture"], from_state))
    fn(meet)
    touch(meet)
    run_system_transitions()
    return ok_object(ser_meet(meet))


@bp.post("/api/v1/meets/<mid>/publish")
def publish_meet(mid):
    def do(meet):
        sessions = [s for s in DB.sessions.values() if s["meet_id"] == meet["id"]]
        for s in sessions:
            if (s["scheduled_start"] < meet["start_date"]
                    or s["scheduled_end"] > meet["end_date"] + timedelta(hours=2)):
                raise ApiError("ERR_SESSION_OUTSIDE_MEET_WINDOW", 422,
                               "Session %s lies outside the meet window" % s["id"])
        for s in sessions:
            if not any(q["session_id"] == s["id"] for q in DB.squads.values()):
                raise ApiError("ERR_INVALID_STATE", 409,
                               "Session %s has no squad assigned" % s["id"])
        for s in sessions:
            if s["state"] != "SCHEDULED":
                s["state"] = "SCHEDULED"
                touch(s)
        for p in DB.panels.values():
            if p["meet_id"] == meet["id"]:
                recompute_panel(p)
        meet["posture"] = "SCHEDULED"
    return _meet_action(mid, "DRAFT", do)


@bp.post("/api/v1/meets/<mid>/close-scoring")
def close_meet_scoring(mid):
    def do(meet):
        sessions = [s for s in DB.sessions.values() if s["meet_id"] == meet["id"]]
        for s in sessions:
            if s["state"] != "CLOSED":
                raise ApiError("ERR_INVALID_STATE", 409,
                               "Session %s is not CLOSED" % s["id"])
        entry_ids = {e["id"] for e in DB.entries.values()
                     if DB.sessions.get(e["session_id"])
                     and DB.sessions[e["session_id"]]["meet_id"] == meet["id"]}
        meet_scores = [sc for sc in DB.scores.values()
                       if sc["athlete_entry_id"] in entry_ids]
        for sc in meet_scores:
            if sc["score_state"] not in ("FINAL", "VOID"):
                raise ApiError("ERR_INVALID_STATE", 409,
                               "Score %s is not FINAL or VOID" % sc["id"])
        score_ids = {sc["id"] for sc in meet_scores}
        for iq in DB.inquiries.values():
            if iq["score_id"] in score_ids and iq["inquiry_state"] in (
                    "FILED", "UNDER_REVIEW"):
                raise ApiError("ERR_INVALID_STATE", 409,
                               "Inquiry %s is still open" % iq["id"])
        for s in sessions:
            run_session_close_computations(s)
        meet["posture"] = "SCORING_CLOSED"
    return _meet_action(mid, "IN_COMPETITION", do)


@bp.post("/api/v1/meets/<mid>/finalize")
def finalize_meet(mid):
    def do(meet):
        session_ids = {s["id"] for s in DB.sessions.values()
                       if s["meet_id"] == meet["id"]}
        for a in DB.awards.values():
            if a["session_id"] in session_ids and a["ceremony_order"] is None:
                raise ApiError("ERR_INVALID_STATE", 409,
                               "Award %s has no ceremony_order" % a["id"])
        entry_ids = {e["id"] for e in DB.entries.values()
                     if e["session_id"] in session_ids}
        for r in DB.qual_records.values():
            if r["athlete_entry_id"] in entry_ids and r["qualification_state"] \
                    not in ("CONFIRMED", "DECLINED", "REVOKED"):
                raise ApiError("ERR_INVALID_STATE", 409,
                               "QualificationRecord %s is not resolved" % r["id"])
        meet["posture"] = "FINALIZED"
    return _meet_action(mid, "SCORING_CLOSED", do)


@bp.post("/api/v1/meets/<mid>/archive")
def archive_meet(mid):
    def do(meet):
        meet["posture"] = "ARCHIVED"
    return _meet_action(mid, "FINALIZED", do)


# ----------------------------------------------------------------------------
# Sessions
# ----------------------------------------------------------------------------

@bp.post("/api/v1/meets/<mid>/sessions")
def create_session(mid):
    authorize(["MeetDirector"])
    meet = get_or_404(DB.meets, mid, "Meet")
    data = body()
    if meet["posture"] in ("IN_COMPETITION", "SCORING_CLOSED", "FINALIZED",
                           "ARCHIVED"):
        raise ApiError("ERR_MEET_POSTURE_FORBIDS", 409,
                       "Meet posture %s forbids session creation" % meet["posture"])
    session_label = req_str(data, "session_label")
    level_band = req_enum(data, "level_band", LEVEL_BAND_SET)
    scheduled_start = parse_dt(required(data, "scheduled_start"), "scheduled_start")
    scheduled_end = parse_dt(required(data, "scheduled_end"), "scheduled_end")
    if scheduled_end <= scheduled_start:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "scheduled_end must be after scheduled_start")
    apparatus_set = required(data, "apparatus_set")
    if not isinstance(apparatus_set, list) or len(apparatus_set) != 4:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "apparatus_set must contain exactly four elements")
    seen = set()
    for slot in apparatus_set:
        if not isinstance(slot, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "apparatus_set elements must be objects")
        app = enum_val(slot.get("apparatus"), APPARATUS, "apparatus")
        fc = slot.get("flight_count")
        if isinstance(fc, bool) or not isinstance(fc, int):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "flight_count must be an integer")
        if app in seen:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "each apparatus must appear exactly once")
        seen.add(app)
    if seen != APPARATUS:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "apparatus_set must cover all four apparatus")
    warmup_offset = opt_int(data, "warmup_open_offset_minutes", 90)
    march_in_offset = opt_int(data, "march_in_offset_minutes", 15)
    for s in DB.sessions.values():
        if s["meet_id"] == mid and s["session_label"] == session_label:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "session_label must be unique within the meet")
    if (scheduled_start < meet["start_date"]
            or scheduled_end > meet["end_date"] + timedelta(hours=2)):
        raise ApiError("ERR_SESSION_OUTSIDE_MEET_WINDOW", 422,
                       "Session scheduled interval is outside the meet window")
    s = new_entity()
    s.update({
        "meet_id": mid,
        "session_label": session_label,
        "level_band": level_band,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "warmup_open_offset_minutes": warmup_offset,
        "march_in_offset_minutes": march_in_offset,
        "apparatus_set": [{"apparatus": slot["apparatus"],
                           "flight_count": slot["flight_count"]}
                          for slot in apparatus_set],
        "state": "SCHEDULED",
        "closed_at": None,
    })
    DB.sessions[s["id"]] = s
    return ok_object(ser_session(s), 201)


@bp.get("/api/v1/meets/<mid>/sessions")
def list_sessions(mid):
    authorize(SESSION_READ)
    get_or_404(DB.meets, mid, "Meet")
    items = apply_filters(
        sort_items(s for s in DB.sessions.values() if s["meet_id"] == mid),
        {"level_band": ("str", "level_band"), "state": ("str", "state")})
    return ok_list([ser_session(s) for s in items])


@bp.get("/api/v1/sessions/<sid>")
def get_session(sid):
    authorize(SESSION_READ)
    return ok_object(ser_session(get_or_404(DB.sessions, sid, "Session")))


@bp.post("/api/v1/sessions/<sid>/close")
def close_session(sid):
    authorize(["MeetDirector"])
    session = get_or_404(DB.sessions, sid, "Session")
    data = body()
    if "expected_session_version" not in data or data["expected_session_version"] is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "expected_session_version is required")
    expected = data["expected_session_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "expected_session_version must be an integer")
    if session["state"] in SESSION_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "Session is already CLOSED")
    if expected != session["version"]:
        raise ApiError("ERR_STALE_SESSION_VERSION", 412,
                       "expected_session_version does not match current version")
    if session["state"] != "SCORING":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Session state is %s, expected SCORING" % session["state"])
    scores = [sc for sc in DB.scores.values()
              if DB.entries.get(sc["athlete_entry_id"])
              and DB.entries[sc["athlete_entry_id"]]["session_id"] == sid]
    for sc in scores:
        if sc["score_state"] not in ("FINAL", "VOID"):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Score %s is not FINAL or VOID" % sc["id"])
    score_ids = {sc["id"] for sc in scores}
    for iq in DB.inquiries.values():
        if iq["score_id"] in score_ids and iq["inquiry_state"] in (
                "FILED", "UNDER_REVIEW"):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Inquiry %s is still open" % iq["id"])
    session["state"] = "CLOSED"
    session["closed_at"] = now()
    touch(session)
    run_session_close_computations(session)
    run_system_transitions()
    return ok_object(ser_session(session))


# ----------------------------------------------------------------------------
# Squads
# ----------------------------------------------------------------------------

@bp.post("/api/v1/sessions/<sid>/squads")
def create_squad(sid):
    authorize(["MeetDirector"])
    get_or_404(DB.sessions, sid, "Session")
    data = body()
    squad_label = req_str(data, "squad_label")
    starting_apparatus = req_enum(data, "starting_apparatus", APPARATUS)
    for q in DB.squads.values():
        if q["session_id"] == sid and q["squad_label"] == squad_label:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "squad_label must be unique within the session")
    q = new_entity()
    q.update({
        "session_id": sid,
        "squad_label": squad_label,
        "starting_apparatus": starting_apparatus,
        "rotation_index": 0,
    })
    DB.squads[q["id"]] = q
    return ok_object(ser_squad(q), 201)


@bp.get("/api/v1/sessions/<sid>/squads")
def list_squads(sid):
    authorize(STAFF_READ)
    get_or_404(DB.sessions, sid, "Session")
    items = sort_items(q for q in DB.squads.values() if q["session_id"] == sid)
    return ok_list([ser_squad(q) for q in items])


@bp.get("/api/v1/squads/<qid>")
def get_squad(qid):
    authorize(STAFF_READ)
    return ok_object(ser_squad(get_or_404(DB.squads, qid, "Squad")))


@bp.get("/api/v1/squads/<qid>/athlete-entries")
def list_squad_entries(qid):
    authorize(STAFF_READ)
    get_or_404(DB.squads, qid, "Squad")
    items = sort_items(e for e in DB.entries.values() if e.get("squad_id") == qid)
    return ok_list([ser_entry(e) for e in items])


@bp.post("/api/v1/sessions/<sid>/assign-squads")
def assign_squads(sid):
    authorize(["MeetDirector"])
    session = get_or_404(DB.sessions, sid, "Session")
    squads = squad_assignment(session)
    recompute_conflicts_for_session(sid)
    run_system_transitions()
    return ok_array([ser_squad(q) for q in squads])


# ----------------------------------------------------------------------------
# Gymnasts
# ----------------------------------------------------------------------------

@bp.post("/api/v1/gymnasts")
def create_gymnast():
    authorize(["MeetDirector"])
    data = body()
    number = req_str(data, "usag_member_number")
    if not RE_GYMNAST.match(number):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "usag_member_number must match ^A[0-9]{7}$")
    legal_name = req_str(data, "legal_name")
    dob = parse_dt(required(data, "date_of_birth"), "date_of_birth")
    level = req_enum(data, "competitive_level", LEVEL_BAND_SET)
    home_gym = req_str(data, "home_gym")
    for g in DB.gymnasts.values():
        if g["usag_member_number"] == number:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "usag_member_number must be globally unique")
    g = new_entity()
    g.update({
        "usag_member_number": number,
        "legal_name": legal_name,
        "date_of_birth": dob,
        "competitive_level": level,
        "home_gym": home_gym,
    })
    DB.gymnasts[g["id"]] = g
    return ok_object(ser_gymnast(g), 201)


@bp.get("/api/v1/gymnasts")
def list_gymnasts():
    authorize(["MeetDirector", "MeetReferee", "Coach"])
    items = apply_filters(sort_items(DB.gymnasts.values()),
                          {"competitive_level": ("str", "competitive_level"),
                           "home_gym": ("str", "home_gym")})
    return ok_list([ser_gymnast(g) for g in items])


@bp.get("/api/v1/gymnasts/<gid>")
def get_gymnast(gid):
    authorize(["MeetDirector", "MeetReferee", "Coach"])
    return ok_object(ser_gymnast(get_or_404(DB.gymnasts, gid, "Gymnast")))


@bp.get("/api/v1/gymnasts/<gid>/athlete-entries")
def list_gymnast_entries(gid):
    authorize(["MeetDirector", "MeetReferee", "Coach"])
    get_or_404(DB.gymnasts, gid, "Gymnast")
    items = sort_items(e for e in DB.entries.values() if e["gymnast_id"] == gid)
    return ok_list([ser_entry(e) for e in items])


# ----------------------------------------------------------------------------
# Athlete entries
# ----------------------------------------------------------------------------

@bp.post("/api/v1/sessions/<sid>/athlete-entries")
def create_entry(sid):
    authorize(["MeetDirector", "Coach"])
    session = get_or_404(DB.sessions, sid, "Session")
    data = body()
    gymnast_id = required(data, "gymnast_id")
    if not isinstance(gymnast_id, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "gymnast_id must be a string")
    gymnast = fk_or_404(DB.gymnasts, gymnast_id, "gymnast_id")
    if not level_compatible(gymnast["competitive_level"], session["level_band"]):
        raise ApiError("ERR_LEVEL_BAND_MISMATCH", 422,
                       "Gymnast level %s is incompatible with session band %s"
                       % (gymnast["competitive_level"], session["level_band"]))
    meet_id = session["meet_id"]
    for e in DB.entries.values():
        if e["gymnast_id"] != gymnast_id or e["entry_status"] == "SCRATCHED":
            continue
        other_session = DB.sessions.get(e["session_id"])
        if other_session is not None and other_session["meet_id"] == meet_id:
            raise ApiError("ERR_GYMNAST_DOUBLE_ENTERED", 409,
                           "Gymnast already has a non-SCRATCHED entry in this meet")
    e = new_entity()
    e.update({
        "session_id": sid,
        "gymnast_id": gymnast_id,
        "squad_id": None,
        "entry_status": "REGISTERED",
        "scratch_reason": None,
        "all_around_total": Decimal("0.000"),
        "all_around_rank": None,
        "qualified_for_next_meet": False,
        "qualification_mobility_score": None,
    })
    DB.entries[e["id"]] = e
    recompute_conflicts_for_session(sid)
    return ok_object(ser_entry(e), 201)


@bp.get("/api/v1/sessions/<sid>/athlete-entries")
def list_session_entries(sid):
    authorize(STAFF_READ)
    get_or_404(DB.sessions, sid, "Session")
    items = apply_filters(
        sort_items(e for e in DB.entries.values() if e["session_id"] == sid),
        {"entry_status": ("str", "entry_status"), "squad_id": ("str", "squad_id")})
    return ok_list([ser_entry(e) for e in items])


@bp.get("/api/v1/athlete-entries/<eid>")
def get_entry(eid):
    authorize(STAFF_READ)
    return ok_object(ser_entry(get_or_404(DB.entries, eid, "AthleteEntry")))


@bp.post("/api/v1/athlete-entries/<eid>/check-in")
def check_in_entry(eid):
    uid, _ = authorize(["Coach"])
    entry = get_or_404(DB.entries, eid, "AthleteEntry")
    if entry["entry_status"] in ENTRY_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", 409,
                       "AthleteEntry is in terminal state %s" % entry["entry_status"])
    if entry["entry_status"] != "REGISTERED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "AthleteEntry state is %s, expected REGISTERED"
                       % entry["entry_status"])
    session = DB.sessions.get(entry["session_id"])
    meet = DB.meets.get(session["meet_id"]) if session else None
    has_pass = any(p["coach_id"] == uid and p["meet_id"] == meet["id"]
                   and p["pass_state"] == "FLOOR_ACCESS_GRANTED"
                   for p in DB.passes.values()) if meet else False
    if not has_pass:
        raise ApiError("ERR_COACH_CREDENTIAL_LAPSED", 422,
                       "Coach does not hold floor access on this meet")
    coach = DB.coaches.get(uid)
    gymnast = DB.gymnasts.get(entry["gymnast_id"])
    if coach is None or gymnast is None \
            or coach["affiliated_gym"] != gymnast["home_gym"]:
        raise ApiError("ERR_UNAUTHORIZED_ROLE", 403,
                       "Coach gym does not match gymnast home_gym")
    entry["entry_status"] = "CHECKED_IN"
    touch(entry)
    run_system_transitions()
    return ok_object(ser_entry(entry))


@bp.post("/api/v1/athlete-entries/<eid>/scratch")
def scratch_entry(eid):
    authorize(["Coach", "MeetDirector"])
    entry = get_or_404(DB.entries, eid, "AthleteEntry")
    data = body()
    reason = req_enum(data, "scratch_reason",
                      {"INJURY", "COACH_DECISION", "NO_SHOW", "DISQUALIFICATION"})
    if entry["entry_status"] in ENTRY_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", 409,
                       "AthleteEntry is in terminal state %s" % entry["entry_status"])
    if entry["entry_status"] not in ("REGISTERED", "CHECKED_IN", "COMPETING"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "AthleteEntry cannot be scratched from %s"
                       % entry["entry_status"])
    pre_competition = entry["entry_status"] in ("REGISTERED", "CHECKED_IN")
    for sc in DB.scores.values():
        if sc["athlete_entry_id"] == eid and sc["score_state"] == "DRAFT":
            sc["score_state"] = "VOID"
            touch(sc)
    entry["entry_status"] = "SCRATCHED"
    entry["scratch_reason"] = reason
    touch(entry)
    if pre_competition:
        recompute_conflicts_for_session(entry["session_id"])
    run_system_transitions()
    return ok_object(ser_entry(entry))
