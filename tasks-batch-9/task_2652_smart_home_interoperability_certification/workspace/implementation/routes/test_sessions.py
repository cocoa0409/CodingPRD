"""Test sessions: booking, execution, results and disputes (PRD 3.6)."""

from datetime import timedelta

from flask import Blueprint

import calc
import cascade
import common as C
import enums as E
import middleware as M
import queries as Q
import shape as S
from db import new_row, now, ordered, set_fields, store, touch
from errors import ApiError
from response import list_response, object_response
from serial import public, public_list

bp = Blueprint("test_sessions", __name__)

SESSION_READ_ROLES = [M.PROGRAM_ADMIN, M.MEMBER, M.TEST_LABORATORY,
                      M.CONFORMANCE_REVIEWER, M.SECURITY_REVIEWER]
BUFFER = timedelta(minutes=E.BENCH_CHANGEOVER_MINUTES)


def _on_minute(value):
    return value.second == 0 and value.microsecond == 0


@bp.post("/test-sessions")
def create_test_session():
    M.auth([M.PROGRAM_ADMIN, M.TEST_LABORATORY])
    body = S.body_obj()
    # rung 5
    plan = C.body_fk("test_plan", body, "test_plan_id")
    lab = C.body_fk("laboratory", body, "laboratory_id")
    # rung 6
    S.req_str(body, "test_plan_id")
    S.req_str(body, "laboratory_id")
    bench_index = S.req_int(body, "bench_index", 1, lab["bench_capacity"])
    window_start = S.req_dt(body, "window_start")
    window_end = S.req_dt(body, "window_end")
    session_type = S.req_str(body, "session_type")
    # rung 7
    S.check_enum(session_type, E.SESSION_TYPES, "session_type")
    # rung 8
    if not window_end > window_start or not _on_minute(window_start) or not _on_minute(window_end):
        raise ApiError("ERR_INVALID_WINDOW_BOUNDS",
                       "window_end must be after window_start and both must fall on a minute boundary")
    # rung 15
    if lab["accreditation_status"] != "AUTHORIZED":
        raise ApiError("ERR_INVALID_LABORATORY_STATE", "booking requires an AUTHORIZED laboratory")
    # rung 18
    if plan["state"] == "VOIDED":
        raise ApiError("ERR_INVALID_TEST_PLAN_STATE", "a VOIDED plan cannot be booked")
    # rung 29
    if not lab["accreditation_expires_at"] > now():
        raise ApiError("ERR_ACCREDITATION_EXPIRED", "accreditation has expired")
    # rung 30
    if plan["device_type"] not in lab["authorized_device_types"]:
        raise ApiError("ERR_DEVICE_TYPE_NOT_AUTHORIZED",
                       "the laboratory is not authorized for %s" % plan["device_type"])
    # rung 34 -- the session's own declared device class must agree with the plan's
    declared_device_type = body.get("device_type")
    if isinstance(declared_device_type, str) and declared_device_type != plan["device_type"]:
        raise ApiError("ERR_DEVICE_TYPE_MISMATCH",
                       "the session device class disagrees with the test plan's device_type")
    # rung 38 -- bench occupancy with a 60-minute changeover buffer on both sides
    for other in Q.sessions_for_lab(lab["id"]):
        if other["state"] not in cascade.LIVE_SESSION_STATES:
            continue
        if other["bench_index"] != bench_index:
            continue
        if (window_start - BUFFER) < other["window_end"] and (window_end + BUFFER) > other["window_start"]:
            raise ApiError("ERR_BENCH_WINDOW_CONFLICT", "the bench window conflicts with another session")
    # rung 49 -- capacity ceiling
    reserved_minutes = calc.session_minutes(window_start, window_end)
    ceiling = lab["bench_capacity"] * E.MINUTES_PER_BENCH_PER_CYCLE
    if lab["reserved_bench_minutes"] + reserved_minutes > ceiling:
        raise ApiError("ERR_LAB_CAPACITY_EXCEEDED", "the laboratory capacity ceiling is exceeded")

    session = new_row(
        test_plan_id=plan["id"],
        laboratory_id=lab["id"],
        bench_index=bench_index,
        window_start=window_start,
        window_end=window_end,
        session_type=session_type,
        state="SCHEDULED",
        started_at=None,
        completed_at=None,
        completed_late=False,
        result_lines=[],
        disputed_line_count=0,
        reserved_minutes=reserved_minutes,
    )
    store.test_sessions[session["id"]] = session
    cascade.recompute_lab_minutes(lab)
    return object_response(public(session), 201)


@bp.get("/test-sessions/<test_session_id>")
def get_test_session(test_session_id):
    M.auth(SESSION_READ_ROLES)
    return object_response(public(C.must("test_session", test_session_id)), 200)


@bp.get("/test-sessions")
def list_test_sessions():
    M.auth(SESSION_READ_ROLES)
    limit, offset = S.paging()
    test_plan_id = S.q_str("test_plan_id")
    laboratory_id = S.q_str("laboratory_id")
    state = S.q_str("state")
    session_type = S.q_enum("session_type", E.SESSION_TYPES)
    rows = ordered(store.test_sessions.values())
    if test_plan_id is not None:
        rows = [r for r in rows if r["test_plan_id"] == test_plan_id]
    if laboratory_id is not None:
        rows = [r for r in rows if r["laboratory_id"] == laboratory_id]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    if session_type is not None:
        rows = [r for r in rows if r["session_type"] == session_type]
    page, total = C.paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)


