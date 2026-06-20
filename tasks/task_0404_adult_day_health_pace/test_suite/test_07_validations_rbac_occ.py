"""Enroll/transport/billing validations, RBAC segregation of duties, OCC, LOC expiry,
and immediate-consistency ledger visibility.

Corner queue B: sections validations, rbac, cross_cutting_complexity_layers,
consistency_model.
"""
from test_helpers import (
    api_client, get_success_data, validate_error, validate_success, ApiErrorId,
    create_program, set_clock, create_participant, create_certified_loc,
    create_active_care_plan, setup_enrolled_participant, setup_eligible_participant,
    create_attendance_day, create_transport_leg, create_draft_capitation,
    finalize_capitation, get_participant_version,
    TEST_USERS,
)

PA = TEST_USERS["program_admin_headers"]
IC = TEST_USERS["intake_coordinator_headers"]
MD = TEST_USERS["medical_director_headers"]
NS = TEST_USERS["nurse_staff_headers"]
BS = TEST_USERS["billing_specialist_headers"]


def _ready_to_enroll(program, dob="1955-01-01", clock="2026-05-20T12:00:00Z"):
    set_clock(clock)
    p = create_participant(program["id"], date_of_birth=dob)
    create_certified_loc(p["id"])
    create_active_care_plan(p["id"])
    return p


# ===========================================================================
# validations / enroll_age_ineligible
# ===========================================================================
def test_enroll_age_ineligible():
    """PRD 3.4: "The participant must be at least 55 years old as of
    enrollment_effective_date, computed against the participant's date_of_birth
    (otherwise ERR_AGE_INELIGIBLE)."

    DOB 1980-01-01 is age 46 at effective 2026-06-01: ERR_AGE_INELIGIBLE.

    Design: Corner/validations/enroll_age_ineligible
    """
    program = create_program()
    p = _ready_to_enroll(program, dob="1980-01-01")
    resp = api_client.enroll_participant(p["id"], {"enrollment_effective_date": "2026-06-01"}, IC)
    validate_error(resp, ApiErrorId.ERR_AGE_INELIGIBLE.value)


# ===========================================================================
# validations / duplicate_attendance_service_date
# ===========================================================================
def test_duplicate_attendance_service_date():
    """PRD 3.5: "The day's service_date must be unique per participant; a second day on
    the same date for the same participant is rejected with ERR_DUPLICATE_PERIOD."

    Design: Corner/validations/duplicate_attendance_service_date
    """
    program = create_program()
    participant = create_participant(program["id"])
    create_attendance_day(participant["id"], "2026-06-02")
    resp = api_client.create_attendance_day(
        {"participant_id": participant["id"], "service_date": "2026-06-02"}, NS)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PERIOD.value)


# ===========================================================================
# validations / transport_window_end_before_start
# ===========================================================================
def test_transport_window_end_before_start():
    """PRD 3.5: "window_end_min is strictly greater than window_start_min and at most
    1440 - an end not strictly after the start, or a window outside the 0-to-1440 bounds,
    is rejected with ERR_INVALID_WINDOW."

    window_end_min 520 <= window_start_min 540: ERR_INVALID_WINDOW.

    Design: Corner/validations/transport_window_end_before_start
    """
    program = create_program()
    participant = create_participant(program["id"])
    day = create_attendance_day(participant["id"], "2026-06-02")
    resp = api_client.create_transport_leg(
        {"attendance_day_id": day["id"], "direction": "PICKUP",
         "window_start_min": 540, "window_end_min": 520, "vehicle_id": "VAN1"}, NS)
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW.value)


# ===========================================================================
# validations / transport_touching_windows_allowed
# ===========================================================================
def test_transport_touching_windows_allowed():
    """PRD 3.5: "intervals are treated as half-open, so a leg that merely touches another
    at an endpoint (one ending exactly when the next begins) does not overlap, but any
    genuine overlap is rejected with ERR_TRANSPORT_OVERLAP."

    A new leg [540,600) touching existing [480,540) on VAN1 is accepted as PLANNED.

    Design: Corner/validations/transport_touching_windows_allowed
    """
    program = create_program()
    participant = create_participant(program["id"])
    day = create_attendance_day(participant["id"], "2026-06-02")
    create_transport_leg(day["id"], direction="PICKUP", window_start_min=480,
                         window_end_min=540, vehicle_id="VAN1")
    resp = api_client.create_transport_leg(
        {"attendance_day_id": day["id"], "direction": "DROPOFF",
         "window_start_min": 540, "window_end_min": 600, "vehicle_id": "VAN1"}, NS)
    leg = validate_success(resp, expected_status=201)
    assert leg["status"] == "PLANNED"


