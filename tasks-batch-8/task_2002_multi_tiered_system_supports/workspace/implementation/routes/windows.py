"""Screening windows, screening scores, and benchmark cut points."""

from flask import Blueprint, request

from db import DB
from errors import (
    err, ERR_WINDOW_NOT_FOUND, ERR_STUDENT_NOT_FOUND, ERR_SCHOOL_NOT_FOUND,
    ERR_INVALID_STATE, ERR_WINDOW_NOT_OPEN, ERR_CUT_POINT_NOT_DEFINED,
    ERR_INVALID_CUT_POINT, ERR_INVALID_REQUEST,
)
from middleware import (
    require_role, ALL_ROLES, get_json_body, check_unknown_fields, require_fields,
    req_string, req_int, req_enum, req_date, base_fields, base_fields_append_only,
    paginate, sort_created, parse_date,
)
from response import success_object, success_list
from services import (
    WINDOW_KINDS, SUBJECTS,
    serialize_window, serialize_score, serialize_cut_point,
    resolve_school, resolve_window, get_window_refreshed, refresh_window_status,
    find_cut_point, classify_risk_band, propose_movement,
)
from clock import today_date

bp = Blueprint("windows", __name__)


# ---------- Screening Windows ----------

@bp.post("/districts/<districtId>/schools/<schoolId>/screening-windows")
def create_window(districtId, schoolId):
    require_role("DistrictCoordinator")
    body = get_json_body()
    check_unknown_fields(body, {"window_kind", "opens_on", "closes_on"})
    require_fields(body, ["window_kind", "opens_on", "closes_on"])
    window_kind = req_enum(body, "window_kind", WINDOW_KINDS)
    opens_on = req_date(body, "opens_on")
    closes_on = req_date(body, "closes_on")
    resolve_school(districtId, schoolId)
    w = base_fields()
    w.update({
        "school_id": schoolId,
        "window_kind": window_kind,
        "opens_on": opens_on,
        "closes_on": closes_on,
        "status": "SCHEDULED",
        "_scored_seq": 0,
    })
    DB.screening_windows[w["id"]] = w
    refresh_window_status(w)
    return success_object(serialize_window(w), status=201)


@bp.get("/districts/<districtId>/schools/<schoolId>/screening-windows")
def list_windows(districtId, schoolId):
    require_role(*ALL_ROLES)
    resolve_school(districtId, schoolId)
    status_filter = request.args.get("status")
    items = []
    for w in DB.screening_windows.values():
        if w["school_id"] != schoolId:
            continue
        refresh_window_status(w)
        if status_filter is not None and w["status"] != status_filter:
            continue
        items.append(w)
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_window(w) for w in page], limit, offset, total)


@bp.get("/districts/<districtId>/schools/<schoolId>/screening-windows/<windowId>")
def get_window(districtId, schoolId, windowId):
    require_role(*ALL_ROLES)
    w = resolve_window(districtId, schoolId, windowId)
    refresh_window_status(w)
    return success_object(serialize_window(w))


