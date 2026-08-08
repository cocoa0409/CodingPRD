"""Composite setup helpers for the Lymphedema & Specialty Rehab API.

Every helper builds its preconditions from scratch through PRD-declared endpoints
(the per-test database starts empty). Setup calls use get_success_data() so a
broken precondition surfaces as a clear "Setup failed" rather than a confusing
assertion deep in a test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS
from . import factories as f
from .constants import (
    STANDARD_CIRCUMFERENCES,
    STANDARD_CONTRALATERAL,
    IMPROVED_CIRCUMFERENCES,
    STANDARD_INTERVAL_CM,
)

CLINICIAN = TEST_USERS["clinician_headers"]
AUTHORIZER = TEST_USERS["authorizer_headers"]
DME = TEST_USERS["dme_coordinator_headers"]
ADMIN = TEST_USERS["clinic_admin_headers"]


# --------------------------------------------------------------------------
# Low-level single-entity helpers
# --------------------------------------------------------------------------
def create_patient(**overrides) -> dict:
    resp = api_client.create_patient(f.create_patient_payload(**overrides), ADMIN)
    return get_success_data(resp)


def patient_version(patient_id: str) -> int:
    resp = api_client.get_patient(patient_id, CLINICIAN)
    return get_success_data(resp)["version"]


def create_draft_evaluation(patient_id, expected_patient_version=None, **overrides) -> dict:
    if expected_patient_version is None:
        expected_patient_version = patient_version(patient_id)
    payload = f.create_evaluation_payload(patient_id, expected_patient_version, **overrides)
    resp = api_client.create_evaluation(payload, CLINICIAN)
    return get_success_data(resp)


def finalize_evaluation(evaluation_id) -> dict:
    resp = api_client.finalize_evaluation(evaluation_id, CLINICIAN)
    return get_success_data(resp)


def create_finalized_evaluation(patient_id, expected_patient_version=None, **overrides) -> dict:
    ev = create_draft_evaluation(patient_id, expected_patient_version, **overrides)
    return finalize_evaluation(ev["id"])


def create_authorization(patient_id, **overrides) -> dict:
    resp = api_client.create_authorization(f.create_authorization_payload(patient_id, **overrides), AUTHORIZER)
    return get_success_data(resp)


def create_approved_authorization(patient_id, **overrides) -> dict:
    auth = create_authorization(patient_id, **overrides)
    get_success_data(api_client.submit_authorization(auth["id"], AUTHORIZER))
    get_success_data(api_client.approve_authorization(auth["id"], AUTHORIZER))
    return get_success_data(api_client.get_authorization(auth["id"], AUTHORIZER))


def create_plan(patient_id, evaluation_id, authorization_id, **overrides) -> dict:
    payload = f.create_treatment_plan_payload(patient_id, evaluation_id, authorization_id, **overrides)
    resp = api_client.create_treatment_plan(payload, CLINICIAN)
    return get_success_data(resp)


def create_active_plan(patient_id, evaluation_id, authorization_id, **overrides) -> dict:
    plan = create_plan(patient_id, evaluation_id, authorization_id, **overrides)
    return get_success_data(api_client.activate_treatment_plan(plan["id"], CLINICIAN))


def create_therapist(**overrides) -> dict:
    resp = api_client.create_therapist(f.create_therapist_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_scheduled_session(plan_id, authorization_id, therapist_id, **overrides) -> dict:
    payload = f.create_session_payload(plan_id, authorization_id, therapist_id, **overrides)
    resp = api_client.create_session(payload, CLINICIAN)
    return get_success_data(resp)


def create_garment_order(patient_id, evaluation_id, expected_patient_version=None, **overrides) -> dict:
    if expected_patient_version is None:
        expected_patient_version = patient_version(patient_id)
    payload = f.create_garment_order_payload(patient_id, evaluation_id, expected_patient_version, **overrides)
    resp = api_client.create_garment_order(payload, CLINICIAN)
    return get_success_data(resp)


def create_approved_garment_order(patient_id, evaluation_id, expected_patient_version=None, **overrides) -> dict:
    order = create_garment_order(patient_id, evaluation_id, expected_patient_version, **overrides)
    return get_success_data(api_client.approve_garment_order(order["id"], AUTHORIZER))


def create_dme_item(**overrides) -> dict:
    resp = api_client.create_dme_item(f.create_dme_item_payload(**overrides), DME)
    return get_success_data(resp)


def create_dispense(garment_order_id, dme_item_id, **overrides) -> dict:
    payload = f.create_dispense_payload(garment_order_id, dme_item_id, **overrides)
    resp = api_client.create_dispense(payload, DME)
    return get_success_data(resp)


def create_adherence_log(plan_id, **overrides) -> dict:
    payload = f.create_adherence_log_payload(plan_id, **overrides)
    resp = api_client.create_adherence_log(payload, CLINICIAN)
    return get_success_data(resp)


# --------------------------------------------------------------------------
# Composite scenario builders
# --------------------------------------------------------------------------
def setup_active_plan_scenario(
    visit_cap=5,
    body_region="LEFT_ARM",
    effective_start_date="2026-05-01",
    effective_end_date="2026-12-31",
    prescribed_daily_minutes=60,
    isl_stage="STAGE_II",
    circumferences_cm=None,
    contralateral_circumferences_cm=None,
):
    """Patient + FINALIZED evaluation + APPROVED authorization + ACTIVE plan + therapist.

    Returns dict: patient, evaluation, authorization, plan, therapist.
    """
    patient = create_patient()
    evaluation = create_finalized_evaluation(
        patient["id"],
        body_region=body_region,
        isl_stage=isl_stage,
        circumferences_cm=circumferences_cm or list(STANDARD_CIRCUMFERENCES),
        contralateral_circumferences_cm=contralateral_circumferences_cm or list(STANDARD_CONTRALATERAL),
        interval_cm=STANDARD_INTERVAL_CM,
    )
    authorization = create_approved_authorization(
        patient["id"],
        body_region=body_region,
        visit_cap=visit_cap,
        effective_start_date=effective_start_date,
        effective_end_date=effective_end_date,
    )
    plan = create_active_plan(
        patient["id"], evaluation["id"], authorization["id"],
        prescribed_daily_minutes=prescribed_daily_minutes,
    )
    therapist = create_therapist()
    return {
        "patient": patient,
        "evaluation": evaluation,
        "authorization": authorization,
        "plan": plan,
        "therapist": therapist,
    }


def setup_scheduled_session_scenario(
    visit_cap=5,
    scheduled_start="2026-06-01T09:00:00Z",
    scheduled_end="2026-06-01T10:00:00Z",
    cdt_component="MLD",
    **scenario_overrides,
):
    """setup_active_plan_scenario plus one SCHEDULED session. Returns the scenario
    dict with an added 'session' key."""
    scenario = setup_active_plan_scenario(visit_cap=visit_cap, **scenario_overrides)
    session = create_scheduled_session(
        scenario["plan"]["id"],
        scenario["authorization"]["id"],
        scenario["therapist"]["id"],
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        cdt_component=cdt_component,
    )
    scenario["session"] = session
    return scenario


def setup_approved_order_and_item(
    initial_stock_qty=10,
    item_l_code="L8100",
    body_region="LEFT_ARM",
):
    """Patient + FINALIZED eval + APPROVED garment order (L8100 SLEEVE) + DME item.

    Returns dict: patient, evaluation, garment_order, dme_item.
    """
    patient = create_patient()
    evaluation = create_finalized_evaluation(patient["id"], body_region=body_region)
    order = create_approved_garment_order(patient["id"], evaluation["id"])
    item = create_dme_item(l_code=item_l_code, initial_stock_qty=initial_stock_qty)
    return {
        "patient": patient,
        "evaluation": evaluation,
        "garment_order": order,
        "dme_item": item,
    }


def setup_draft_order_and_item(initial_stock_qty=10, item_l_code="L8100"):
    """Patient + FINALIZED eval + DRAFT garment order + DME item (order NOT approved)."""
    patient = create_patient()
    evaluation = create_finalized_evaluation(patient["id"], body_region="LEFT_ARM")
    order = create_garment_order(patient["id"], evaluation["id"])
    item = create_dme_item(l_code=item_l_code, initial_stock_qty=initial_stock_qty)
    return {
        "patient": patient,
        "evaluation": evaluation,
        "garment_order": order,
        "dme_item": item,
    }


def setup_reassessment_scenario(finalize_current=True):
    """Patient with a baseline (LEFT_ARM STAGE_II, excess 152.4) evaluation that becomes
    SUPERSEDED, and a current (improved, excess 44.8) FINALIZED LEFT_ARM evaluation; an
    authorization; a DRAFT plan on the current evaluation; and a DRAFT reassessment
    linking baseline -> current.

    Returns dict: patient, baseline_evaluation, current_evaluation, authorization,
    plan, reassessment.
    """
    patient = create_patient()
    baseline = create_finalized_evaluation(
        patient["id"],
        body_region="LEFT_ARM",
        isl_stage="STAGE_II",
        circumferences_cm=list(STANDARD_CIRCUMFERENCES),
        contralateral_circumferences_cm=list(STANDARD_CONTRALATERAL),
    )
    # Creating the second LEFT_ARM evaluation supersedes the baseline and bumps
    # the patient version; the helper re-reads the current version itself.
    current = create_finalized_evaluation(
        patient["id"],
        body_region="LEFT_ARM",
        isl_stage="STAGE_II",
        circumferences_cm=list(IMPROVED_CIRCUMFERENCES),
        contralateral_circumferences_cm=list(STANDARD_CONTRALATERAL),
    )
    authorization = create_authorization(patient["id"], body_region="LEFT_ARM", visit_cap=5)
    plan = create_plan(patient["id"], current["id"], authorization["id"], prescribed_daily_minutes=60)
    reass_resp = api_client.create_reassessment(
        f.create_reassessment_payload(plan["id"], baseline["id"], current["id"]),
        CLINICIAN,
    )
    reassessment = get_success_data(reass_resp)
    return {
        "patient": patient,
        "baseline_evaluation": baseline,
        "current_evaluation": current,
        "authorization": authorization,
        "plan": plan,
        "reassessment": reassessment,
    }


def setup_exhausted_auth_and_held_plan():
    """Drive an APPROVED auth (visit_cap 1) to EXHAUSTED via a single completed session,
    cascading its ACTIVE plan to ON_HOLD. Returns dict: patient, evaluation,
    authorization, plan, therapist, session (all after the cascade)."""
    scenario = setup_scheduled_session_scenario(visit_cap=1)
    session = scenario["session"]
    get_success_data(api_client.check_in_session(session["id"], CLINICIAN))
    get_success_data(api_client.complete_session(session["id"], CLINICIAN))
    scenario["session"] = get_success_data(api_client.get_session(session["id"], CLINICIAN))
    scenario["authorization"] = get_success_data(
        api_client.get_authorization(scenario["authorization"]["id"], AUTHORIZER)
    )
    scenario["plan"] = get_success_data(
        api_client.get_treatment_plan(scenario["plan"]["id"], CLINICIAN)
    )
    return scenario