# ===========================================================================
# validations / recoup_exceeds_billed_rejected
# ===========================================================================
def test_recoup_exceeds_billed_rejected():
    """PRD 3.7: "The recoup_cents may not exceed total_billed_cents; a recoup larger than
    what was billed is rejected with ERR_RECOUP_EXCEEDS_BILLED".

    recoup_cents 700000 > total_billed_cents 630000: ERR_RECOUP_EXCEEDS_BILLED.

    Design: Corner/validations/recoup_exceeds_billed_rejected
    """
    program = create_program(lock_in_days=30)
    set_clock("2026-06-15T12:00:00Z")
    _, participant, _ = setup_enrolled_participant(program=program, dual_eligible=True,
                                                   effective_date="2026-06-01")
    payment = create_draft_capitation(participant["id"], "2026-06-01", "FULL_MONTH")
    payment = finalize_capitation(payment["id"], participant["id"])
    resp = api_client.reconcile_capitation_payment(payment["id"], {"recoup_cents": 700000}, BS)
    validate_error(resp, ApiErrorId.ERR_RECOUP_EXCEEDS_BILLED.value)


# ===========================================================================
# validations / capitation_finalize_program_suspended
# ===========================================================================
def test_capitation_finalize_program_suspended():
    """PRD 3.1: "While a program is SUSPENDED, two operations are blocked and rejected
    with ERR_PROGRAM_SUSPENDED: enrolling a participant, and finalizing a capitation
    payment."

    Design: Corner/validations/capitation_finalize_program_suspended
    """
    program = create_program(lock_in_days=30)
    set_clock("2026-06-15T12:00:00Z")
    _, participant, _ = setup_enrolled_participant(program=program, effective_date="2026-06-01")
    payment = create_draft_capitation(participant["id"], "2026-06-01", "FULL_MONTH")
    ver = get_participant_version(participant["id"])
    get_success_data(api_client.suspend_program(program["id"], PA))
    resp = api_client.finalize_capitation_payment(
        payment["id"], {"expected_participant_version": ver}, BS)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_SUSPENDED.value)


# ===========================================================================
# validations / enroll_no_active_care_plan
# ===========================================================================
def test_enroll_no_active_care_plan():
    """PRD 3.4: "The participant must have a non-null active_care_plan_id - an ACTIVE
    care plan must exist (otherwise ERR_NO_ACTIVE_CARE_PLAN)."

    An ELIGIBLE participant with a certified LOC but no activated care plan: enroll fails
    ERR_NO_ACTIVE_CARE_PLAN.

    Design: Corner/validations/enroll_no_active_care_plan
    """
    program = create_program()
    set_clock("2026-05-20T12:00:00Z")
    _, participant, _ = setup_eligible_participant(program_id=program["id"])
    resp = api_client.enroll_participant(
        participant["id"], {"enrollment_effective_date": "2026-06-01"}, IC)
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_CARE_PLAN.value)


# ===========================================================================
# rbac / intake_cannot_certify_loc_segregation
# ===========================================================================
def test_intake_cannot_certify_loc_segregation():
    """PRD 3.2: "Certification is a clinical act reserved to the MedicalDirector alone -
    an IntakeCoordinator may author an assessment but may never certify it."

    Design: Corner/rbac/intake_cannot_certify_loc_segregation
    """
    program = create_program()
    participant = create_participant(program["id"])
    loc = get_success_data(api_client.create_loc_assessment(
        {"participant_id": participant["id"], "nf_score": 75, "assessed_on": "2026-05-01"}, IC))
    resp = api_client.certify_loc_assessment(loc["id"], IC)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ===========================================================================
