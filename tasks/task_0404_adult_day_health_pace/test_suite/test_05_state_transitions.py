"""State-machine transitions: invalid transitions, terminal lockdown, precondition
enforcement, guarded transitions, side-effect cascades, valid bubble-up.

Corner queue B: section state_machines.
"""
from test_helpers import (
    api_client, get_success_data, validate_error, validate_success, ApiErrorId,
    create_program, set_clock, create_participant, create_certified_loc,
    create_active_care_plan, create_in_review_care_plan, create_active_med_order,
    setup_enrolled_participant, setup_disenrolled_participant,
    create_attendance_day, create_transport_leg,
    submit_disenrollment, approve_disenrollment,
    TEST_USERS,
)

PA = TEST_USERS["program_admin_headers"]
IC = TEST_USERS["intake_coordinator_headers"]
MD = TEST_USERS["medical_director_headers"]
NS = TEST_USERS["nurse_staff_headers"]
BS = TEST_USERS["billing_specialist_headers"]


# ===========================================================================
# state_machines / certify_already_certified_invalid_state
# ===========================================================================
def test_certify_already_certified_invalid_state():
    """PRD 3.2: "To move a PENDING assessment to CERTIFIED, the assessment must be
    PENDING (otherwise ERR_INVALID_STATE) and its nf_score must be at least its
    nf_threshold (otherwise ERR_LOC_BELOW_THRESHOLD)."

    Design: Corner/state_machines/certify_already_certified_invalid_state
    """
    program = create_program()
    participant = create_participant(program["id"])
    loc = get_success_data(api_client.create_loc_assessment(
        {"participant_id": participant["id"], "nf_score": 75, "assessed_on": "2026-05-01"}, IC))
    get_success_data(api_client.certify_loc_assessment(loc["id"], MD))
    resp = api_client.certify_loc_assessment(loc["id"], MD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# state_machines / terminal_disenrolled_cannot_enroll_again
# ===========================================================================
def test_terminal_disenrolled_cannot_enroll_again():
    """PRD 3.2: "The full status progression is APPLICANT → ELIGIBLE → ENROLLED →
    DISENROLLMENT_PENDING → DISENROLLED, with DISENROLLED terminal."
    PRD 3.4: "The participant must be in ELIGIBLE status (otherwise ERR_INVALID_STATE)."

    Design: Corner/state_machines/terminal_disenrolled_cannot_enroll_again
    """
    program = create_program(lock_in_days=30)
    _, participant, _ = setup_disenrolled_participant(program_overrides={"lock_in_days": 30})
    resp = api_client.enroll_participant(
        participant["id"], {"enrollment_effective_date": "2026-09-01"}, IC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# state_machines / submit_care_plan_without_goals_rejected
# ===========================================================================
def test_submit_care_plan_without_goals_rejected():
    """PRD 3.3: "submission requires at least one goal (goal_count of 1 or more), failing
    which it is rejected with ERR_CARE_PLAN_NO_GOALS, and the plan must be in DRAFT to
    submit from draft (otherwise ERR_INVALID_STATE)."

    Design: Corner/state_machines/submit_care_plan_without_goals_rejected
    """
    program = create_program()
    participant = create_participant(program["id"])
    cp = get_success_data(api_client.create_care_plan({"participant_id": participant["id"]}, IC))
    resp = api_client.submit_care_plan(cp["id"], IC)
    validate_error(resp, ApiErrorId.ERR_CARE_PLAN_NO_GOALS.value)


# ===========================================================================
# state_machines / no_show_cascades_transport_cancel
# ===========================================================================
def test_no_show_cascades_transport_cancel():
    """PRD 3.5: "Whenever a day moves to NO_SHOW or CANCELLED, every PLANNED transport
    leg under that day is cascaded to CANCELLED."

    Design: Corner/state_machines/no_show_cascades_transport_cancel
    """
    program = create_program()
    participant = create_participant(program["id"])
    day = create_attendance_day(participant["id"], "2026-06-02")
    leg = create_transport_leg(day["id"], direction="PICKUP", window_start_min=480,
                               window_end_min=540, vehicle_id="VAN1")

    no_showed = get_success_data(api_client.no_show_attendance_day(day["id"], NS))
    assert no_showed["status"] == "NO_SHOW"
    assert get_success_data(api_client.get_transport_leg(leg["id"], NS))["status"] == "CANCELLED"


# ===========================================================================
# state_machines / complete_from_scheduled_invalid_state
# ===========================================================================
def test_complete_from_scheduled_invalid_state():
    """PRD 3.5: "A CHECKED_IN day is closed out by NurseStaff completing it, moving it to
    COMPLETED and incrementing the participant's lifetime_attendance_days by 1."
    PRD 2.5: "whether the target resource is in a legal state for the transition
    (ERR_INVALID_STATE, HTTP 409)."

    Completing a SCHEDULED (never CHECKED_IN) day is rejected ERR_INVALID_STATE.

    Design: Corner/state_machines/complete_from_scheduled_invalid_state
    """
    program = create_program()
    participant = create_participant(program["id"])
    day = create_attendance_day(participant["id"], "2026-06-02")
    resp = api_client.complete_attendance_day(day["id"], NS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# state_machines / idt_incomplete_blocks_activation
# ===========================================================================
def test_idt_incomplete_blocks_activation():
    """PRD 3.3: "An IN_REVIEW plan transitions to ACTIVE only when every discipline
    listed in required_disciplines is present in idt_disciplines_signed ... but a missing
    required signature rejects the activation with ERR_IDT_INCOMPLETE".

    Only RN signed of required {RN, SW, MEDICAL_DIRECTOR}: activation is rejected.

    Design: Corner/state_machines/idt_incomplete_blocks_activation
    """
    program = create_program()
    participant = create_participant(program["id"])
    cp = create_in_review_care_plan(participant["id"], sign_disciplines=("RN",))
    resp = api_client.activate_care_plan(cp["id"], MD)
    validate_error(resp, ApiErrorId.ERR_IDT_INCOMPLETE.value)


# ===========================================================================
# state_machines / void_active_care_plan_rejected
# ===========================================================================
def test_void_active_care_plan_rejected():
    """PRD 3.3: "An IntakeCoordinator may void a plan that is in DRAFT, IN_REVIEW, or
    REVISION (otherwise ERR_INVALID_STATE), but never one that is currently the
    participant's active plan - an attempt to void the participant's active care plan is
    rejected with ERR_CANNOT_VOID_ACTIVE."

    Design: Corner/state_machines/void_active_care_plan_rejected
    """
    program = create_program()
    participant = create_participant(program["id"])
    cp = create_active_care_plan(participant["id"])
    resp = api_client.void_care_plan(cp["id"], IC)
    validate_error(resp, ApiErrorId.ERR_CANNOT_VOID_ACTIVE.value)


# ===========================================================================
# state_machines / involuntary_request_cannot_be_denied
# ===========================================================================
def test_involuntary_request_cannot_be_denied():
    """PRD 3.8: "only a VOLUNTARY request may be denied - an INVOLUNTARY for-cause
    request cannot be denied and the attempt is rejected with ERR_INVOLUNTARY_CANNOT_DENY".

    Design: Corner/state_machines/involuntary_request_cannot_be_denied
    """
    program = create_program(lock_in_days=30)
    set_clock("2026-06-15T12:00:00Z")
    _, participant, _ = setup_enrolled_participant(program=program, effective_date="2026-06-01")
    req = submit_disenrollment(participant["id"], kind="INVOLUNTARY", reason_code="NONPAYMENT",
                               requested_effective_date="2026-08-01", as_headers=PA)
    resp = api_client.deny_disenrollment_request(req["id"], MD)
    validate_error(resp, ApiErrorId.ERR_INVOLUNTARY_CANNOT_DENY.value)


# ===========================================================================
# state_machines / involuntary_request_cannot_be_withdrawn
# ===========================================================================
def test_involuntary_request_cannot_be_withdrawn():
    """PRD 3.8: "An IntakeCoordinator may withdraw a request, but only a VOLUNTARY one -
    an INVOLUNTARY request cannot be withdrawn and the attempt is rejected with
    ERR_WITHDRAW_NOT_ALLOWED".

    Design: Corner/state_machines/involuntary_request_cannot_be_withdrawn
    """
    program = create_program(lock_in_days=30)
    set_clock("2026-06-15T12:00:00Z")
    _, participant, _ = setup_enrolled_participant(program=program, effective_date="2026-06-01")
    req = submit_disenrollment(participant["id"], kind="INVOLUNTARY", reason_code="DISRUPTIVE",
                               requested_effective_date="2026-08-01", as_headers=PA)
    approve_disenrollment(req["id"])
    resp = api_client.withdraw_disenrollment_request(req["id"], IC)
    validate_error(resp, ApiErrorId.ERR_WITHDRAW_NOT_ALLOWED.value)


# ===========================================================================
# state_machines / loc_certify_below_threshold_rejected
# ===========================================================================
def test_loc_certify_below_threshold_rejected():
    """PRD 3.2: "its nf_score must be at least its nf_threshold (otherwise
    ERR_LOC_BELOW_THRESHOLD)."

    nf_score 40 below default nf_threshold 60: certification rejected.

    Design: Corner/state_machines/loc_certify_below_threshold_rejected
    """
    program = create_program()
    participant = create_participant(program["id"])
    loc = get_success_data(api_client.create_loc_assessment(
        {"participant_id": participant["id"], "nf_score": 40, "assessed_on": "2026-05-01"}, IC))
    resp = api_client.certify_loc_assessment(loc["id"], MD)
    validate_error(resp, ApiErrorId.ERR_LOC_BELOW_THRESHOLD.value)


# ===========================================================================
# state_machines / med_order_resume_with_inactive_plan_rejected
# ===========================================================================
def test_med_order_resume_with_inactive_plan_rejected():
    """PRD 3.6: "a HELD order may be resumed back to ACTIVE - resuming likewise requires
    the referenced care plan to be ACTIVE, failing with ERR_CARE_PLAN_NOT_ACTIVE if it
    is not."

    A HELD order whose care plan is sent to REVISION cannot be resumed.

    Design: Corner/state_machines/med_order_resume_with_inactive_plan_rejected
    """
    program = create_program()
    participant = create_participant(program["id"])
    cp = create_active_care_plan(participant["id"])
    mo = create_active_med_order(participant["id"], cp["id"], drug_name="Warfarin", daily_doses=1)
    get_success_data(api_client.hold_medication_order(mo["id"], NS))
    get_success_data(api_client.request_care_plan_revision(cp["id"], MD))
    resp = api_client.resume_medication_order(mo["id"], NS)
    validate_error(resp, ApiErrorId.ERR_CARE_PLAN_NOT_ACTIVE.value)


# ===========================================================================
# state_machines / enroll_loc_certified_to_eligible_bubble_up
# ===========================================================================
def test_certify_first_loc_bubbles_participant_to_eligible():
    """PRD 3.2: "the participant's active_loc_assessment_id is pointed at the newly
    certified assessment; and if the participant was still in APPLICANT status, the
    participant bubbles up to ELIGIBLE and its version increments."

    Design: Corner/state_machines/enroll_loc_certified_to_eligible_bubble_up
    """
    program = create_program()
    participant = create_participant(program["id"])
    loc = get_success_data(api_client.create_loc_assessment(
        {"participant_id": participant["id"], "nf_score": 75, "assessed_on": "2026-05-01"}, IC))
    get_success_data(api_client.certify_loc_assessment(loc["id"], MD))

    refreshed = get_success_data(api_client.get_participant(participant["id"], IC))
    assert refreshed["status"] == "ELIGIBLE"
    assert refreshed["active_loc_assessment_id"] == loc["id"]
