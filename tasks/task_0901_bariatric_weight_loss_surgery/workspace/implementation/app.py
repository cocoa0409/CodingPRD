"""Bariatric / Weight-Loss Surgery Program API — Flask entry point.

In-memory only; store starts empty on every boot (see models.py). No seeding.
"""
import os
from datetime import timedelta

from flask import Flask

import models as m
from models import (
    patients, insurance_plans, operating_rooms, surgeons, programs,
    diet_visits, psych_evaluations, nutrition_clearances, milestones,
    surgery_cases, complications, follow_up_visits, financing_plans,
)
import web
from web import (
    ApiError, ok, ok_list, err_response, authenticate, get_body,
    req_str, opt_str, req_enum, req_number, req_int, opt_int, req_bool,
    opt_bool, req_str_array, paginate, ALL_ROLES,
)

app = Flask(__name__)


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return err_response(e)


# ---------------------------------------------------------------------------
# Path-id resolution helpers
# ---------------------------------------------------------------------------
def _get(store, _id, err_id):
    row = store.get(_id)
    if row is None:
        raise ApiError(err_id, 404, f"Resource not found: {_id}")
    return row


def get_patient(i): return _get(patients, i, "ERR_PATIENT_NOT_FOUND")
def get_plan(i): return _get(insurance_plans, i, "ERR_INSURANCE_PLAN_NOT_FOUND")
def get_room(i): return _get(operating_rooms, i, "ERR_OPERATING_ROOM_NOT_FOUND")
def get_surgeon(i): return _get(surgeons, i, "ERR_SURGEON_NOT_FOUND")
def get_program(i): return _get(programs, i, "ERR_PROGRAM_NOT_FOUND")
def get_case(i): return _get(surgery_cases, i, "ERR_SURGERY_CASE_NOT_FOUND")
def get_psych(i): return _get(psych_evaluations, i, "ERR_PSYCH_EVALUATION_NOT_FOUND")
def get_complication(i): return _get(complications, i, "ERR_COMPLICATION_NOT_FOUND")
def get_follow_up(i): return _get(follow_up_visits, i, "ERR_FOLLOW_UP_VISIT_NOT_FOUND")


def surgeon_owns(case, user_id):
    if case["surgeon_id"] != user_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Surgeon does not own this case")


# ===========================================================================
# Configuration (SystemAdmin creates; reads open to all roles)
# ===========================================================================
@app.post("/insurance-plans")
def create_insurance_plan():
    authenticate({"SystemAdmin"})
    b = get_body()
    row = m.base_fields()
    row.update({
        "plan_name": req_str(b, "plan_name"),
        "payer_code": req_str(b, "payer_code"),
        "required_supervised_diet_months": req_int(b, "required_supervised_diet_months", ge=0),
        "requires_psych_clearance": opt_bool(b, "requires_psych_clearance", True),
        "requires_nutrition_clearance": opt_bool(b, "requires_nutrition_clearance", True),
        "bmi_floor_no_comorbidity": req_number(b, "bmi_floor_no_comorbidity") if "bmi_floor_no_comorbidity" in b and b["bmi_floor_no_comorbidity"] is not None else 40.0,
        "bmi_floor_with_comorbidity": req_number(b, "bmi_floor_with_comorbidity") if "bmi_floor_with_comorbidity" in b and b["bmi_floor_with_comorbidity"] is not None else 35.0,
        "qualifying_comorbidities": req_str_array(b, "qualifying_comorbidities", m.COMORBIDITIES),
    })
    insurance_plans[row["id"]] = row
    return ok(m.ser_insurance_plan(row), 201)


@app.get("/insurance-plans/<pid>")
def get_insurance_plan(pid):
    authenticate(ALL_ROLES)
    return ok(m.ser_insurance_plan(get_plan(pid)))