# rbac / billing_cannot_enroll_segregation
# ===========================================================================
def test_billing_cannot_enroll_segregation():
    """PRD 2.1: "a BillingSpecialist owns the money but cannot enroll, certify, or approve
    a disenrollment."
    PRD 3.4: "Enrolling a participant is the IntakeCoordinator's act".

    Design: Corner/rbac/billing_cannot_enroll_segregation
    """
    program = create_program()
    p = _ready_to_enroll(program)
    resp = api_client.enroll_participant(p["id"], {"enrollment_effective_date": "2026-06-01"}, BS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ===========================================================================
# rbac / missing_headers_unauthenticated
# ===========================================================================
def test_unknown_role_unauthenticated():
    """PRD 2.1: "If either header is missing, or if X-User-Role is not one of the
    recognized role names, the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_headers_unauthenticated
    """
    program = create_program()
    resp = api_client.get_program(program["id"], TEST_USERS["unknown_role_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ===========================================================================
# cross_cutting_complexity_layers / occ_correct_version_finalize_succeeds
# ===========================================================================
def test_occ_correct_version_finalize_succeeds():
    """PRD 2.8: "That request must carry expected_participant_version, a non-optional
    field whose value is the version of the target participant as the client last
    observed it."
    PRD 3.7: "On finalize the payment moves to FINALIZED, total_billed_cents is added to
    the participant's ledger_billed_cents, and the participant's version increments."

    Finalizing with the participant's current version succeeds (FINALIZED) and debits the
    ledger by 630000.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_finalize_succeeds
    """
    program = create_program(lock_in_days=30)
    set_clock("2026-06-15T12:00:00Z")
    _, participant, _ = setup_enrolled_participant(program=program, dual_eligible=True,
                                                   effective_date="2026-06-01")
    payment = create_draft_capitation(participant["id"], "2026-06-01", "FULL_MONTH")
    ver = get_participant_version(participant["id"])
    finalized = get_success_data(api_client.finalize_capitation_payment(
        payment["id"], {"expected_participant_version": ver}, BS))
    assert finalized["status"] == "FINALIZED"
    assert get_success_data(api_client.get_participant(participant["id"], BS))["ledger_billed_cents"] == 630000


# ===========================================================================
# cross_cutting_complexity_layers / occ_stale_version_finalize_rejected
# ===========================================================================
def test_occ_stale_version_finalize_rejected():
    """PRD 2.8: "If expected_participant_version does not match the participant's current
    version at the moment of finalize - for example because a finalize for another month,
    or an enroll/disenroll cascade, has already advanced the participant since the client
    read it - the request is rejected with ERR_STALE_VERSION (HTTP 412), and no shares
    are computed and no ledger is debited."

    Finalizing the first month bumps the participant's version; finalizing the second
    month while still carrying the pre-finalize version is rejected ERR_STALE_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_finalize_rejected
    """
    program = create_program(lock_in_days=30)
    set_clock("2026-08-15T12:00:00Z")
    _, participant, _ = setup_enrolled_participant(program=program, dual_eligible=True,
                                                   effective_date="2026-06-01")
    pv1 = get_participant_version(participant["id"])
    pay1 = create_draft_capitation(participant["id"], "2026-06-01", "FULL_MONTH")
    pay2 = create_draft_capitation(participant["id"], "2026-07-01", "FULL_MONTH")
    get_success_data(api_client.finalize_capitation_payment(
        pay1["id"], {"expected_participant_version": pv1}, BS))

    resp = api_client.finalize_capitation_payment(
        pay2["id"], {"expected_participant_version": pv1}, BS)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ===========================================================================
# cross_cutting_complexity_layers / loc_expiry_blocks_enroll_after_clock_advance
# ===========================================================================
def test_loc_expiry_blocks_enroll_after_clock_advance():
    """PRD 3.2: "When the current clock date is past expires_on, a CERTIFIED assessment is
    treated as EXPIRED for the purposes of any gate that requires certification, so long
    as no newer CERTIFIED assessment exists; this expiry is evaluated at enroll time and
    at capitation-finalize time."
    PRD 3.4: "The participant must have a non-null active_loc_assessment_id pointing at an
    assessment that is CERTIFIED and not past its expires_on as of the current clock date
    (otherwise ERR_LOC_NOT_CERTIFIED)."

    LOC assessed 2026-01-01 with loc_validity_days 30 expires 2026-01-31; after advancing
    the clock to 2026-03-01, enroll is rejected ERR_LOC_NOT_CERTIFIED.

    Design: Corner/cross_cutting_complexity_layers/loc_expiry_blocks_enroll_after_clock_advance
    """
    program = create_program(lock_in_days=30, loc_validity_days=30)
    set_clock("2026-01-05T12:00:00Z")
    participant = create_participant(program["id"])
    create_certified_loc(participant["id"], assessed_on="2026-01-01")
    create_active_care_plan(participant["id"])
    set_clock("2026-03-01T12:00:00Z")
    resp = api_client.enroll_participant(
        participant["id"], {"enrollment_effective_date": "2026-04-01"}, IC)
    validate_error(resp, ApiErrorId.ERR_LOC_NOT_CERTIFIED.value)


# ===========================================================================
# consistency_model / immediate_ledger_visible_in_same_request
# ===========================================================================
def test_immediate_ledger_visible_after_finalize():
    """PRD 2.6: "Whenever a child event changes one of these aggregates - a capitation
    finalize, void, or reconcile; an attendance completion; an enrollment or
    disenrollment - the corresponding derived field is updated so that it never drifts
    from the true total."
    PRD 3.7: "On finalize the payment moves to FINALIZED, total_billed_cents is added to
    the participant's ledger_billed_cents".

    Immediately after finalize, GET participant shows ledger_billed_cents 630000.

    Design: Corner/consistency_model/immediate_ledger_visible_in_same_request
    """
    program = create_program(lock_in_days=30)
    set_clock("2026-06-15T12:00:00Z")
    _, participant, _ = setup_enrolled_participant(program=program, dual_eligible=True,
                                                   effective_date="2026-06-01")
    payment = create_draft_capitation(participant["id"], "2026-06-01", "FULL_MONTH")
    finalize_capitation(payment["id"], participant["id"])
    refreshed = get_success_data(api_client.get_participant(participant["id"], BS))
    assert refreshed["ledger_billed_cents"] == 630000
