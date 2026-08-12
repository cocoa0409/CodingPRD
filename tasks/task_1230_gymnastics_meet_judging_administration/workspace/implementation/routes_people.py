"""Routes: coaches, coach meet passes, judges, judge panels, panel assignments."""
from flask import Blueprint

from common import (APPARATUS, ApiError, DB, RATINGS, RE_COACH, RE_JUDGE,
                    SUSPENSION_REASONS, apply_filters, authorize, body,
                    fk_or_404, get_or_404, new_entity, now, ok_array, ok_list,
                    ok_object, parse_dt, req_enum, req_str, required,
                    sort_items, touch)
from logic import (compute_conflict, expire_inquiry, judge_panel_selector,
                   recompute_panel, run_system_transitions)
from serialize import (ser_assignment, ser_coach, ser_judge, ser_panel,
                       ser_pass)

bp = Blueprint("people", __name__)

PASS_TERMINAL = ("REVOKED",)
ASSIGNMENT_TERMINAL = ("RELEASED",)


# ----------------------------------------------------------------------------
# Coaches
# ----------------------------------------------------------------------------

@bp.post("/api/v1/coaches")
def create_coach():
    authorize(["MeetDirector"])
    data = body()
    number = req_str(data, "usag_coach_number")
    if not RE_COACH.match(number):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "usag_coach_number must match ^C[0-9]{7}$")
    legal_name = req_str(data, "legal_name")
    affiliated_gym = req_str(data, "affiliated_gym")
    bg = parse_dt(required(data, "background_check_expiry"),
                  "background_check_expiry")
    safety = parse_dt(required(data, "safety_cert_expiry"), "safety_cert_expiry")
    for c in DB.coaches.values():
        if c["usag_coach_number"] == number:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "usag_coach_number must be globally unique")
    c = new_entity()
    c.update({
        "usag_coach_number": number,
        "legal_name": legal_name,
        "affiliated_gym": affiliated_gym,
        "background_check_expiry": bg,
        "safety_cert_expiry": safety,
        "credential_state": "PENDING_VERIFICATION",
    })
    DB.coaches[c["id"]] = c
    return ok_object(ser_coach(c), 201)


@bp.get("/api/v1/coaches")
def list_coaches():
    authorize(["MeetDirector", "MeetReferee"])
    items = apply_filters(sort_items(DB.coaches.values()),
                          {"credential_state": ("str", "credential_state"),
                           "affiliated_gym": ("str", "affiliated_gym")})
    return ok_list([ser_coach(c) for c in items])


@bp.get("/api/v1/coaches/<cid>")
def get_coach(cid):
    authorize(["MeetDirector", "MeetReferee", "Coach"])
    return ok_object(ser_coach(get_or_404(DB.coaches, cid, "Coach")))


@bp.post("/api/v1/coaches/<cid>/verify")
def verify_coach(cid):
    authorize(["MeetDirector"])
    coach = get_or_404(DB.coaches, cid, "Coach")
    if coach["credential_state"] != "PENDING_VERIFICATION":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Coach credential_state is %s, expected PENDING_VERIFICATION"
                       % coach["credential_state"])
    coach["credential_state"] = "CREDENTIALED"
    touch(coach)
    return ok_object(ser_coach(coach))


# ----------------------------------------------------------------------------
# Coach meet passes
# ----------------------------------------------------------------------------

@bp.post("/api/v1/meets/<mid>/coach-meet-passes")
def create_pass(mid):
    authorize(["MeetDirector"])
    get_or_404(DB.meets, mid, "Meet")
    data = body()
    coach_id = required(data, "coach_id")
    if not isinstance(coach_id, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "coach_id must be a string")
    fk_or_404(DB.coaches, coach_id, "coach_id")
    p = new_entity()
    p.update({
        "meet_id": mid,
        "coach_id": coach_id,
        "pass_state": "ISSUED",
        "issued_at": now(),
        "floor_access_granted_at": None,
        "suspension_reason": None,
    })
    DB.passes[p["id"]] = p
    return ok_object(ser_pass(p), 201)


@bp.get("/api/v1/meets/<mid>/coach-meet-passes")
def list_meet_passes(mid):
    authorize(["MeetDirector", "MeetReferee"])
    get_or_404(DB.meets, mid, "Meet")
    items = apply_filters(
        sort_items(p for p in DB.passes.values() if p["meet_id"] == mid),
        {"pass_state": ("str", "pass_state")})
    return ok_list([ser_pass(p) for p in items])