@app.post("/operating-rooms")
def create_operating_room():
    authenticate({"SystemAdmin"})
    b = get_body()
    row = m.base_fields()
    row.update({
        "room_code": req_str(b, "room_code"),
        "turnover_buffer_minutes": opt_int(b, "turnover_buffer_minutes", 30, ge=0),
        "status": req_enum(b, "status", m.ROOM_STATUSES) if "status" in b and b["status"] is not None else "OPEN",
    })
    operating_rooms[row["id"]] = row
    return ok(m.ser_operating_room(row), 201)


@app.get("/operating-rooms/<rid>")
def get_operating_room(rid):
    authenticate(ALL_ROLES)
    return ok(m.ser_operating_room(get_room(rid)))


@app.post("/surgeons")
def create_surgeon():
    authenticate({"SystemAdmin"})
    b = get_body()
    row = m.base_fields()
    row.update({
        "full_name": req_str(b, "full_name"),
        "npi": req_str(b, "npi"),
        "credentialed_procedures": req_str_array(b, "credentialed_procedures", m.PROCEDURES),
    })
    surgeons[row["id"]] = row
    return ok(m.ser_surgeon(row), 201)


@app.get("/surgeons/<sid>")
def get_surgeon_route(sid):
    authenticate(ALL_ROLES)
    return ok(m.ser_surgeon(get_surgeon(sid)))


@app.get("/surgery-cases")
def list_surgery_cases():
    authenticate(ALL_ROLES)
    from flask import request
    rows = list(surgery_cases.values())
    pid = request.args.get("program_id")
    rid = request.args.get("operating_room_id")
    sid = request.args.get("surgeon_id")
    status = request.args.get("status")
    if pid is not None:
        rows = [r for r in rows if r["program_id"] == pid]
    if rid is not None:
        rows = [r for r in rows if r["operating_room_id"] == rid]
    if sid is not None:
        rows = [r for r in rows if r["surgeon_id"] == sid]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = paginate(rows)
    return ok_list([m.ser_surgery_case(r) for r in page], limit, offset, total)


# ===========================================================================
# Logical clock
# ===========================================================================
@app.post("/_clock/set_current_utc")
def set_clock():
    authenticate({"SystemAdmin"})
    b = get_body()
    raw = req_str(b, "to_iso8601")
    try:
        dt = m.parse_dt(raw)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400, "to_iso8601 is not a valid ISO 8601 instant")
    m.clock_set(dt)
    return ok({"current_utc": m._fmt(dt)})


# ===========================================================================
# Patients
# ===========================================================================
@app.post("/patients")
def create_patient():
    authenticate({"ProgramCoordinator"})
    b = get_body()
    row = m.base_fields()
    row.update({
        "mrn": req_str(b, "mrn"),
        "full_name": req_str(b, "full_name"),
        "date_of_birth": req_str(b, "date_of_birth"),
        "sex": req_enum(b, "sex", m.SEXES),
        "height_cm": req_number(b, "height_cm", gt=0),
        "baseline_weight_kg": req_number(b, "baseline_weight_kg", gt=0),
    })
    patients[row["id"]] = row
    return ok(m.ser_patient(row), 201)


@app.get("/patients/<pid>")
def get_patient_route(pid):
    authenticate(ALL_ROLES)
    return ok(m.ser_patient(get_patient(pid)))


