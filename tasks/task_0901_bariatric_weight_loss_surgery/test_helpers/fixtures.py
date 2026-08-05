"""Composite setup helpers.

Each helper builds its preconditions from scratch using only PRD-declared endpoints,
because the test harness restarts the server (empty DB) before every test. Fixtures
use get_success_data (lenient) internally so setup failures surface clearly.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_surgeon_headers
from . import factories as f
from .constants import DEFAULT_SURGERY_START, DEFAULT_SURGERY_END, REQUIRED_MILESTONES

PC = TEST_USERS["program_coordinator_headers"]
DT = TEST_USERS["dietitian_headers"]
BH = TEST_USERS["behavioral_health_headers"]
BILL = TEST_USERS["billing_specialist_headers"]
ADMIN = TEST_USERS["system_admin_headers"]


def _d(resp):
    return get_success_data(resp)


# ---------------- Primitive entity creators ----------------

def create_patient(api=api_client, **overrides):
    return _d(api.create_patient(f.create_patient_payload(**overrides), PC))


def create_insurance_plan(api=api_client, **overrides):
    return _d(api.create_insurance_plan(f.create_insurance_plan_payload(**overrides), ADMIN))


def create_operating_room(api=api_client, **overrides):
    return _d(api.create_operating_room(f.create_operating_room_payload(**overrides), ADMIN))


def create_surgeon(api=api_client, **overrides):
    return _d(api.create_surgeon(f.create_surgeon_payload(**overrides), ADMIN))


def create_program(api=api_client, patient_id=None, payment_pathway="SELF_PAY", **overrides):
    if patient_id is None:
        patient_id = create_patient(api)["id"]
    payload = f.create_program_payload(patient_id, payment_pathway=payment_pathway, **overrides)
    return _d(api.create_program(payload, PC))


def get_program(api=api_client, program_id=None):
    return _d(api.get_program(program_id, PC))


def program_version(api=api_client, program_id=None):
    return get_program(api, program_id)["version"]


# ---------------- Clearance-artifact helpers ----------------

def add_psych_cleared(api=api_client, program_id=None):
    pe = _d(api.create_psych_evaluation(program_id, f.create_psych_evaluation_payload(), BH))
    _d(api.psych_decision(pe["id"], {"decision": "CLEARED"}, BH))
    return pe


def add_psych_deferred(api=api_client, program_id=None, deferral_reason="reassess in 4 weeks"):
    pe = _d(api.create_psych_evaluation(program_id, f.create_psych_evaluation_payload(), BH))
    _d(api.psych_decision(pe["id"], {"decision": "DEFERRED", "deferral_reason": deferral_reason}, BH))
    return pe


def add_nutrition_cleared(api=api_client, program_id=None, diet_readiness_score=80):
    return _d(api.create_nutrition_clearance(
        program_id, f.create_nutrition_clearance_payload(diet_readiness_score=diet_readiness_score), DT))


def add_all_milestones(api=api_client, program_id=None):
    out = []
    for code in REQUIRED_MILESTONES:
        out.append(_d(api.create_milestone(program_id, f.create_milestone_payload(code), PC)))
    return out


def add_diet_visit(api=api_client, program_id=None, month_index=1, visit_date="2026-02-01",
                   weight_kg=118, attended=True):
    return _d(api.create_diet_visit(
        program_id,
        f.create_diet_visit_payload(month_index, visit_date=visit_date, weight_kg=weight_kg, attended=attended),
        DT))


# ---------------- Program-lifecycle composites ----------------

def create_program_for_new_patient(api=api_client, payment_pathway="SELF_PAY", insurance_plan_id=None,
                                   comorbidities=None, **patient_kwargs):
    """Register a fresh patient (default FEMALE 170cm/120kg => baseline_bmi 41.5) and
    enroll them in a program in SCREENING. Returns the created program."""
    patient = create_patient(api, **patient_kwargs)
    program = create_program(
        api,
        patient_id=patient["id"],
        payment_pathway=payment_pathway,
        insurance_plan_id=insurance_plan_id,
        comorbidities=comorbidities if comorbidities is not None else [],
    )
    return program


def create_reviewed_program(api=api_client, payment_pathway="SELF_PAY", insurance_plan_id=None,
                            comorbidities=None, **patient_kwargs):
    """patient -> program -> candidacy-review. Returns the program after review."""
    program = create_program_for_new_patient(
        api, payment_pathway=payment_pathway, insurance_plan_id=insurance_plan_id,
        comorbidities=comorbidities, **patient_kwargs)
    _d(api.candidacy_review(program["id"], PC))
    return get_program(api, program["id"])


def create_clearance_in_progress_program(api=api_client, payment_pathway="SELF_PAY",
                                         insurance_plan_id=None, comorbidities=None, **patient_kwargs):
    """Walk a qualifying program to CLEARANCE_IN_PROGRESS (review + request-clearance)."""
    program = create_reviewed_program(
        api, payment_pathway=payment_pathway, insurance_plan_id=insurance_plan_id,
        comorbidities=comorbidities, **patient_kwargs)
    _d(api.request_clearance(program["id"], PC))
    return get_program(api, program["id"])


def create_cleared_self_pay_program(api=api_client, comorbidities=None, **patient_kwargs):
    """Full walk for a SELF_PAY program to CLEARED: review, open clearance,
    psych CLEARED, nutrition CLEARED, all 4 milestones, finalize."""
    program = create_clearance_in_progress_program(
        api, payment_pathway="SELF_PAY", comorbidities=comorbidities, **patient_kwargs)
    pid = program["id"]
    add_psych_cleared(api, pid)
    add_nutrition_cleared(api, pid)
    add_all_milestones(api, pid)
    _d(api.finalize_clearance(pid, PC))
    return get_program(api, pid)


def create_insurance_clearance_ready_except_diet(api=api_client, required_supervised_diet_months=3,
                                                 comorbidities=None):
    """INSURANCE program in CLEARANCE_IN_PROGRESS with psych CLEARED, nutrition
    CLEARED and all 4 milestones done, but NO diet visits logged yet.
    Returns (program, plan)."""
    plan = create_insurance_plan(api, required_supervised_diet_months=required_supervised_diet_months)
    program = create_clearance_in_progress_program(
        api, payment_pathway="INSURANCE", insurance_plan_id=plan["id"],
        comorbidities=comorbidities)
    pid = program["id"]
    add_psych_cleared(api, pid)
    add_nutrition_cleared(api, pid)
    add_all_milestones(api, pid)
    return get_program(api, pid), plan


# ---------------- Surgery-lifecycle composites ----------------

def setup_scheduled_case(api=api_client, program=None, procedure_type="SLEEVE_GASTRECTOMY",
                         credentialed_procedures=None, surgeon=None, room=None,
                         scheduled_start=DEFAULT_SURGERY_START, scheduled_end=DEFAULT_SURGERY_END,
                         comorbidities=None, **patient_kwargs):
    """Cleared SELF_PAY program + credentialed surgeon + OPEN room + one SCHEDULED case.
    Returns dict(program, case, surgeon, room)."""
    if program is None:
        program = create_cleared_self_pay_program(api, comorbidities=comorbidities, **patient_kwargs)
    if surgeon is None:
        creds = credentialed_procedures if credentialed_procedures is not None else [procedure_type]
        surgeon = create_surgeon(api, credentialed_procedures=creds)
    if room is None:
        room = create_operating_room(api)
    version = program_version(api, program["id"])
    payload = f.schedule_surgery_case_payload(
        room["id"], surgeon["id"], version, procedure_type=procedure_type,
        scheduled_start=scheduled_start, scheduled_end=scheduled_end)
    case = _d(api.schedule_surgery_case(program["id"], payload, PC))
    return {"program": get_program(api, program["id"]), "case": case, "surgeon": surgeon, "room": room}


def setup_completed_case(api=api_client, actual_or_minutes=95, procedure_type="SLEEVE_GASTRECTOMY",
                         comorbidities=None, **patient_kwargs):
    """Program in POST_OP after a completed surgery. Returns dict(program, case, surgeon, room)."""
    ctx = setup_scheduled_case(api, procedure_type=procedure_type, comorbidities=comorbidities,
                               **patient_kwargs)
    surgeon_headers = make_surgeon_headers(ctx["surgeon"]["id"])
    case = _d(api.complete_surgery_case(
        ctx["case"]["id"], f.complete_surgery_case_payload(actual_or_minutes=actual_or_minutes),
        surgeon_headers))
    return {"program": get_program(api, ctx["program"]["id"]), "case": case,
            "surgeon": ctx["surgeon"], "room": ctx["room"]}


def setup_postop_with_open_complication(api=api_client, requires_readmission=False,
                                        complication_type="INFECTION", severity="MINOR",
                                        onset_date="2026-06-16"):
    """POST_OP (or READMITTED) program with one OPEN complication.
    Returns dict(program, case, surgeon, room, complication)."""
    ctx = setup_completed_case(api)
    surgeon_headers = make_surgeon_headers(ctx["surgeon"]["id"])
    comp = _d(api.create_complication(
        ctx["case"]["id"],
        f.create_complication_payload(complication_type=complication_type, severity=severity,
                                      requires_readmission=requires_readmission, onset_date=onset_date),
        surgeon_headers))
    ctx["complication"] = comp
    ctx["program"] = get_program(api, ctx["program"]["id"])
    return ctx


def first_follow_up_visit_id(api=api_client, program_id=None):
    data = _d(api.list_follow_up_visits(program_id, PC))
    return data[0]["id"]