@bp.get("/api/v1/coaches/<cid>/coach-meet-passes")
def list_coach_passes(cid):
    authorize(["MeetDirector", "MeetReferee", "Coach"])
    get_or_404(DB.coaches, cid, "Coach")
    items = sort_items(p for p in DB.passes.values() if p["coach_id"] == cid)
    return ok_list([ser_pass(p) for p in items])


@bp.get("/api/v1/coach-meet-passes/<pid>")
def get_pass(pid):
    authorize(["MeetDirector", "MeetReferee", "Coach"])
    return ok_object(ser_pass(get_or_404(DB.passes, pid, "CoachMeetPass")))


def _expire_coach_inquiries(coach_id, meet_id):
    for iq in DB.inquiries.values():
        if iq["filed_by_coach_id"] != coach_id or iq["inquiry_state"] != "FILED":
            continue
        score = DB.scores.get(iq["score_id"])
        if score is None:
            continue
        entry = DB.entries.get(score["athlete_entry_id"])
        session = DB.sessions.get(entry["session_id"]) if entry else None
        if session is not None and session["meet_id"] == meet_id:
            expire_inquiry(iq)


@bp.post("/api/v1/coach-meet-passes/<pid>/grant-floor-access")
def grant_floor_access(pid):
    authorize(["MeetDirector"])
    p = get_or_404(DB.passes, pid, "CoachMeetPass")
    if p["pass_state"] in PASS_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "Pass is REVOKED")
    if p["pass_state"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Pass state is %s, expected ISSUED" % p["pass_state"])
    coach = DB.coaches.get(p["coach_id"])
    if coach is None or coach["credential_state"] != "CREDENTIALED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Coach credential_state is not CREDENTIALED")
    if not (coach["background_check_expiry"] > now()
            and coach["safety_cert_expiry"] > now()):
        raise ApiError("ERR_COACH_CREDENTIAL_LAPSED", 422,
                       "Coach background check or safety cert has lapsed")
    p["pass_state"] = "FLOOR_ACCESS_GRANTED"
    p["floor_access_granted_at"] = now()
    touch(p)
    return ok_object(ser_pass(p))


@bp.post("/api/v1/coach-meet-passes/<pid>/suspend")
def suspend_pass(pid):
    authorize(["MeetDirector"])
    p = get_or_404(DB.passes, pid, "CoachMeetPass")
    data = body()
    reason = req_enum(data, "suspension_reason", SUSPENSION_REASONS)
    if p["pass_state"] in PASS_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "Pass is REVOKED")
    if p["pass_state"] != "FLOOR_ACCESS_GRANTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Pass state is %s, expected FLOOR_ACCESS_GRANTED"
                       % p["pass_state"])
    p["pass_state"] = "FLOOR_ACCESS_SUSPENDED"
    p["suspension_reason"] = reason
    touch(p)
    _expire_coach_inquiries(p["coach_id"], p["meet_id"])
    return ok_object(ser_pass(p))


@bp.post("/api/v1/coach-meet-passes/<pid>/reinstate")
def reinstate_pass(pid):
    authorize(["MeetDirector"])
    p = get_or_404(DB.passes, pid, "CoachMeetPass")
    if p["pass_state"] in PASS_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "Pass is REVOKED")
    if p["pass_state"] != "FLOOR_ACCESS_SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Pass state is %s, expected FLOOR_ACCESS_SUSPENDED"
                       % p["pass_state"])
    coach = DB.coaches.get(p["coach_id"])
    if coach is None or not (coach["background_check_expiry"] > now()
                             and coach["safety_cert_expiry"] > now()):
        raise ApiError("ERR_COACH_CREDENTIAL_LAPSED", 422,
                       "Coach background check or safety cert has lapsed")
    p["pass_state"] = "FLOOR_ACCESS_GRANTED"
    touch(p)
    return ok_object(ser_pass(p))