# ===========================================================================
# Programs
# ===========================================================================
@app.post("/programs")
def create_program():
    authenticate({"ProgramCoordinator"})
    b = get_body()
    patient_id = req_str(b, "patient_id")
    pathway = req_enum(b, "payment_pathway", m.PAYMENT_PATHWAYS)
    comorbidities = req_str_array(b, "comorbidities", m.COMORBIDITIES)
    plan_id = None
    if "insurance_plan_id" in b and b["insurance_plan_id"] is not None:
        plan_id = b["insurance_plan_id"]
        if not isinstance(plan_id, str) or plan_id == "":
            raise ApiError("ERR_VALIDATION", 400, "insurance_plan_id must be a string")
    # body FK resolution (priority 5) before pathway coherence (priority 6)
    patient = get_patient(patient_id)
    if plan_id is not None:
        get_plan(plan_id)
    # pathway/plan coherence
    if pathway == "INSURANCE" and plan_id is None:
        raise ApiError("ERR_PATHWAY_PLAN_MISMATCH", 422, "INSURANCE requires insurance_plan_id")
    if pathway == "SELF_PAY" and plan_id is not None:
        raise ApiError("ERR_PATHWAY_PLAN_MISMATCH", 422, "SELF_PAY must not supply insurance_plan_id")

    row = m.base_fields()
    row.update({
        "patient_id": patient_id,
        "payment_pathway": pathway,
        "insurance_plan_id": plan_id,
        "comorbidities": comorbidities,
        "baseline_bmi": m.calc_baseline_bmi(patient["height_cm"], patient["baseline_weight_kg"]),
        "baseline_weight_kg": patient["baseline_weight_kg"],
        "ideal_body_weight_kg": m.calc_ideal_body_weight(patient["height_cm"], patient["sex"]),
        "candidacy_status": "UNDETERMINED",
        "qualifying_reason": None,
        "status": "SCREENING",
        "readmission_count": 0,
        "active_complication_count": 0,
        "amount_collected_cents": 0,
        "amount_refunded_cents": 0,
        "amount_forfeited_cents": 0,
    })
    programs[row["id"]] = row
    return ok(m.ser_program(row), 201)


@app.get("/programs/<pid>")
def get_program_route(pid):
    authenticate(ALL_ROLES)
    return ok(m.ser_program(get_program(pid)))