@bp.post("/test-sessions/<test_session_id>/start")
def start_test_session(test_session_id):
    user_id, _ = M.auth([M.TEST_LABORATORY])
    session = C.must("test_session", test_session_id)
    M.own(user_id, session["laboratory_id"])
    lab = store.laboratories[session["laboratory_id"]]
    plan = store.test_plans[session["test_plan_id"]]
    # rung 15
    if lab["accreditation_status"] != "AUTHORIZED":
        raise ApiError("ERR_INVALID_LABORATORY_STATE", "starting requires an AUTHORIZED laboratory")
    # rung 18
    if plan["state"] not in ("ISSUED", "IN_EXECUTION"):
        raise ApiError("ERR_INVALID_TEST_PLAN_STATE",
                       "the parent plan must be ISSUED or IN_EXECUTION")
    # rung 19
    if session["state"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_SESSION_STATE", "a session starts from SCHEDULED")
    # rung 29
    if not lab["accreditation_expires_at"] > now():
        raise ApiError("ERR_ACCREDITATION_EXPIRED", "accreditation has expired")

    set_fields(session, state="IN_PROGRESS", started_at=now())
    if plan["state"] == "ISSUED":
        set_fields(plan, state="IN_EXECUTION")
    cascade.recompute_lab_minutes(lab)
    return object_response(public(session), 200)


@bp.post("/test-sessions/<test_session_id>/results")
def record_results(test_session_id):
    user_id, _ = M.auth([M.TEST_LABORATORY])
    session = C.must("test_session", test_session_id)
    M.own(user_id, session["laboratory_id"])
    body = S.body_obj()
    # rung 6
    lines = body.get("result_lines")
    if lines is None:
        S.bad("result_lines is required")
    if not isinstance(lines, list) or not lines:
        S.bad("result_lines must be a non-empty array")
    for line in lines:
        if not isinstance(line, dict):
            S.bad("every result line must be an object")
        for key in ("feature_set_id", "outcome", "evidence_hash"):
            value = line.get(key)
            if not isinstance(value, str) or not value:
                S.bad("every result line requires a %s string" % key)
    # rung 7
    for line in lines:
        S.check_enum(line["outcome"], E.RESULT_OUTCOMES, "outcome")
    # rung 19
    if session["state"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_SESSION_STATE", "results require an IN_PROGRESS session")
    # rung 37
    plan = store.test_plans[session["test_plan_id"]]
    for line in lines:
        if line["feature_set_id"] not in plan["included_feature_set_ids"]:
            raise ApiError("ERR_UNKNOWN_RESULT_FEATURE_SET",
                           "feature_set_id %s is outside the plan" % line["feature_set_id"])

    stamp = now()
    appended = list(session["result_lines"])
    for line in lines:
        appended.append({
            "feature_set_id": line["feature_set_id"],
            "outcome": line["outcome"],
            "evidence_hash": line["evidence_hash"],
            "recorded_at": stamp,
            "disputed": False,
        })
    session["result_lines"] = appended
    touch(session)
    submission = store.submissions[plan["submission_id"]]
    cascade.refresh_provisional_readiness(submission)
    return object_response(public(session), 200)


@bp.post("/test-sessions/<test_session_id>/complete")
def complete_test_session(test_session_id):
    user_id, _ = M.auth([M.TEST_LABORATORY])
    session = C.must("test_session", test_session_id)
    M.own(user_id, session["laboratory_id"])
    # rung 19
    if session["state"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_SESSION_STATE", "completion requires an IN_PROGRESS session")
    # rung 43
    if not session["result_lines"]:
        raise ApiError("ERR_MANDATORY_COVERAGE_INCOMPLETE",
                       "a session that captured no result lines cannot be completed")

    completed_at = now()
    set_fields(session, state="COMPLETE", completed_at=completed_at,
               completed_late=completed_at > session["window_end"])
    lab = store.laboratories.get(session["laboratory_id"])
    if lab is not None:
        cascade.recompute_lab_minutes(lab)
    plan = store.test_plans[session["test_plan_id"]]
    cascade.plan_progress_after_completion(plan)
    return object_response(public(session), 200)


@bp.post("/test-sessions/<test_session_id>/cancel")
def cancel_test_session(test_session_id):
    user_id, role = M.auth([M.PROGRAM_ADMIN, M.TEST_LABORATORY])
    session = C.must("test_session", test_session_id)
    if role == M.TEST_LABORATORY:
        M.own(user_id, session["laboratory_id"])
    body = S.body_obj()
    S.opt_str(body, "reason", 1, 500)
    # rung 19
    if session["state"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise ApiError("ERR_INVALID_SESSION_STATE",
                       "cancellation is not available from %s" % session["state"])
    cascade.cancel_session(session)
    return object_response(public(session), 200)


@bp.post("/test-sessions/<test_session_id>/dispute-line")
def dispute_line(test_session_id):
    M.auth([M.PROGRAM_ADMIN, M.CONFORMANCE_REVIEWER])
    session = C.must("test_session", test_session_id)
    body = S.body_obj()
    line_index = S.req_int(body, "line_index", 0, None)
    # rung 19
    if session["state"] not in ("IN_PROGRESS", "COMPLETE"):
        raise ApiError("ERR_INVALID_SESSION_STATE",
                       "disputes require an IN_PROGRESS or COMPLETE session")
    # rung 37
    if line_index >= len(session["result_lines"]):
        raise ApiError("ERR_UNKNOWN_RESULT_FEATURE_SET", "line_index addresses no result line")

    line = session["result_lines"][line_index]
    if not line["disputed"]:
        line["disputed"] = True
        session["disputed_line_count"] = sum(
            1 for entry in session["result_lines"] if entry["disputed"])
        touch(session)
    return object_response(public(session), 200)
