"""State-machine corners: valid transition + invalid-transition rejections."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_clinician_headers,
    register_patient, register_referral, register_clinician,
    setup_finalized_assessment, setup_active_care_plan,
)

INTAKE = TEST_USERS["intake_headers"]
SUPER = TEST_USERS["supervisor_headers"]


def test_referral_decision_accept_moves_to_accepted(api):
    """PRD §3.1: "an operator supplies a `decision` of either `ACCEPT`, which
    advances the referral to `ACCEPTED`, or `DECLINE`, which moves it to the
    terminal `DECLINED` state."

    Design: Corner/state_machines/corner_referral_decision_accept_valid_transition
    """
    patient = register_patient(api, insurance_member_id="MEM-C-04")
    referral = register_referral(api, patient["id"])
    resp = api.decide_referral(referral["id"], {"decision": "ACCEPT"}, INTAKE)
    data = validate_success(resp, 200)
    assert data["status"] == "ACCEPTED"


def test_finalize_already_finalized_assessment_rejected(api):
    """PRD §3.2: "Finalization is permitted only from `DRAFT`; a second finalize
    attempt is rejected with `ERR_INVALID_STATE`, and a finalize by anyone other
    than the clinician named in `clinician_id` is rejected with `ERR_NOT_OWNER`."

    Design: Corner/state_machines/corner_finalize_assessment_twice_rejected
    """
    ctx = setup_finalized_assessment(api)  # assessment already FINALIZED
    resp = api.finalize_assessment(ctx["assessment"]["id"], ctx["clinician_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_activate_already_active_plan_rejected(api):
    """PRD §3.3: "A ClinicSupervisor activates a plan, moving it from DRAFT to
    ACTIVE; activation from any other state is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/corner_activate_non_draft_plan_rejected
    """
    ctx = setup_active_care_plan(api)  # plan already ACTIVE
    resp = api.activate_care_plan(ctx["care_plan"]["id"], SUPER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_dispense_pending_device_referral_rejected(api):
    """PRD §3.7: "from APPROVED, a DISPENSE moves it to the terminal DISPENSED. A
    decision that does not match the referral's current state is rejected with
    ERR_INVALID_STATE."

    Design: Corner/state_machines/corner_device_dispense_before_approve_rejected
    """
    ctx = setup_finalized_assessment(api)
    cp = get_success_data(
        api.create_care_plan(
            {"patient_id": ctx["patient"]["id"], "assessment_id": ctx["assessment"]["id"]},
            INTAKE,
        )
    )
    dr = get_success_data(
        api.create_device_referral(
            {"patient_id": ctx["patient"]["id"], "care_plan_id": cp["id"], "device_type": "CANE"},
            ctx["clinician_headers"],
        )
    )
    assert dr["status"] == "PENDING"
    resp = api.decide_device_referral(dr["id"], {"decision": "DISPENSE"}, SUPER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