@app.get("/programs")
def list_programs():
    authenticate(ALL_ROLES)
    from flask import request
    rows = list(programs.values())
    patient_id = request.args.get("patient_id")
    plan_id = request.args.get("insurance_plan_id")
    status = request.args.get("status")
    if patient_id is not None:
        rows = [r for r in rows if r["patient_id"] == patient_id]
    if plan_id is not None:
        rows = [r for r in rows if r["insurance_plan_id"] == plan_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = paginate(rows)
    return ok_list([m.ser_program(r) for r in page], limit, offset, total)


@app.post("/programs/<pid>/candidacy-review")
def candidacy_review(pid):
    authenticate({"ProgramCoordinator"})
    program = get_program(pid)
    if program["status"] != "SCREENING":
        raise ApiError("ERR_INVALID_PROGRAM_STATE", 409, "Candidacy review requires SCREENING")
    if program["payment_pathway"] == "INSURANCE":
        plan = insurance_plans[program["insurance_plan_id"]]
        floor_no = plan["bmi_floor_no_comorbidity"]
        floor_yes = plan["bmi_floor_with_comorbidity"]
        qual_set = set(plan["qualifying_comorbidities"])
    else:
        floor_no = m.DEFAULT_BMI_FLOOR_NO_COMORBIDITY
        floor_yes = m.DEFAULT_BMI_FLOOR_WITH_COMORBIDITY
        qual_set = set(m.DEFAULT_QUALIFYING_COMORBIDITIES)
    bmi = program["baseline_bmi"]
    has_qual = bool(set(program["comorbidities"]) & qual_set)
    if bmi >= floor_no:
        program["candidacy_status"] = "QUALIFIED"
        program["qualifying_reason"] = "BMI_40_PLUS"
        program["status"] = "ELIGIBLE"
    elif bmi >= floor_yes and has_qual:
        program["candidacy_status"] = "QUALIFIED"
        program["qualifying_reason"] = "BMI_35_PLUS_COMORBIDITY"
        program["status"] = "ELIGIBLE"
    else:
        program["candidacy_status"] = "NOT_QUALIFIED"
        program["qualifying_reason"] = "NOT_MET"
        program["status"] = "INELIGIBLE"
    m.touch(program)
    return ok(m.ser_program(program))


@app.post("/programs/<pid>/request-clearance")
def request_clearance(pid):
    authenticate({"ProgramCoordinator"})
    program = get_program(pid)
    if program["status"] != "ELIGIBLE":
        raise ApiError("ERR_INVALID_PROGRAM_STATE", 409, "Request-clearance requires ELIGIBLE")
    program["status"] = "CLEARANCE_IN_PROGRESS"
    m.touch(program)
    return ok(m.ser_program(program))


@app.post("/programs/<pid>/finalize-clearance")
def finalize_clearance(pid):
    authenticate({"ProgramCoordinator"})
    program = get_program(pid)
    if program["status"] != "CLEARANCE_IN_PROGRESS":
        raise ApiError("ERR_INVALID_PROGRAM_STATE", 409, "Finalize requires CLEARANCE_IN_PROGRESS")
    if not m.clearances_complete(program):
        raise ApiError("ERR_CLEARANCES_INCOMPLETE", 409, "Clearances are not complete")
    program["status"] = "CLEARED"
    m.touch(program)
    return ok(m.ser_program(program))


@app.get("/programs/<pid>/summary")
def program_summary(pid):
    authenticate(ALL_ROLES)
    program = get_program(pid)
    recorded = [f for f in follow_up_visits.values()
                if f["program_id"] == pid and f["status"] == "COMPLETED"]
    latest_ibw = None
    latest_bmi25 = None
    if recorded:
        latest = sorted(recorded, key=lambda r: (r["updated_at"], r["_seq"]))[-1]
        latest_ibw = latest["ewl_pct_ibw"]
        latest_bmi25 = latest["ewl_pct_bmi25"]
    data = {
        "program_id": program["id"],
        "status": program["status"],
        "baseline_bmi": program["baseline_bmi"],
        "candidacy_status": program["candidacy_status"],
        "latest_ewl_pct_ibw": latest_ibw,
        "latest_ewl_pct_bmi25": latest_bmi25,
        "readmission_count": program["readmission_count"],
        "active_complication_count": program["active_complication_count"],
    }
    return ok(data)


def _require_clearance_window(program):
    if program["status"] != "CLEARANCE_IN_PROGRESS":
        raise ApiError("ERR_INVALID_PROGRAM_STATE", 409,
                       "Clearance artifacts require CLEARANCE_IN_PROGRESS")


# ===========================================================================
# Supervised diet visits
# ===========================================================================
@app.post("/programs/<pid>/diet-visits")
def create_diet_visit(pid):
    authenticate({"Dietitian"})
    program = get_program(pid)
    b = get_body()
    month_index = req_int(b, "month_index", ge=1)
    visit_date = req_str(b, "visit_date")
    weight_kg = req_number(b, "weight_kg", gt=0)
    attended = opt_bool(b, "attended", True)
    _require_clearance_window(program)
    for v in diet_visits.values():
        if v["program_id"] == pid and v["month_index"] == month_index:
            raise ApiError("ERR_DUPLICATE_DIET_MONTH", 409, "month_index already logged")
    row = m.base_fields()
    row.update({"program_id": pid, "month_index": month_index,
                "visit_date": visit_date, "weight_kg": weight_kg, "attended": attended})
    diet_visits[row["id"]] = row
    return ok(m.ser_diet_visit(row), 201)


@app.get("/programs/<pid>/diet-visits")
def list_diet_visits(pid):
    authenticate(ALL_ROLES)
    get_program(pid)
    rows = [v for v in diet_visits.values() if v["program_id"] == pid]
    page, limit, offset, total = paginate(rows)
    return ok_list([m.ser_diet_visit(r) for r in page], limit, offset, total)


# ===========================================================================
# Psych evaluations
# ===========================================================================
@app.post("/programs/<pid>/psych-evaluations")
def create_psych(pid):
    authenticate({"BehavioralHealthClinician"})
    program = get_program(pid)
    b = get_body()
    note = opt_str(b, "clinician_note")
    _require_clearance_window(program)
    row = m.base_fields()
    row.update({"program_id": pid, "clinician_note": note, "status": "PENDING",
                "deferral_reason": None, "reevaluation_count": 0})
    psych_evaluations[row["id"]] = row
    return ok(m.ser_psych(row), 201)


@app.get("/programs/<pid>/psych-evaluations")
def list_psych(pid):
    authenticate(ALL_ROLES)
    get_program(pid)
    rows = [v for v in psych_evaluations.values() if v["program_id"] == pid]
    page, limit, offset, total = paginate(rows)
    return ok_list([m.ser_psych(r) for r in page], limit, offset, total)


@app.post("/psych-evaluations/<eid>/decision")
def psych_decision(eid):
    authenticate({"BehavioralHealthClinician"})
    ev = get_psych(eid)
    b = get_body()
    decision = req_enum(b, "decision", m.PSYCH_DECISIONS)
    deferral_reason = opt_str(b, "deferral_reason")
    if ev["status"] != "PENDING":
        raise ApiError("ERR_INVALID_PSYCH_STATE", 409, "Decision requires PENDING")
    if decision == "CLEARED":
        ev["status"] = "CLEARED"
    else:
        ev["status"] = "DEFERRED"
        ev["deferral_reason"] = deferral_reason
    m.touch(ev)
    return ok(m.ser_psych(ev))


@app.post("/psych-evaluations/<eid>/reevaluate")
def psych_reevaluate(eid):
    authenticate({"BehavioralHealthClinician"})
    ev = get_psych(eid)
    if ev["status"] != "DEFERRED":
        raise ApiError("ERR_INVALID_PSYCH_STATE", 409, "Reevaluate requires DEFERRED")
    ev["status"] = "PENDING"
    ev["reevaluation_count"] += 1
    ev["deferral_reason"] = None
    m.touch(ev)
    return ok(m.ser_psych(ev))


# ===========================================================================
# Nutrition clearances
# ===========================================================================
@app.post("/programs/<pid>/nutrition-clearances")
def create_nutrition(pid):
    authenticate({"Dietitian"})
    program = get_program(pid)
    b = get_body()
    decision = req_enum(b, "decision", m.NUTRITION_DECISIONS)
    score = req_int(b, "diet_readiness_score", ge=0, le=100)
    _require_clearance_window(program)
    row = m.base_fields()
    row.update({"program_id": pid, "decision": decision, "diet_readiness_score": score})
    nutrition_clearances[row["id"]] = row
    return ok(m.ser_nutrition(row), 201)


@app.get("/programs/<pid>/nutrition-clearances")
def list_nutrition(pid):
    authenticate(ALL_ROLES)
    get_program(pid)
    rows = [v for v in nutrition_clearances.values() if v["program_id"] == pid]
    page, limit, offset, total = paginate(rows)
    return ok_list([m.ser_nutrition(r) for r in page], limit, offset, total)


# ===========================================================================
# Education milestones
# ===========================================================================
@app.post("/programs/<pid>/milestones")
def create_milestone(pid):
    authenticate({"ProgramCoordinator"})
    program = get_program(pid)
    b = get_body()
    code = req_enum(b, "milestone_code", m.MILESTONE_CODES)
    completed = opt_bool(b, "completed", False)
    completed_date = opt_str(b, "completed_date")
    _require_clearance_window(program)
    for ms in milestones.values():
        if ms["program_id"] == pid and ms["milestone_code"] == code:
            raise ApiError("ERR_DUPLICATE_MILESTONE", 409, "milestone_code already recorded")
    row = m.base_fields()
    row.update({"program_id": pid, "milestone_code": code,
                "completed": completed, "completed_date": completed_date})
    milestones[row["id"]] = row
    return ok(m.ser_milestone(row), 201)


@app.get("/programs/<pid>/milestones")
def list_milestones(pid):
    authenticate(ALL_ROLES)
    get_program(pid)
    rows = [v for v in milestones.values() if v["program_id"] == pid]
    page, limit, offset, total = paginate(rows)
    return ok_list([m.ser_milestone(r) for r in page], limit, offset, total)


# ===========================================================================
# Surgery scheduling & lifecycle
# ===========================================================================
@app.post("/programs/<pid>/surgery-cases")
def schedule_surgery(pid):
    authenticate({"ProgramCoordinator"})
    program = get_program(pid)
    b = get_body()
    operating_room_id = req_str(b, "operating_room_id")
    surgeon_id = req_str(b, "surgeon_id")
    procedure_type = req_enum(b, "procedure_type", m.PROCEDURES)
    start_raw = req_str(b, "scheduled_start")
    end_raw = req_str(b, "scheduled_end")
    expected_version = req_int(b, "expected_program_version")
    try:
        new_start = m.parse_dt(start_raw)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400, "scheduled_start is not a valid ISO 8601 instant")
    try:
        new_end = m.parse_dt(end_raw)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400, "scheduled_end is not a valid ISO 8601 instant")
    # body FK resolution (priority 5)
    room = get_room(operating_room_id)
    surgeon = get_surgeon(surgeon_id)
    # state: program must be CLEARED (priority 8)
    if program["status"] != "CLEARED":
        raise ApiError("ERR_PROGRAM_NOT_CLEARED", 409, "Program must be CLEARED to schedule")
    # credentialing (priority 11)
    if procedure_type not in surgeon["credentialed_procedures"]:
        raise ApiError("ERR_SURGEON_NOT_CREDENTIALED", 409, "Surgeon not credentialed")
    # room open (priority 12)
    if room["status"] != "OPEN":
        raise ApiError("ERR_ROOM_CLOSED", 409, "Operating room is CLOSED")
    # time window (priority 15)
    if not new_end > new_start:
        raise ApiError("ERR_INVALID_TIME_WINDOW", 422, "scheduled_end must be after scheduled_start")
    # not in past (priority 16)
    if new_start < m.clock_now():
        raise ApiError("ERR_SURGERY_IN_PAST", 422, "scheduled_start is in the past")
    # OR room conflict (priority 17): buffer-extended symmetric
    buffer = timedelta(minutes=room["turnover_buffer_minutes"])
    for c in surgery_cases.values():
        if c["operating_room_id"] == operating_room_id and c["status"] != "CANCELLED":
            cstart = m.parse_dt(c["scheduled_start"])
            cend = m.parse_dt(c["scheduled_end"])
            if new_start < cend + buffer and cstart < new_end + buffer:
                raise ApiError("ERR_OR_ROOM_CONFLICT", 409, "Operating room conflict")
    # surgeon conflict (priority 18): strict overlap, no buffer
    for c in surgery_cases.values():
        if c["surgeon_id"] == surgeon_id and c["status"] != "CANCELLED":
            cstart = m.parse_dt(c["scheduled_start"])
            cend = m.parse_dt(c["scheduled_end"])
            if new_start < cend and cstart < new_end:
                raise ApiError("ERR_SURGEON_CONFLICT", 409, "Surgeon conflict")
    # OCC (priority 20)
    if expected_version != program["version"]:
        raise ApiError("ERR_STALE_PROGRAM_VERSION", 412, "expected_program_version mismatch")

    if program["payment_pathway"] == "SELF_PAY":
        estimate = m.bundle_estimate_cents(procedure_type, program["baseline_bmi"])
    else:
        estimate = 0
    row = m.base_fields()
    row.update({
        "program_id": pid, "operating_room_id": operating_room_id,
        "surgeon_id": surgeon_id, "procedure_type": procedure_type,
        "scheduled_start": start_raw, "scheduled_end": end_raw,
        "status": "SCHEDULED", "estimated_bundle_cents": estimate,
        "actual_or_minutes": None, "final_bundle_cents": None,
        "cancellation_reason": None,
    })
    surgery_cases[row["id"]] = row
    program["status"] = "SURGERY_SCHEDULED"
    m.touch(program)
    return ok(m.ser_surgery_case(row), 201)


