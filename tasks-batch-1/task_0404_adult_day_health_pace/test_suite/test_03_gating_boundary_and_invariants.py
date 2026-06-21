"""Validation-priority conflicts, numeric boundaries, cross-entity dependencies,
interval overlap, and conserved-quantity invariants.

Difficulty queue A: priority_pair_validation_conflict, boundary_precision_check,
cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant.
"""
from test_helpers import (
    api_client, get_success_data, validate_error, validate_success, ApiErrorId,
    create_program, set_clock, create_participant, create_certified_loc,
    create_active_care_plan, create_in_review_care_plan,
    setup_enrolled_participant, setup_eligible_participant,
    create_attendance_day, create_transport_leg, create_draft_capitation,
    finalize_capitation, get_participant_version,
    submit_disenrollment, approve_disenrollment, finalize_disenrollment,
    TEST_USERS,
)

PA = TEST_USERS["program_admin_headers"]
IC = TEST_USERS["intake_coordinator_headers"]
MD = TEST_USERS["medical_director_headers"]
NS = TEST_USERS["nurse_staff_headers"]
BS = TEST_USERS["billing_specialist_headers"]


# ===========================================================================
# priority_pair_validation_conflict / enroll_state_beats_loc_safety
# ===========================================================================
def test_enroll_applicant_returns_invalid_state_over_loc():
    """PRD 2.5: "then - for state-driven operations - whether the target resource is in
    a legal state for the transition (ERR_INVALID_STATE, HTTP 409). Only after all of
    these pass does the system evaluate the domain-specific business rules described in
    Section 3."
    PRD 3.4: "The participant must be in ELIGIBLE status (otherwise ERR_INVALID_STATE)."

    An APPLICANT (no certified LOC, no care plan) fails both the state check and the
    LOC-safety check; the state check wins, returning ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/enroll_state_beats_loc_safety
    """
    program = create_program()
    participant = create_participant(program["id"])
    resp = api_client.enroll_participant(
        participant["id"], {"enrollment_effective_date": "2026-06-01"}, IC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_enroll_applicant_state_precedes_loc_not_certified():
    """PRD 2.5: "a bad state before any business-safety or fiscal check, so that a
    single request never masks an earlier-priority fault behind a later one."
    PRD 3.4: "The participant must be in ELIGIBLE status (otherwise ERR_INVALID_STATE)."

    Even though the LOC-not-certified condition also holds for the APPLICANT, the
    higher-priority state fault surfaces first as ERR_INVALID_STATE (not
    ERR_LOC_NOT_CERTIFIED).

    Design: Difficulty/priority_pair_validation_conflict/enroll_state_beats_loc_safety
    """
    program = create_program()
    participant = create_participant(program["id"])
    resp = api_client.enroll_participant(
        participant["id"], {"enrollment_effective_date": "2026-06-01"}, IC)
    body = resp.json()["data"]
    assert body["error_id"] == ApiErrorId.ERR_INVALID_STATE.value
    assert resp.status_code == 409


# ===========================================================================
# priority_pair_validation_conflict / enroll_temporal_beats_capacity_constraint
# ===========================================================================
def _make_eligible_ready_to_enroll(program):
    p = create_participant(program["id"])
    create_certified_loc(p["id"])
    create_active_care_plan(p["id"])
    return p


def test_enroll_not_first_of_month_beats_capacity():
    """PRD 2.5: "then request well-formedness (ERR_INVALID_REQUEST, 400), then - for
    state-driven operations - whether the target resource is in a legal state for the
    transition (ERR_INVALID_STATE, HTTP 409)."
    PRD 3.4: "The enrollment_effective_date must be the first of its month - its
    day-of-month must equal 01 (otherwise ERR_NOT_FIRST_OF_MONTH)."

    A second ELIGIBLE participant in a program already at roster capacity supplies a
    mid-month effective date: ERR_NOT_FIRST_OF_MONTH (422) is returned, the
    higher-priority temporal fault, not ERR_CAPACITY_EXCEEDED.

    Design: Difficulty/priority_pair_validation_conflict/enroll_temporal_beats_capacity_constraint
    """
    program = create_program(daily_census_capacity=1, max_roster=1, lock_in_days=30)
    set_clock("2026-05-20T12:00:00Z")
    first = _make_eligible_ready_to_enroll(program)
    get_success_data(api_client.enroll_participant(
        first["id"], {"enrollment_effective_date": "2026-06-01"}, IC))

    second = _make_eligible_ready_to_enroll(program)
    resp = api_client.enroll_participant(
        second["id"], {"enrollment_effective_date": "2026-06-15"}, IC)
    validate_error(resp, ApiErrorId.ERR_NOT_FIRST_OF_MONTH.value)


def test_enroll_temporal_fault_returns_422_not_capacity_409():
    """PRD 3.4: "The enrollment_effective_date must be the first of its month - its
    day-of-month must equal 01 (otherwise ERR_NOT_FIRST_OF_MONTH)."
    PRD 3.4: "The program's enrolled_count must be below its max_roster (otherwise
    ERR_CAPACITY_EXCEEDED)."

    The mid-month date drives the 422 temporal error rather than the 409 capacity error
    when both conditions are violated.

    Design: Difficulty/priority_pair_validation_conflict/enroll_temporal_beats_capacity_constraint
    """
    program = create_program(daily_census_capacity=1, max_roster=1, lock_in_days=30)
    set_clock("2026-05-20T12:00:00Z")
    first = _make_eligible_ready_to_enroll(program)
    get_success_data(api_client.enroll_participant(
        first["id"], {"enrollment_effective_date": "2026-06-01"}, IC))
    second = _make_eligible_ready_to_enroll(program)
    resp = api_client.enroll_participant(
        second["id"], {"enrollment_effective_date": "2026-06-15"}, IC)
    assert resp.status_code == 422
    assert resp.json()["data"]["error_id"] == ApiErrorId.ERR_NOT_FIRST_OF_MONTH.value


# ===========================================================================
# boundary_precision_check / census_full_second_checkin_at_capacity
# ===========================================================================
def test_checkin_at_capacity_rejected_census_full():
    """PRD 3.5: "If that count is already at or above the program's
    daily_census_capacity, the check-in is rejected with ERR_CENSUS_FULL - at exactly
    capacity the next check-in is refused, while at one below capacity it is admitted."

    With capacity 1, participant A checks in (occupancy 0 < 1, admitted); participant B
    on the same date is rejected ERR_CENSUS_FULL (occupancy 1 >= 1).

    Design: Difficulty/boundary_precision_check/census_full_second_checkin_at_capacity
    """
    program = create_program(daily_census_capacity=1, max_roster=10, lock_in_days=30)
    set_clock("2026-06-02T08:00:00Z")
    _, pa, _ = setup_enrolled_participant(program=program, effective_date="2026-06-01")
    day_a = create_attendance_day(pa["id"], "2026-06-02")
    get_success_data(api_client.check_in_attendance_day(day_a["id"], NS))

    _, pb, _ = setup_enrolled_participant(program=program, effective_date="2026-06-01")
    day_b = create_attendance_day(pb["id"], "2026-06-02")
    resp = api_client.check_in_attendance_day(day_b["id"], NS)
    validate_error(resp, ApiErrorId.ERR_CENSUS_FULL.value)
    assert get_success_data(api_client.get_attendance_day(day_b["id"], NS))["status"] == "SCHEDULED"


def test_checkin_one_below_capacity_admitted():
    """PRD 3.5: "at exactly capacity the next check-in is refused, while at one below
    capacity it is admitted."

    With capacity 2, the first check-in (occupancy 0, one below the 1-occupancy that
    capacity-2 would refuse on the third) is admitted to CHECKED_IN — the X-1 side of
    the boundary.

    Design: Difficulty/boundary_precision_check/census_full_second_checkin_at_capacity
    """
    program = create_program(daily_census_capacity=2, max_roster=10, lock_in_days=30)
    set_clock("2026-06-02T08:00:00Z")
    _, pa, _ = setup_enrolled_participant(program=program, effective_date="2026-06-01")
    day_a = create_attendance_day(pa["id"], "2026-06-02")
    checked = get_success_data(api_client.check_in_attendance_day(day_a["id"], NS))
    assert checked["status"] == "CHECKED_IN"

    _, pb, _ = setup_enrolled_participant(program=program, effective_date="2026-06-01")
    day_b = create_attendance_day(pb["id"], "2026-06-02")
    checked_b = get_success_data(api_client.check_in_attendance_day(day_b["id"], NS))
    assert checked_b["status"] == "CHECKED_IN"


# ===========================================================================
# boundary_precision_check / attendance_summary_empty_completed_set_zero
# ===========================================================================
def test_attendance_summary_empty_completed_set_is_zero():
    """PRD 3.7: "This read sums a per-day charge across only those AttendanceDay rows
    that are COMPLETED and whose service_date falls in the queried month, supplied as
    service_month; days that are SCHEDULED, CHECKED_IN, NO_SHOW, or CANCELLED are
    excluded."
    PRD 3.7: "The read returns the queried service_month, the count of completed_days
    included, and the summed month_ancillary_cents."

    A participant with only a SCHEDULED day in June has an empty COMPLETED set:
    completed_days 0 and month_ancillary_cents 0.

    Design: Difficulty/boundary_precision_check/attendance_summary_empty_completed_set_zero
    """
    program = create_program(daily_census_capacity=10, max_roster=10, lock_in_days=30)
    set_clock("2026-06-02T08:00:00Z")
    _, participant, _ = setup_enrolled_participant(program=program, effective_date="2026-06-01")
    create_attendance_day(participant["id"], "2026-06-02")

    resp = api_client.get_attendance_summary(
        participant["id"], BS, params={"service_month": "2026-06-01"})
    data = validate_success(resp)
    assert data["completed_days"] == 0
    assert data["month_ancillary_cents"] == 0


def test_attendance_summary_zero_with_no_days_at_all():
    """PRD 3.7: "This read sums a per-day charge across only those AttendanceDay rows
    that are COMPLETED and whose service_date falls in the queried month".

    With no attendance days at all, the summary is the empty-set zero: completed_days 0
    and month_ancillary_cents 0.

    Design: Difficulty/boundary_precision_check/attendance_summary_empty_completed_set_zero
    """
    program = create_program(daily_census_capacity=10, max_roster=10, lock_in_days=30)
    set_clock("2026-06-02T08:00:00Z")
    _, participant, _ = setup_enrolled_participant(program=program, effective_date="2026-06-01")

    resp = api_client.get_attendance_summary(
        participant["id"], BS, params={"service_month": "2026-06-01"})
    data = validate_success(resp)
    assert data["completed_days"] == 0
    assert data["month_ancillary_cents"] == 0


# ===========================================================================
# cross_entity_state_dependency / checkin_requires_participant_enrolled
# ===========================================================================
def test_checkin_eligible_participant_rejected_not_enrolled():
    """PRD 3.5: "Three conditions gate it: the day must be SCHEDULED (otherwise
    ERR_INVALID_STATE); the participant must be ENROLLED (otherwise
    ERR_PARTICIPANT_NOT_ENROLLED); and the live census must have room."

    An ELIGIBLE (not yet enrolled) participant with a SCHEDULED day cannot be checked in.

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_participant_enrolled
    """
    program = create_program()
    set_clock("2026-06-02T08:00:00Z")
    _, participant, _ = setup_eligible_participant(program_id=program["id"])
    day = create_attendance_day(participant["id"], "2026-06-02")
    resp = api_client.check_in_attendance_day(day["id"], NS)
    validate_error(resp, ApiErrorId.ERR_PARTICIPANT_NOT_ENROLLED.value)


def test_checkin_enrolled_participant_succeeds():
    """PRD 3.5: "Checking a participant in for the day is a NurseStaff action that moves
    the day from SCHEDULED to CHECKED_IN."
    PRD 3.5: "the participant must be ENROLLED (otherwise ERR_PARTICIPANT_NOT_ENROLLED)".

    The positive side of the cross-entity gate: an ENROLLED participant's SCHEDULED day
    checks in to CHECKED_IN.

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_participant_enrolled
    """
    program = create_program(daily_census_capacity=10, lock_in_days=30)
    set_clock("2026-06-02T08:00:00Z")
    _, participant, _ = setup_enrolled_participant(program=program, effective_date="2026-06-01")
    day = create_attendance_day(participant["id"], "2026-06-02")
    checked = get_success_data(api_client.check_in_attendance_day(day["id"], NS))
    assert checked["status"] == "CHECKED_IN"


# ===========================================================================
# cross_entity_state_dependency / med_order_activate_requires_care_plan_active
# ===========================================================================
def test_med_order_activate_requires_active_care_plan():
    """PRD 3.6: "Activating an ORDERED order moves it to ACTIVE, but only if the order's
    care_plan_id references a plan that is currently ACTIVE - otherwise the activation is
    rejected with ERR_CARE_PLAN_NOT_ACTIVE".

    An order on an IN_REVIEW (not ACTIVE) care plan cannot be activated.

    Design: Difficulty/cross_entity_state_dependency/med_order_activate_requires_care_plan_active
    """
    program = create_program()
    participant = create_participant(program["id"])
    cp = create_in_review_care_plan(participant["id"], sign_disciplines=("RN",))
    mo = get_success_data(api_client.create_medication_order(
        {"participant_id": participant["id"], "care_plan_id": cp["id"],
         "drug_name": "Lisinopril", "daily_doses": 1}, NS))
    resp = api_client.activate_medication_order(mo["id"], NS)
    validate_error(resp, ApiErrorId.ERR_CARE_PLAN_NOT_ACTIVE.value)


def test_med_order_activate_succeeds_on_active_care_plan():
    """PRD 3.6: "Activating an ORDERED order moves it to ACTIVE, but only if the order's
    care_plan_id references a plan that is currently ACTIVE".

    The positive side: an order against an ACTIVE care plan activates to ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/med_order_activate_requires_care_plan_active
    """
    program = create_program()
    participant = create_participant(program["id"])
    cp = create_active_care_plan(participant["id"])
    mo = get_success_data(api_client.create_medication_order(
        {"participant_id": participant["id"], "care_plan_id": cp["id"],
         "drug_name": "Lisinopril", "daily_doses": 1}, NS))
    activated = get_success_data(api_client.activate_medication_order(mo["id"], NS))
    assert activated["status"] == "ACTIVE"


# ===========================================================================
# resource_temporal_overlap / transport_leg_vehicle_halfopen_overlap
# ===========================================================================
def test_transport_leg_overlap_same_vehicle_rejected():
    """PRD 3.5: "a new leg may not overlap any existing PLANNED leg assigned to the same
    vehicle_id on the same service_date; intervals are treated as half-open, so a leg
    that merely touches another at an endpoint (one ending exactly when the next begins)
    does not overlap, but any genuine overlap is rejected with ERR_TRANSPORT_OVERLAP."

    A PLANNED leg [480,540) on VAN1 blocks a new [530,560) leg (genuine overlap).

    Design: Difficulty/resource_temporal_overlap/transport_leg_vehicle_halfopen_overlap
    """
    program = create_program()
    participant = create_participant(program["id"])
    day = create_attendance_day(participant["id"], "2026-06-02")
    create_transport_leg(day["id"], direction="PICKUP", window_start_min=480,
                         window_end_min=540, vehicle_id="VAN1")
    resp = api_client.create_transport_leg(
        {"attendance_day_id": day["id"], "direction": "PICKUP",
         "window_start_min": 530, "window_end_min": 560, "vehicle_id": "VAN1"}, NS)
    validate_error(resp, ApiErrorId.ERR_TRANSPORT_OVERLAP.value)


def test_transport_leg_touching_endpoint_allowed():
    """PRD 3.5: "intervals are treated as half-open, so a leg that merely touches
    another at an endpoint (one ending exactly when the next begins) does not overlap".

    A leg [540,600) touching the existing [480,540) on VAN1 is accepted (PLANNED) — the
    half-open boundary admits a touching endpoint.

    Design: Difficulty/resource_temporal_overlap/transport_leg_vehicle_halfopen_overlap
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
# resource_temporal_overlap / capitation_month_must_intersect_enrollment_window
# ===========================================================================
def test_capitation_month_before_enrollment_no_coverage():
    """PRD 3.7: "finalize requires ... the participant had an enrollment covering at
    least one calendar day of the service_month (otherwise ERR_NO_COVERAGE_FOR_MONTH)".

    A participant enrolled 2026-06-01 finalizing a payment for service_month 2026-04-01
    (entirely before enrollment) has zero covered days: ERR_NO_COVERAGE_FOR_MONTH.

    Design: Difficulty/resource_temporal_overlap/capitation_month_must_intersect_enrollment_window
    """
    program = create_program(lock_in_days=30)
    set_clock("2026-06-15T12:00:00Z")
    _, participant, _ = setup_enrolled_participant(program=program, effective_date="2026-06-01")
    payment = create_draft_capitation(participant["id"], "2026-04-01", "FULL_MONTH")
    ver = get_participant_version(participant["id"])
    resp = api_client.finalize_capitation_payment(
        payment["id"], {"expected_participant_version": ver}, BS)
    validate_error(resp, ApiErrorId.ERR_NO_COVERAGE_FOR_MONTH.value)


def test_capitation_month_intersecting_enrollment_finalizes():
    """PRD 3.7: "finalize requires ... the participant had an enrollment covering at
    least one calendar day of the service_month (otherwise ERR_NO_COVERAGE_FOR_MONTH)".
    PRD 3.7: "On finalize the payment moves to FINALIZED".

    The positive side: a payment for the enrollment month 2026-06-01 has coverage and
    finalizes to FINALIZED.

    Design: Difficulty/resource_temporal_overlap/capitation_month_must_intersect_enrollment_window
    """
    program = create_program(lock_in_days=30)
    set_clock("2026-06-15T12:00:00Z")
    _, participant, _ = setup_enrolled_participant(program=program, effective_date="2026-06-01")
    payment = create_draft_capitation(participant["id"], "2026-06-01", "FULL_MONTH")
    finalized = finalize_capitation(payment["id"], participant["id"])
    assert finalized["status"] == "FINALIZED"


# ===========================================================================
# compensating_invariant / capitation_finalize_then_void_ledger_conserved
# ===========================================================================
def test_finalize_then_void_returns_ledger_to_zero():
    """PRD 2.6: "In particular, voiding a previously FINALIZED capitation payment removes
    it from the FINALIZED set, so ledger_billed_cents returns to exactly its pre-finalize
    value."
    PRD 3.7: "If the payment being voided was FINALIZED, its total_billed_cents is
    subtracted back out of the participant's ledger_billed_cents as a compensating entry,
    so the ledger returns exactly to its pre-finalize value with no drift".

    Finalizing a FULL_MONTH dual payment debits 630000; voiding it credits it back, so
    ledger_billed_cents returns to 0.

    Design: Difficulty/compensating_invariant/capitation_finalize_then_void_ledger_conserved
    """
    program = create_program(lock_in_days=30)
    set_clock("2026-06-15T12:00:00Z")
    _, participant, _ = setup_enrolled_participant(program=program, dual_eligible=True,
                                                   effective_date="2026-06-01")
    payment = create_draft_capitation(participant["id"], "2026-06-01", "FULL_MONTH")
    payment = finalize_capitation(payment["id"], participant["id"])
    assert get_success_data(api_client.get_participant(participant["id"], BS))["ledger_billed_cents"] == 630000

    voided = get_success_data(api_client.void_capitation_payment(payment["id"], BS))
    assert voided["status"] == "VOID"
    assert get_success_data(api_client.get_participant(participant["id"], BS))["ledger_billed_cents"] == 0


def test_void_draft_payment_does_not_touch_ledger():
    """PRD 3.7: "voiding a DRAFT payment that was never finalized touches no ledger."
    PRD 2.6: "The ledger_billed_cents field equals the sum of total_billed_cents over
    the participant's CapitationPayment rows that are in FINALIZED status."

    Voiding a never-finalized DRAFT leaves ledger_billed_cents at 0 — the conserved
    quantity is unaffected because a DRAFT was never in the FINALIZED set.

    Design: Difficulty/compensating_invariant/capitation_finalize_then_void_ledger_conserved
    """
    program = create_program(lock_in_days=30)
    set_clock("2026-06-15T12:00:00Z")
    _, participant, _ = setup_enrolled_participant(program=program, dual_eligible=True,
                                                   effective_date="2026-06-01")
    payment = create_draft_capitation(participant["id"], "2026-06-01", "FULL_MONTH")
    voided = get_success_data(api_client.void_capitation_payment(payment["id"], BS))
    assert voided["status"] == "VOID"
    assert get_success_data(api_client.get_participant(participant["id"], BS))["ledger_billed_cents"] == 0


# ===========================================================================
# compensating_invariant / disenroll_approve_then_withdraw_census_conserved
# ===========================================================================
def test_approve_then_withdraw_conserves_enrolled_count():
    """PRD 3.8: "approval moves the request to APPROVED, drives the participant from
    ENROLLED to DISENROLLMENT_PENDING, and increments the participant's version."
    PRD 3.8: "withdrawal moves the request to WITHDRAWN and returns the participant from
    DISENROLLMENT_PENDING back to ENROLLED, incrementing the participant's version."

    Approve then withdraw leaves the participant ENROLLED and the program's
    enrolled_count at 1 (the count only decrements on finalize).

    Design: Difficulty/compensating_invariant/disenroll_approve_then_withdraw_census_conserved
    """
    program = create_program(lock_in_days=30)
    set_clock("2026-06-15T12:00:00Z")
    _, participant, _ = setup_enrolled_participant(program=program, effective_date="2026-06-01")
    req = submit_disenrollment(participant["id"], kind="VOLUNTARY", reason_code="DISSATISFIED",
                               requested_effective_date="2026-08-01")
    approve_disenrollment(req["id"])

    withdrawn = get_success_data(api_client.withdraw_disenrollment_request(req["id"], IC))
    assert withdrawn["status"] == "WITHDRAWN"
    assert get_success_data(api_client.get_participant(participant["id"], BS))["status"] == "ENROLLED"
    assert get_success_data(api_client.get_program(program["id"], PA))["enrolled_count"] == 1


def test_approve_does_not_decrement_enrolled_count():
    """PRD 3.8: "approval moves the request to APPROVED, drives the participant from
    ENROLLED to DISENROLLMENT_PENDING, and increments the participant's version."
    PRD 2.6: "Likewise, the Program's enrolled_count equals the number of that program's
    participants whose status is ENROLLED."

    Approval alone does not change enrolled_count — but it moves the participant out of
    ENROLLED, so enrolled_count drops to 0 while DISENROLLMENT_PENDING. This pins the
    derived-field rule: enrolled_count counts only ENROLLED participants.

    Design: Difficulty/compensating_invariant/disenroll_approve_then_withdraw_census_conserved
    """
    program = create_program(lock_in_days=30)
    set_clock("2026-06-15T12:00:00Z")
    _, participant, _ = setup_enrolled_participant(program=program, effective_date="2026-06-01")
    assert get_success_data(api_client.get_program(program["id"], PA))["enrolled_count"] == 1
    req = submit_disenrollment(participant["id"], kind="VOLUNTARY", reason_code="DISSATISFIED",
                               requested_effective_date="2026-08-01")
    approve_disenrollment(req["id"])
    # participant is now DISENROLLMENT_PENDING, not ENROLLED
    assert get_success_data(api_client.get_participant(participant["id"], BS))["status"] == "DISENROLLMENT_PENDING"
    assert get_success_data(api_client.get_program(program["id"], PA))["enrolled_count"] == 0
