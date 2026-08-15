"""EvaluationSession planning, window gating, lock/analyze cascade,
cancel and makeup lineage (PRD §3.5)."""
import math
from datetime import timedelta

import clock
import db
from auth import require_roles, ALL_ROLES
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STUDY_STATE,
    ERR_ARM_STUDY_MISMATCH, ERR_TIME_POINT_STUDY_MISMATCH,
    ERR_SESSION_EXISTS, ERR_INVALID_SESSION_STATE, ERR_NO_PULLED_SAMPLES,
    ERR_OUTSIDE_SESSION_WINDOW, ERR_SESSION_UNDER_QUORUM,
)
from flask import Blueprint, request
from response import respond, respond_list
from services import (
    ser_session, sessions_of_tp, submitted_assignments,
    required_panelist_count, overall_mean_of,
    recompute_provisional_for_session, recompute_final_for_session,
    recompute_arm_failure, cancel_session, PANEL_SD, Z_ALPHA,
)
from util import body, paginate, req_dt, req_str, sort_created, touch

bp = Blueprint("sessions", __name__)


def get_session(session_id):
    s = db.store["sessions"].get(session_id)
    if s is None:
        raise_err(ERR_NOT_FOUND, f"EvaluationSession {session_id} not found")
    return s


def _live_session_exists(time_point_id, arm_id):
    return any(
        s["time_point_id"] == time_point_id and s["arm_id"] == arm_id
        and s["status"] != "CANCELLED"
        for s in db.store["sessions"].values())


def _new_session(study_id, time_point_id, arm_id, start, end, makeup_of_id):
    study = db.store["studies"][study_id]
    now = clock.now()
    session = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "study_id": study_id,
        "time_point_id": time_point_id,
        "arm_id": arm_id,
        "scheduled_start_utc": start,
        "scheduled_end_utc": end,
        "makeup_of_id": makeup_of_id,
        "required_panelist_count": required_panelist_count(study),
        "overall_mean": None,
        "significance_delta": None,
        "sensory_failed": False,
        "status": "PLANNED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.store["sessions"][session["id"]] = session
    return session


@bp.route("/evaluation-sessions", methods=["POST"])
@require_roles("PanelCoordinator")
def create_session():
    b = body()
    study_id = req_str(b, "study_id")
    time_point_id = req_str(b, "time_point_id")
    arm_id = req_str(b, "arm_id")
    start = req_dt(b, "scheduled_start_utc")
    end = req_dt(b, "scheduled_end_utc")
    study = db.store["studies"].get(study_id)
    if study is None:
        raise_err(ERR_NOT_FOUND, f"Study {study_id} not found")
    tp = db.store["time_points"].get(time_point_id)
    if tp is None:
        raise_err(ERR_NOT_FOUND, f"SamplingTimePoint {time_point_id} "
                                 f"not found")
    arm = db.store["arms"].get(arm_id)
    if arm is None:
        raise_err(ERR_NOT_FOUND, f"StudyArm {arm_id} not found")
    # Order per PRD §3.5: study state, referential belonging, end>start,
    # live-session uniqueness.
    if study["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise_err(ERR_INVALID_STUDY_STATE,
                  "sessions may be planned only while the study is "
                  "SCHEDULED or IN_PROGRESS")
    if arm["study_id"] != study_id:
        raise_err(ERR_ARM_STUDY_MISMATCH,
                  "arm_id does not belong to the study")
    if tp["study_id"] != study_id:
        raise_err(ERR_TIME_POINT_STUDY_MISMATCH,
                  "time_point_id does not belong to the study")
    if not (end > start):
        raise_err(ERR_INVALID_REQUEST,
                  "scheduled_end_utc must be strictly after "
                  "scheduled_start_utc")
    if _live_session_exists(time_point_id, arm_id):
        raise_err(ERR_SESSION_EXISTS,
                  "a non-CANCELLED session already exists for this "
                  "(time_point_id, arm_id)")
    session = _new_session(study_id, time_point_id, arm_id, start, end, None)
    return respond(ser_session(session), 201)