@app.get("/surgery-cases/<cid>")
def get_surgery_case_route(cid):
    authenticate(ALL_ROLES)
    return ok(m.ser_surgery_case(get_case(cid)))


@app.post("/surgery-cases/<cid>/complete")
def complete_surgery(cid):
    user_id, _ = authenticate({"Surgeon"})
    case = get_case(cid)
    surgeon_owns(case, user_id)
    b = get_body()
    actual_or_minutes = req_int(b, "actual_or_minutes", ge=0)
    if case["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_SURGERY_STATE", 409, "Complete requires SCHEDULED")
    program = programs[case["program_id"]]
    case["actual_or_minutes"] = actual_or_minutes
    if program["payment_pathway"] == "SELF_PAY":
        case["final_bundle_cents"] = m.bundle_final_cents(
            case["procedure_type"], program["baseline_bmi"], actual_or_minutes)
    else:
        case["final_bundle_cents"] = 0
    case["status"] = "COMPLETED"
    m.touch(case)
    # cascade: program -> POST_OP; generate follow-up series
    program["status"] = "POST_OP"
    completion_date = m.clock_now().date()
    for code in m.INTERVAL_ORDER:
        d = completion_date + timedelta(days=m.INTERVAL_OFFSET_DAYS[code])
        fv = m.base_fields()
        fv.update({"program_id": program["id"], "interval_code": code,
                   "scheduled_date": d.isoformat(), "status": "SCHEDULED",
                   "recorded_weight_kg": None, "ewl_pct_ibw": None,
                   "ewl_pct_bmi25": None})
        follow_up_visits[fv["id"]] = fv
    m.touch(program)
    return ok(m.ser_surgery_case(case))