@bp.post("/districts/<districtId>/schools/<schoolId>/screening-windows/<windowId>/close")
def close_window(districtId, schoolId, windowId):
    require_role("DistrictCoordinator")
    w = resolve_window(districtId, schoolId, windowId)
    refresh_window_status(w)
    if w["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, 409, "Only an OPEN window can be manually closed")
    w["status"] = "CLOSED"
    from middleware import touch
    touch(w)
    return success_object(serialize_window(w))


@bp.post("/districts/<districtId>/schools/<schoolId>/screening-windows/<windowId>/score")
def score_window(districtId, schoolId, windowId):
    require_role("DistrictCoordinator")
    w = resolve_window(districtId, schoolId, windowId)
    refresh_window_status(w)
    if w["status"] != "CLOSED":
        raise err(ERR_INVALID_STATE, 409, "Window must be CLOSED before scoring")
    # Side effect: auto-propose TierMovements for students whose latest risk_band
    # in this window is at-risk and who are still at TIER_1 (PRD §3.3).
    students_at_school = [
        st for st in DB.students.values() if st["school_id"] == schoolId
    ]
    students_at_school.sort(key=lambda st: (st["created_at"], st["_seq"]))
    for st in students_at_school:
        if st["current_tier"] != "TIER_1":
            continue
        rows = [
            sc for sc in DB.screening_scores.values()
            if sc["window_id"] == w["id"] and sc["student_id"] == st["id"]
        ]
        if not rows:
            continue
        rows.sort(key=lambda sc: (sc["created_at"], sc["_seq"]))
        band = rows[-1]["risk_band"]
        if band in ("TIER_2", "TIER_3"):
            propose_movement(st, band, "Auto-proposed from screening window scoring")
    w["status"] = "SCORED"
    w["_scored_seq"] = DB.next_seq()
    from middleware import touch
    touch(w)
    return success_object(serialize_window(w))


@bp.get("/screening-windows/<windowId>")
def get_window_flat(windowId):
    require_role(*ALL_ROLES)
    w = get_window_refreshed(windowId)
    if w is None:
        raise err(ERR_WINDOW_NOT_FOUND, 404, "windowId does not exist")
    return success_object(serialize_window(w))


@bp.get("/schools/<id>/screening-windows")
def list_windows_flat(id):
    require_role(*ALL_ROLES)
    s = DB.schools.get(id)
    if s is None:
        raise err(ERR_SCHOOL_NOT_FOUND, 404, "school id does not exist")
    status_filter = request.args.get("status")
    items = []
    for w in DB.screening_windows.values():
        if w["school_id"] != id:
            continue
        refresh_window_status(w)
        if status_filter is not None and w["status"] != status_filter:
            continue
        items.append(w)
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_window(w) for w in page], limit, offset, total)


# ---------- Screening Scores ----------

@bp.post("/districts/<districtId>/schools/<schoolId>/screening-windows/<windowId>/scores")
def create_score(districtId, schoolId, windowId):
    require_role("DistrictCoordinator", "Teacher")
    body = get_json_body()
    check_unknown_fields(body, {"student_id", "subject", "raw_score"})
    require_fields(body, ["student_id", "subject", "raw_score"])
    student_id = req_string(body, "student_id")
    subject = req_enum(body, "subject", SUBJECTS)
    raw_score = req_int(body, "raw_score")
    w = resolve_window(districtId, schoolId, windowId)
    refresh_window_status(w)
    # Body-FK existence: the scored student must exist within this school.
    student = DB.students.get(student_id)
    if student is None or student["school_id"] != schoolId:
        raise err(ERR_STUDENT_NOT_FOUND, 404, "student_id does not exist (within school)")
    # Window-open rule (business_temporal): OPEN status and clock within range.
    today = today_date()
    if (w["status"] != "OPEN"
            or not (parse_date(w["opens_on"]) <= today <= parse_date(w["closes_on"]))):
        raise err(ERR_WINDOW_NOT_OPEN, 409,
                  "ScreeningScore creation requires window OPEN and current date within [opens_on, closes_on]")
    cut = find_cut_point(schoolId, w["window_kind"], student["grade_level"], subject)
    if cut is None:
        raise err(ERR_CUT_POINT_NOT_DEFINED, 422,
                  "No BenchmarkCutPoint matches (school, window_kind, grade_level, subject)")
    sc = base_fields_append_only()
    sc.update({
        "window_id": windowId,
        "student_id": student_id,
        "subject": subject,
        "raw_score": raw_score,
        "risk_band": classify_risk_band(cut, raw_score),
    })
    DB.screening_scores[sc["id"]] = sc
    # screened_student_count is a computed field on the window; its change is a
    # mutation of the window record (PRD §2.6).
    from middleware import touch
    touch(w)
    return success_object(serialize_score(sc), status=201)


def _list_scores_for_window(windowId):
    student_filter = request.args.get("student_id")
    subject_filter = request.args.get("subject")
    items = [
        sc for sc in DB.screening_scores.values() if sc["window_id"] == windowId
    ]
    if student_filter is not None:
        items = [sc for sc in items if sc["student_id"] == student_filter]
    if subject_filter is not None:
        items = [sc for sc in items if sc["subject"] == subject_filter]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_score(sc) for sc in page], limit, offset, total)


@bp.get("/districts/<districtId>/schools/<schoolId>/screening-windows/<windowId>/scores")
def list_scores(districtId, schoolId, windowId):
    require_role(*ALL_ROLES)
    resolve_window(districtId, schoolId, windowId)
    return _list_scores_for_window(windowId)