@bp.post("/api/v1/coach-meet-passes/<pid>/revoke")
def revoke_pass(pid):
    authorize(["MeetDirector"])
    p = get_or_404(DB.passes, pid, "CoachMeetPass")
    if p["pass_state"] in PASS_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "Pass is REVOKED")
    if p["pass_state"] not in ("ISSUED", "FLOOR_ACCESS_GRANTED",
                               "FLOOR_ACCESS_SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Pass cannot be revoked from %s" % p["pass_state"])
    p["pass_state"] = "REVOKED"
    touch(p)
    _expire_coach_inquiries(p["coach_id"], p["meet_id"])
    return ok_object(ser_pass(p))


# ----------------------------------------------------------------------------
# Judges
# ----------------------------------------------------------------------------

@bp.post("/api/v1/judges")
def create_judge():
    authorize(["MeetReferee"])
    data = body()
    number = req_str(data, "usag_judge_number")
    if not RE_JUDGE.match(number):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "usag_judge_number must match ^J[0-9]{7}$")
    legal_name = req_str(data, "legal_name")
    rating = req_enum(data, "rating", RATINGS)
    affiliated_gym = req_str(data, "affiliated_gym")
    avail_start = parse_dt(required(data, "availability_start"),
                           "availability_start")
    avail_end = parse_dt(required(data, "availability_end"), "availability_end")
    if avail_end <= avail_start:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "availability_end must be after availability_start")
    for j in DB.judges.values():
        if j["usag_judge_number"] == number:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "usag_judge_number must be globally unique")
    j = new_entity()
    j.update({
        "usag_judge_number": number,
        "legal_name": legal_name,
        "rating": rating,
        "affiliated_gym": affiliated_gym,
        "availability_start": avail_start,
        "availability_end": avail_end,
    })
    DB.judges[j["id"]] = j
    return ok_object(ser_judge(j), 201)


@bp.get("/api/v1/judges")
def list_judges():
    authorize(["MeetDirector", "MeetReferee"])
    items = apply_filters(sort_items(DB.judges.values()),
                          {"rating": ("str", "rating"),
                           "affiliated_gym": ("str", "affiliated_gym")})
    return ok_list([ser_judge(j) for j in items])


@bp.get("/api/v1/judges/<jid>")
def get_judge(jid):
    authorize(["MeetDirector", "MeetReferee"])
    return ok_object(ser_judge(get_or_404(DB.judges, jid, "Judge")))


@bp.get("/api/v1/judges/<jid>/panel-assignments")
def list_judge_assignments(jid):
    authorize(["MeetDirector", "MeetReferee"])
    get_or_404(DB.judges, jid, "Judge")
    items = sort_items(a for a in DB.assignments.values() if a["judge_id"] == jid)
    return ok_list([ser_assignment(a) for a in items])


# ----------------------------------------------------------------------------
# Judge panels
# ----------------------------------------------------------------------------

@bp.post("/api/v1/sessions/<sid>/judge-panels")
def create_panel(sid):
    authorize(["MeetReferee"])
    session = get_or_404(DB.sessions, sid, "Session")
    data = body()
    meet_id = required(data, "meet_id")
    if not isinstance(meet_id, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "meet_id must be a string")
    fk_or_404(DB.meets, meet_id, "meet_id")
    if meet_id != session["meet_id"]:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "meet_id does not match the session's meet")
    apparatus = req_enum(data, "apparatus", APPARATUS)
    required_count = 4 if apparatus in ("BALANCE_BEAM", "FLOOR_EXERCISE") else 2
    p = new_entity()
    p.update({
        "meet_id": meet_id,
        "session_id": sid,
        "apparatus": apparatus,
        "panel_state": "FORMING",
        "required_judge_count": required_count,
    })
    DB.panels[p["id"]] = p
    return ok_object(ser_panel(p), 201)


@bp.get("/api/v1/sessions/<sid>/judge-panels")
def list_session_panels(sid):
    authorize(["MeetDirector", "MeetReferee", "JudgePanelChief"])
    get_or_404(DB.sessions, sid, "Session")
    items = apply_filters(
        sort_items(p for p in DB.panels.values() if p["session_id"] == sid),
        {"apparatus": ("str", "apparatus"), "panel_state": ("str", "panel_state")})
    return ok_list([ser_panel(p) for p in items])


@bp.get("/api/v1/meets/<mid>/judge-panels")
def list_meet_panels(mid):
    authorize(["MeetDirector", "MeetReferee", "JudgePanelChief"])
    get_or_404(DB.meets, mid, "Meet")
    items = sort_items(p for p in DB.panels.values() if p["meet_id"] == mid)
    return ok_list([ser_panel(p) for p in items])