@app.post("/surgery-cases/<cid>/cancel")
def cancel_surgery(cid):
    authenticate({"ProgramCoordinator"})
    case = get_case(cid)
    b = get_body()
    reason = opt_str(b, "cancellation_reason")
    if case["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_SURGERY_STATE", 409, "Cancel requires SCHEDULED")
    case["status"] = "CANCELLED"
    case["cancellation_reason"] = reason
    m.touch(case)
    program = programs[case["program_id"]]
    program["status"] = "CLEARED"
    if program["payment_pathway"] == "SELF_PAY" and program["amount_collected_cents"] > 0:
        forfeited, refunded = m.cancellation_refund(program["amount_collected_cents"])
        program["amount_forfeited_cents"] += forfeited
        program["amount_refunded_cents"] += refunded
    m.touch(program)
    return ok(m.ser_surgery_case(case))


# ===========================================================================
# Complications
# ===========================================================================
@app.post("/surgery-cases/<cid>/complications")
def create_complication(cid):
    user_id, _ = authenticate({"Surgeon"})
    case = get_case(cid)
    surgeon_owns(case, user_id)
    b = get_body()
    ctype = req_enum(b, "complication_type", m.COMPLICATION_TYPES)
    severity = req_enum(b, "severity", m.SEVERITIES)
    requires_readmission = req_bool(b, "requires_readmission")
    onset_date = req_str(b, "onset_date")
    row = m.base_fields()
    row.update({"surgery_case_id": cid, "complication_type": ctype,
                "severity": severity, "requires_readmission": requires_readmission,
                "onset_date": onset_date, "status": "OPEN"})
    complications[row["id"]] = row
    program = programs[case["program_id"]]
    program["active_complication_count"] += 1
    if requires_readmission:
        program["readmission_count"] += 1
        if program["status"] == "POST_OP":
            program["status"] = "READMITTED"
    m.touch(program)
    return ok(m.ser_complication(row), 201)


