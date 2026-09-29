"""Cold-chain readings, case failures and the halt cascade (PRD §3.7)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import errors
import middleware as mw
import validation as v
from calc import CONSECUTIVE_FAILURE_THRESHOLD, ESCALATION_MINUTES, rhu
from db import db, make, mark, now, now_iso, sort_rows
from errors import ApiError
from response import list_response, object_response
from services import case

bp = Blueprint("temperature", __name__)

DISPOSITIONS = ("NONE", "MARKDOWN", "DISCARD")

FAILURE_ACTION_ROLES = {
    "CONTAIN": (mw.MEAT_CUTTER,),
    "ESCALATE": (mw.MEAT_MANAGER,),
    "RESOLVE": (mw.MEAT_MANAGER,),
}

DECLARED_TRANSITIONS = {
    "CONTAIN": ("OPEN",),
    "ESCALATE": ("OPEN",),
    "RESOLVE": ("CONTAINED", "ESCALATED"),
}


def _contained_failure_on_case(department_id, case_code):
    rows = [row for row in db.case_failures.values()
            if row["department_id"] == department_id
            and row["case_code"] == case_code
            and row["status"] == "CONTAINED"]
    rows = sort_rows(rows)
    return rows[-1] if rows else None


@bp.route("/meat-ops/temperature-logs", methods=["POST"])
def create_temperature_log():
    user_id, _ = mw.authenticate((mw.MEAT_CUTTER, mw.SERVICE_CLERK))
    payload = v.body()

    department_id = v.field_id(payload, "department_id", required=True)
    case_code = v.field_str(payload, "case_code", required=True, min_len=1, max_len=24)
    reading_c = v.field_num(payload, "reading_c", required=True,
                            minimum=Decimal("-10.0"), maximum=Decimal("15.0"),
                            places=1)

    department = v.resolve("department", department_id)

    out_of_spec = reading_c > department["max_safe_case_temp_c"]
    if out_of_spec:
        run_length = min(department["consecutive_out_of_spec_readings"] + 1,
                         CONSECUTIVE_FAILURE_THRESHOLD)
    else:
        run_length = 0
    if department["consecutive_out_of_spec_readings"] != run_length:
        department["consecutive_out_of_spec_readings"] = run_length
        mark(department)

    log = make("TemperatureLog", {
        "department_id": department_id,
        "case_code": case_code,
        "reading_c": reading_c,
        "taken_at": now_iso(),
        "recorded_by_user_id": user_id,
        "out_of_spec": out_of_spec,
        "consecutive_index": run_length,
    }, common=False)
    db.temperature_logs[log["id"]] = log

    spike = reading_c >= department["critical_case_temp_c"]
    second_strike = run_length >= CONSECUTIVE_FAILURE_THRESHOLD

    failure = None
    if spike or second_strike:
        existing = _contained_failure_on_case(department_id, case_code)
        if existing is not None:
            existing["status"] = "OPEN"
            existing["reopen_count"] = existing["reopen_count"] + 1
            existing["peak_reading_c"] = rhu(
                max(existing["peak_reading_c"], reading_c), 1)
            mark(existing)
            department["open_case_failure_count"] += 1
            department["contained_case_failure_count"] -= 1
            mark(department)
            failure = existing
        else:
            failure = make("CaseFailure", {
                "department_id": department_id,
                "trigger_temperature_log_id": log["id"],
                "case_code": case_code,
                "opened_at": now_iso(),
                "reported_by_user_id": user_id,
                "peak_reading_c": rhu(reading_c, 1),
                "reopen_count": 0,
                "containment_note": None,
                "disposition": "NONE",
                "affected_line_count": 0,
                "contained_at": None,
                "escalated_at": None,
                "resolved_at": None,
                "resolved_by_user_id": None,
                "status": "OPEN",
                "_opened_at": now(),
            })
            db.case_failures[failure["id"]] = failure
            department["open_case_failure_count"] += 1
            mark(department)

    posture = case.recompute_posture(department)
    if failure is not None and posture == "SALES_HALTED":
        case.halt_cascade(department, failure)

    return object_response(log, 201)


@bp.route("/meat-ops/temperature-logs/<log_id>", methods=["GET"])
def get_temperature_log(log_id):
    mw.authenticate(mw.COLD_CHAIN_READERS)
    return object_response(v.resolve("temperature_log", log_id))


@bp.route("/meat-ops/departments/<department_id>/temperature-logs", methods=["GET"])
def list_department_logs(department_id):
    mw.authenticate(mw.COLD_CHAIN_READERS)
    v.resolve("department", department_id)
    limit, offset = v.pagination()
    case_code = v.query_filter("case_code")
    out_of_spec = v.query_bool("out_of_spec")
    rows = []
    for row in db.temperature_logs.values():
        if row["department_id"] != department_id:
            continue
        if case_code is not None and row["case_code"] != case_code:
            continue
        if out_of_spec is not None and row["out_of_spec"] is not out_of_spec:
            continue
        rows.append(row)
    return list_response(sort_rows(rows), limit, offset)


# --------------------------------------------------------------------------
# case failures
# --------------------------------------------------------------------------

@bp.route("/meat-ops/case-failures/<failure_id>", methods=["GET"])
def get_case_failure(failure_id):
    mw.authenticate(mw.COLD_CHAIN_READERS)
    return object_response(v.resolve("case_failure", failure_id))


@bp.route("/meat-ops/case-failures", methods=["GET"])
def list_case_failures():
    mw.authenticate(mw.COLD_CHAIN_READERS)
    limit, offset = v.pagination()
    department_id = v.query_filter("department_id")
    case_code = v.query_filter("case_code")
    status = v.query_filter("status")
    trigger_id = v.query_filter("trigger_temperature_log_id")
    rows = []
    for row in db.case_failures.values():
        if department_id is not None and row["department_id"] != department_id:
            continue
        if case_code is not None and row["case_code"] != case_code:
            continue
        if status is not None and row["status"] != status:
            continue
        if (trigger_id is not None
                and row["trigger_temperature_log_id"] != trigger_id):
            continue
        rows.append(row)
    return list_response(sort_rows(rows), limit, offset)


@bp.route("/meat-ops/case-failures/<failure_id>/transitions", methods=["POST"])
def failure_transition(failure_id):
    user_id, role = mw.authenticate((mw.MEAT_CUTTER, mw.MEAT_MANAGER))
    failure = v.resolve("case_failure", failure_id)
    payload = v.body()

    action = v.field_enum(payload, "action", tuple(FAILURE_ACTION_ROLES),
                          required=True)
    containment_note = v.field_str(payload, "containment_note",
                                   required=(action == "CONTAIN"),
                                   min_len=1, max_len=280)
    disposition = v.field_enum(payload, "disposition", DISPOSITIONS,
                               required=(action == "RESOLVE"))

    mw.check_action_role(role, action, FAILURE_ACTION_ROLES)

    if failure["status"] not in DECLARED_TRANSITIONS[action]:
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION, 409,
                       "%s is not a declared transition out of %s"
                       % (action, failure["status"]))

    department = db.departments[failure["department_id"]]

    if action == "CONTAIN":
        failure["containment_note"] = containment_note
        failure["contained_at"] = now_iso()
        failure["status"] = "CONTAINED"
        mark(failure)
        department["open_case_failure_count"] -= 1
        department["contained_case_failure_count"] += 1
        mark(department)

    elif action == "ESCALATE":
        ready_at = failure["_opened_at"] + timedelta(minutes=ESCALATION_MINUTES)
        if now() < ready_at:
            raise ApiError(errors.ERR_INVALID_STATE_TRANSITION, 409,
                           "A failure may not be escalated before %d minutes have "
                           "passed" % ESCALATION_MINUTES)
        failure["escalated_at"] = now_iso()
        failure["status"] = "ESCALATED"
        mark(failure)

    else:                                          # RESOLVE
        if failure["reported_by_user_id"] == user_id:
            raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 403,
                           "The resolver must differ from the reporting operator")
        from_status = failure["status"]
        failure["disposition"] = disposition
        failure["resolved_at"] = now_iso()
        failure["resolved_by_user_id"] = user_id
        failure["status"] = "RESOLVED"
        mark(failure)
        if from_status == "CONTAINED":
            department["contained_case_failure_count"] -= 1
        else:
            department["open_case_failure_count"] -= 1
        mark(department)

    case.recompute_posture(department)
    return object_response(failure)