@bp.get("/api/v1/judge-panels/<pid>")
def get_panel(pid):
    authorize(["MeetDirector", "MeetReferee", "JudgePanelChief"])
    return ok_object(ser_panel(get_or_404(DB.panels, pid, "JudgePanel")))


@bp.post("/api/v1/judge-panels/<pid>/auto-assign")
def auto_assign_panel(pid):
    authorize(["MeetReferee"])
    panel = get_or_404(DB.panels, pid, "JudgePanel")
    if any(a["judge_panel_id"] == pid and a["assignment_state"]
           in ("PROPOSED", "CONFIRMED") for a in DB.assignments.values()):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Panel already has proposed or confirmed assignments")
    created = judge_panel_selector(panel)
    return ok_array([ser_assignment(a) for a in created])


# ----------------------------------------------------------------------------
# Panel assignments
# ----------------------------------------------------------------------------

@bp.get("/api/v1/judge-panels/<pid>/assignments")
def list_panel_assignments(pid):
    authorize(["MeetDirector", "MeetReferee", "JudgePanelChief"])
    get_or_404(DB.panels, pid, "JudgePanel")
    items = apply_filters(
        sort_items(a for a in DB.assignments.values()
                   if a["judge_panel_id"] == pid),
        {"assignment_state": ("str", "assignment_state")})
    return ok_list([ser_assignment(a) for a in items])


@bp.get("/api/v1/panel-assignments/<aid>")
def get_assignment(aid):
    authorize(["MeetDirector", "MeetReferee", "JudgePanelChief"])
    return ok_object(ser_assignment(
        get_or_404(DB.assignments, aid, "PanelAssignment")))


@bp.post("/api/v1/panel-assignments/<aid>/confirm")
def confirm_assignment(aid):
    authorize(["MeetReferee"])
    a = get_or_404(DB.assignments, aid, "PanelAssignment")
    if a["assignment_state"] in ASSIGNMENT_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "Assignment is RELEASED")
    if a["assignment_state"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Assignment state is %s, expected PROPOSED"
                       % a["assignment_state"])
    if compute_conflict(a):
        a["conflict_flag"] = True
        raise ApiError("ERR_JUDGE_CONFLICT_OF_INTEREST", 422,
                       "Judge affiliated_gym conflicts with a gymnast home_gym")
    judge = DB.judges.get(a["judge_id"])
    panel = DB.panels.get(a["judge_panel_id"])
    session = DB.sessions.get(panel["session_id"]) if panel else None
    if judge is None or session is None or not (
            judge["availability_start"] <= session["scheduled_start"]
            and judge["availability_end"] >= session["scheduled_end"]):
        raise ApiError("ERR_JUDGE_UNAVAILABLE", 422,
                       "Judge availability does not cover the session interval")
    a["assignment_state"] = "CONFIRMED"
    touch(a)
    if panel is not None:
        recompute_panel(panel)
    return ok_object(ser_assignment(a))


@bp.post("/api/v1/panel-assignments/<aid>/recuse")
def recuse_assignment(aid):
    authorize(["MeetReferee"])
    a = get_or_404(DB.assignments, aid, "PanelAssignment")
    if a["assignment_state"] in ASSIGNMENT_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "Assignment is RELEASED")
    if a["assignment_state"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Assignment state is %s, expected CONFIRMED"
                       % a["assignment_state"])
    a["assignment_state"] = "RECUSED"
    a["conflict_flag"] = False
    touch(a)
    panel = DB.panels.get(a["judge_panel_id"])
    if panel is not None:
        recompute_panel(panel)
    return ok_object(ser_assignment(a))


@bp.post("/api/v1/panel-assignments/<aid>/release")
def release_assignment(aid):
    authorize(["MeetReferee"])
    a = get_or_404(DB.assignments, aid, "PanelAssignment")
    if a["assignment_state"] in ASSIGNMENT_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "Assignment is RELEASED")
    if a["assignment_state"] not in ("RECUSED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Assignment cannot be released from %s"
                       % a["assignment_state"])
    a["assignment_state"] = "RELEASED"
    touch(a)
    return ok_object(ser_assignment(a))