@app.get("/surgery-cases/<cid>/complications")
def list_complications(cid):
    authenticate(ALL_ROLES)
    get_case(cid)
    rows = [c for c in complications.values() if c["surgery_case_id"] == cid]
    page, limit, offset, total = paginate(rows)
    return ok_list([m.ser_complication(r) for r in page], limit, offset, total)


@app.post("/complications/<coid>/resolve")
def resolve_complication(coid):
    user_id, _ = authenticate({"Surgeon"})
    comp = get_complication(coid)
    case = surgery_cases[comp["surgery_case_id"]]
    surgeon_owns(case, user_id)
    if comp["status"] != "OPEN":
        raise ApiError("ERR_INVALID_COMPLICATION_STATE", 409, "Resolve requires OPEN")
    comp["status"] = "RESOLVED"
    m.touch(comp)
    program = programs[case["program_id"]]
    program["active_complication_count"] -= 1
    if program["status"] == "READMITTED" and program["active_complication_count"] == 0:
        program["status"] = "POST_OP"
    m.touch(program)
    return ok(m.ser_complication(comp))


# ===========================================================================
# Follow-up visits
# ===========================================================================
@app.get("/programs/<pid>/follow-up-visits")
def list_follow_ups(pid):
    authenticate(ALL_ROLES)
    get_program(pid)
    rows = [f for f in follow_up_visits.values() if f["program_id"] == pid]
    page, limit, offset, total = paginate(rows)
    return ok_list([m.ser_follow_up(r) for r in page], limit, offset, total)