@bp.get("/screening-windows/<id>/scores")
def list_scores_flat(id):
    require_role(*ALL_ROLES)
    w = get_window_refreshed(id)
    if w is None:
        raise err(ERR_WINDOW_NOT_FOUND, 404, "window id does not exist")
    return _list_scores_for_window(id)


@bp.get("/screening-scores/<scoreId>")
def get_score_flat(scoreId):
    require_role(*ALL_ROLES)
    sc = DB.screening_scores.get(scoreId)
    if sc is None:
        raise err(ERR_INVALID_REQUEST, 404, "scoreId does not exist")
    return success_object(serialize_score(sc))


@bp.get("/students/<id>/scores")
def list_scores_for_student_flat(id):
    require_role(*ALL_ROLES)
    st = DB.students.get(id)
    if st is None:
        raise err(ERR_STUDENT_NOT_FOUND, 404, "student id does not exist")
    items = sort_created(
        sc for sc in DB.screening_scores.values() if sc["student_id"] == id
    )
    page, limit, offset, total = paginate(items)
    return success_list([serialize_score(sc) for sc in page], limit, offset, total)


# ---------- Benchmark Cut Points ----------

@bp.post("/districts/<districtId>/schools/<schoolId>/benchmark-cut-points")
def create_cut_point(districtId, schoolId):
    require_role("DistrictCoordinator")
    body = get_json_body()
    check_unknown_fields(body, {"window_kind", "grade_level", "subject", "tier2_max_score", "tier3_max_score"})
    require_fields(body, ["window_kind", "grade_level", "subject", "tier2_max_score", "tier3_max_score"])
    window_kind = req_enum(body, "window_kind", WINDOW_KINDS)
    grade_level = req_int(body, "grade_level")
    subject = req_enum(body, "subject", SUBJECTS)
    tier2_max = req_int(body, "tier2_max_score")
    tier3_max = req_int(body, "tier3_max_score")
    resolve_school(districtId, schoolId)
    if not (tier3_max < tier2_max):
        raise err(ERR_INVALID_CUT_POINT, 400, "tier3_max_score must be strictly less than tier2_max_score")
    c = base_fields_append_only()
    c.update({
        "school_id": schoolId,
        "window_kind": window_kind,
        "grade_level": grade_level,
        "subject": subject,
        "tier2_max_score": tier2_max,
        "tier3_max_score": tier3_max,
    })
    DB.cut_points[c["id"]] = c
    return success_object(serialize_cut_point(c), status=201)


def _list_cut_points(schoolId):
    q = request.args
    items = [c for c in DB.cut_points.values() if c["school_id"] == schoolId]
    wk = q.get("window_kind")
    if wk is not None:
        items = [c for c in items if c["window_kind"] == wk]
    gl = q.get("grade_level")
    if gl is not None:
        try:
            gl_int = int(gl)
        except ValueError:
            raise err(ERR_INVALID_REQUEST, 400, "grade_level filter must be an integer")
        items = [c for c in items if c["grade_level"] == gl_int]
    subj = q.get("subject")
    if subj is not None:
        items = [c for c in items if c["subject"] == subj]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_cut_point(c) for c in page], limit, offset, total)


@bp.get("/districts/<districtId>/schools/<schoolId>/benchmark-cut-points")
def list_cut_points(districtId, schoolId):
    require_role(*ALL_ROLES)
    resolve_school(districtId, schoolId)
    return _list_cut_points(schoolId)


@bp.get("/schools/<id>/benchmark-cut-points")
def list_cut_points_flat(id):
    require_role(*ALL_ROLES)
    s = DB.schools.get(id)
    if s is None:
        raise err(ERR_SCHOOL_NOT_FOUND, 404, "school id does not exist")
    return _list_cut_points(id)


@bp.get("/benchmark-cut-points/<cutpointId>")
def get_cut_point_flat(cutpointId):
    require_role(*ALL_ROLES)
    c = DB.cut_points.get(cutpointId)
    if c is None:
        raise err(ERR_INVALID_REQUEST, 404, "cutpointId does not exist")
    return success_object(serialize_cut_point(c))