@bp.route("/evaluation-sessions", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_sessions():
    items = sort_created(db.store["sessions"].values())
    for field in ("study_id", "time_point_id", "arm_id", "status",
                  "makeup_of_id"):
        v = request.args.get(field)
        if v is not None:
            items = [s for s in items if s[field] == v]
    page, pagination = paginate(items)
    return respond_list([ser_session(s) for s in page], pagination)


@bp.route("/evaluation-sessions/<session_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_one_session(session_id):
    return respond(ser_session(get_session(session_id)), 200)


@bp.route("/evaluation-sessions/<session_id>/open", methods=["POST"])
@require_roles("PanelCoordinator")
def open_session(session_id):
    session = get_session(session_id)
    if session["status"] != "PLANNED":
        raise_err(ERR_INVALID_SESSION_STATE, "open requires status PLANNED")
    study = db.store["studies"][session["study_id"]]
    if study["status"] != "IN_PROGRESS":
        raise_err(ERR_INVALID_STUDY_STATE,
                  "open requires the study to be IN_PROGRESS")
    pulled = any(
        u["time_point_id"] == session["time_point_id"]
        and u["arm_id"] == session["arm_id"]
        for u in db.store["sample_units"].values())
    if not pulled:
        raise_err(ERR_NO_PULLED_SAMPLES,
                  "no sample units have been pulled for this "
                  "(time_point_id, arm_id)")
    now = clock.now()
    if not (session["scheduled_start_utc"] - timedelta(minutes=30) <= now
            <= session["scheduled_end_utc"]):
        raise_err(ERR_OUTSIDE_SESSION_WINDOW,
                  "logical clock is outside [start - 30min, end]")
    session["status"] = "OPEN"
    touch(session)
    return respond(ser_session(session), 200)


@bp.route("/evaluation-sessions/<session_id>/lock", methods=["POST"])
@require_roles("PanelCoordinator")
def lock_session(session_id):
    session = get_session(session_id)
    if session["status"] != "OPEN":
        raise_err(ERR_INVALID_SESSION_STATE, "lock requires status OPEN")
    submitted = submitted_assignments(session_id)
    if len(submitted) < session["required_panelist_count"]:
        raise_err(ERR_SESSION_UNDER_QUORUM,
                  "SUBMITTED assignments are below required_panelist_count")
    study = db.store["studies"][session["study_id"]]
    n_arm = len(submitted)
    mean_arm = overall_mean_of(session)
    session["overall_mean"] = mean_arm
    session["status"] = "LOCKED"
    # Significance screened against the control session for the same time
    # point (PRD §3.5); the control may be this session itself.
    control = None
    for other in sort_created(sessions_of_tp(session["time_point_id"])):
        if other["status"] == "CANCELLED":
            continue
        other_arm = db.store["arms"][other["arm_id"]]
        if other_arm["is_control"]:
            control = other
            break
    significant = False
    delta = None
    if control is not None and control["status"] in ("LOCKED", "ANALYZED"):
        n_ctrl = len(submitted_assignments(control["id"]))
        mean_ctrl = control["overall_mean"]
        if n_ctrl > 0 and mean_ctrl is not None:
            delta = Z_ALPHA * PANEL_SD * math.sqrt(1 / n_arm + 1 / n_ctrl)
            significant = abs(mean_arm - mean_ctrl) >= delta
    session["significance_delta"] = delta
    session["sensory_failed"] = bool(
        mean_arm <= study["sensory_fail_threshold"] and significant)
    touch(session)
    # Provisional consistency recompute for every SUBMITTED panelist.
    recompute_provisional_for_session(session)
    # Failure-day cascade (no-op unless the arm's earliest endpoint moved).
    arm = db.store["arms"][session["arm_id"]]
    recompute_arm_failure(arm)
    return respond(ser_session(session), 200)


@bp.route("/evaluation-sessions/<session_id>/analyze", methods=["POST"])
@require_roles("SensoryScientist")
def analyze_session(session_id):
    session = get_session(session_id)
    if session["status"] != "LOCKED":
        raise_err(ERR_INVALID_SESSION_STATE,
                  "analyze requires status LOCKED")
    session["status"] = "ANALYZED"
    touch(session)
    recompute_final_for_session(session)
    # Time-point bubble-up: PULLED -> EVALUATED when every non-CANCELLED
    # session of the point is ANALYZED and at least one is (PRD §3.5).
    tp = db.store["time_points"][session["time_point_id"]]
    if tp["status"] == "PULLED":
        siblings = [s for s in sessions_of_tp(tp["id"])
                    if s["status"] != "CANCELLED"]
        if siblings and all(s["status"] == "ANALYZED" for s in siblings):
            tp["status"] = "EVALUATED"
            touch(tp)
    return respond(ser_session(session), 200)


@bp.route("/evaluation-sessions/<session_id>/cancel", methods=["POST"])
@require_roles("PanelCoordinator")
def cancel(session_id):
    session = get_session(session_id)
    if session["status"] not in ("PLANNED", "OPEN"):
        raise_err(ERR_INVALID_SESSION_STATE,
                  "cancel requires status PLANNED or OPEN")
    cancel_session(session)
    return respond(ser_session(session), 200)


@bp.route("/evaluation-sessions/<session_id>/schedule-makeup",
          methods=["POST"])
@require_roles("PanelCoordinator")
def schedule_makeup(session_id):
    source = get_session(session_id)
    b = body()
    start = req_dt(b, "scheduled_start_utc")
    end = req_dt(b, "scheduled_end_utc")
    if source["status"] != "CANCELLED":
        raise_err(ERR_INVALID_SESSION_STATE,
                  "schedule-makeup requires the source session to be "
                  "CANCELLED")
    if not (end > start):
        raise_err(ERR_INVALID_REQUEST,
                  "scheduled_end_utc must be strictly after "
                  "scheduled_start_utc")
    # The CANCELLED source does not block its own makeup; a live sibling
    # for the same pairing still would (PRD §3.5).
    if _live_session_exists(source["time_point_id"], source["arm_id"]):
        raise_err(ERR_SESSION_EXISTS,
                  "a non-CANCELLED session already exists for this "
                  "(time_point_id, arm_id)")
    session = _new_session(source["study_id"], source["time_point_id"],
                           source["arm_id"], start, end, source["id"])
    return respond(ser_session(session), 201)