@app.post("/follow-up-visits/<fid>/record")
def record_follow_up(fid):
    authenticate({"Dietitian"})
    fv = get_follow_up(fid)
    b = get_body()
    recorded_weight = req_number(b, "recorded_weight_kg", gt=0)
    if fv["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_FOLLOWUP_STATE", 409, "Record requires SCHEDULED")
    program = programs[fv["program_id"]]
    patient = patients[program["patient_id"]]
    ewl_ibw, ewl_bmi25 = m.weight_loss_outcome(
        program["baseline_weight_kg"], recorded_weight,
        program["ideal_body_weight_kg"], patient["height_cm"])
    fv["recorded_weight_kg"] = recorded_weight
    fv["ewl_pct_ibw"] = ewl_ibw
    fv["ewl_pct_bmi25"] = ewl_bmi25
    fv["status"] = "COMPLETED"
    m.touch(fv)
    if fv["interval_code"] == "MONTH_12" and program["status"] == "POST_OP":
        program["status"] = "COMPLETED"
        m.touch(program)
    return ok(m.ser_follow_up(fv))


# ===========================================================================
# Financing
# ===========================================================================
@app.post("/programs/<pid>/financing-plan")
def create_financing(pid):
    authenticate({"BillingSpecialist"})
    program = get_program(pid)
    b = get_body()
    procedure_type = req_enum(b, "procedure_type", m.PROCEDURES)
    down_payment = req_int(b, "down_payment_cents", ge=0)
    term_months = req_int(b, "term_months", ge=1)
    apr_bps = req_int(b, "apr_bps", ge=0)
    expected_version = req_int(b, "expected_program_version")
    # SELF_PAY only (priority 9)
    if program["payment_pathway"] != "SELF_PAY":
        raise ApiError("ERR_NOT_SELF_PAY", 409, "Financing requires SELF_PAY program")
    bundle_price = m.bundle_estimate_cents(procedure_type, program["baseline_bmi"])
    # down payment cap (priority 19)
    if down_payment > bundle_price:
        raise ApiError("ERR_DOWN_PAYMENT_EXCEEDS_BUNDLE", 422, "down_payment exceeds bundle")
    # OCC (priority 20)
    if expected_version != program["version"]:
        raise ApiError("ERR_STALE_PROGRAM_VERSION", 412, "expected_program_version mismatch")

    interest, installment, final_installment = m.financing_schedule(
        bundle_price, down_payment, apr_bps, term_months)
    # supersede prior ACTIVE plan(s)
    for fp in financing_plans.values():
        if fp["program_id"] == pid and fp["status"] == "ACTIVE":
            fp["status"] = "SUPERSEDED"
            m.touch(fp)
    row = m.base_fields()
    row.update({
        "program_id": pid, "procedure_type": procedure_type,
        "down_payment_cents": down_payment, "term_months": term_months,
        "apr_bps": apr_bps, "bundle_price_cents": bundle_price,
        "interest_cents": interest, "installment_cents": installment,
        "final_installment_cents": final_installment, "status": "ACTIVE",
    })
    financing_plans[row["id"]] = row
    program["amount_collected_cents"] = down_payment
    m.touch(program)
    return ok(m.ser_financing(row), 201)


@app.get("/programs/<pid>/financing-plan")
def list_financing(pid):
    authenticate(ALL_ROLES)
    get_program(pid)
    rows = [f for f in financing_plans.values() if f["program_id"] == pid]
    page, limit, offset, total = paginate(rows)
    return ok_list([m.ser_financing(r) for r in page], limit, offset, total)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
