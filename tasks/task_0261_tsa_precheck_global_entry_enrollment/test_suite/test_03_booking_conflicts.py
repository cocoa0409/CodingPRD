"""Appointment booking constraints: slot availability, suspended centers, lane
buffer overlap, daily capacity, KTN coverage overlap, and validation precedence.

Translates difficulty queue A instances for boundary_precision_check (daily
capacity), priority_pair_validation_conflict (slot vs overlap), and
resource_temporal_overlap, plus corner queue B validation and cascade instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_applicant_headers, TEST_USERS, ApiErrorId,
    pay_payload, background_check_payload, appointment_payload, biometric_payload,
    setup_confirmed_appointment, setup_cleared_application_at_center,
    setup_approved_application,
    get_application, app_version,
    create_program, create_applicant, create_center, create_slot,
    create_draft_application, set_clock,
)

ADMIN = TEST_USERS["scheduling_admin_headers"]
VETTING = TEST_USERS["vetting_officer_headers"]
ENROLLMENT = TEST_USERS["enrollment_officer_headers"]


# ---------------------------------------------------------------------------
# Queue A — boundary_precision_check (daily capacity)
# ---------------------------------------------------------------------------

def test_daily_capacity_exact_boundary_rejects_next(api):
    """PRD §3.5: "counting the `CONFIRMED` appointments at the same center whose
    slot starts on the same UTC calendar date as the requested slot, the booking
    is rejected with `ERR_DAILY_CAPACITY_EXCEEDED` when that count is already at
    the center's `daily_interview_capacity`."

    Design: Difficulty/boundary_precision_check/daily_capacity_exact_boundary_on_appointments
    """
    set_clock()
    program = create_program()
    center = create_center(daily_interview_capacity=1, lane_count=2, buffer_minutes=0)
    slot1 = create_slot(center["id"], lane_index=0,
                        starts_at="2026-06-23T09:00:00Z", ends_at="2026-06-23T09:30:00Z")
    slot2 = create_slot(center["id"], lane_index=1,
                        starts_at="2026-06-23T14:00:00Z", ends_at="2026-06-23T14:30:00Z")
    applicant1, app1 = setup_cleared_application_at_center(center["id"],
                                                           {"full_name": "Leo Cap1"})
    h1 = make_applicant_headers(applicant1["id"])
    v1 = app_version(app1["id"])
    # 1st booking on the date succeeds (used 0 < 1).
    validate_success(
        api.create_appointment(appointment_payload(app1["id"], slot1["id"], v1), h1),
        expected_status=201,
    )
    applicant2, app2 = setup_cleared_application_at_center(center["id"],
                                                           {"full_name": "Mia Cap2"})
    h2 = make_applicant_headers(applicant2["id"])
    v2 = app_version(app2["id"])
    # 2nd booking on the same date is rejected (used 1 >= 1).
    resp = api.create_appointment(appointment_payload(app2["id"], slot2["id"], v2), h2)
    validate_error(resp, ApiErrorId.ERR_DAILY_CAPACITY_EXCEEDED.value)


def test_daily_capacity_first_booking_succeeds(api):
    """PRD §3.5: "the capacity-th confirmed appointment fills the day and the next
    one is refused."

    Design: Difficulty/boundary_precision_check/daily_capacity_exact_boundary_on_appointments
    """
    set_clock()
    program = create_program()
    center = create_center(daily_interview_capacity=1, lane_count=2, buffer_minutes=0)
    slot1 = create_slot(center["id"], lane_index=0,
                        starts_at="2026-06-23T09:00:00Z", ends_at="2026-06-23T09:30:00Z")
    applicant1, app1 = setup_cleared_application_at_center(center["id"])
    h1 = make_applicant_headers(applicant1["id"])
    v1 = app_version(app1["id"])
    appt = validate_success(
        api.create_appointment(appointment_payload(app1["id"], slot1["id"], v1), h1),
        expected_status=201,
    )
    assert appt["status"] == "CONFIRMED", "first booking (used 0 < 1) succeeds"


# ---------------------------------------------------------------------------
# Queue A — resource_temporal_overlap (lane buffer)
# ---------------------------------------------------------------------------

def test_lane_buffer_expanded_overlap_rejected(api):
    """PRD §3.5: "no same-lane confirmed appointment may collide with the requested
    window once that window is expanded by the center's `buffer_minutes`: the
    requested slot's half-open interval, grown by the buffer, must not overlap the
    interval of any other `CONFIRMED` appointment on the same lane, and a collision
    is rejected with `ERR_SLOT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/lane_buffer_expanded_overlap_half_open
    """
    set_clock()
    program = create_program()
    center = create_center(daily_interview_capacity=10, lane_count=1, buffer_minutes=30)
    slot1 = create_slot(center["id"], lane_index=0,
                        starts_at="2026-06-26T09:00:00Z", ends_at="2026-06-26T09:30:00Z")
    slot2 = create_slot(center["id"], lane_index=0,
                        starts_at="2026-06-26T09:40:00Z", ends_at="2026-06-26T10:10:00Z")
    applicant1, app1 = setup_cleared_application_at_center(center["id"],
                                                           {"full_name": "Quin A"})
    h1 = make_applicant_headers(applicant1["id"])
    v1 = app_version(app1["id"])
    validate_success(
        api.create_appointment(appointment_payload(app1["id"], slot1["id"], v1), h1),
        expected_status=201,
    )
    applicant2, app2 = setup_cleared_application_at_center(center["id"],
                                                           {"full_name": "Rex B"})
    h2 = make_applicant_headers(applicant2["id"])
    v2 = app_version(app2["id"])
    # 09:00-09:30 + 30min buffer -> busy to 10:00; slot2 starts 09:40 collides.
    resp = api.create_appointment(appointment_payload(app2["id"], slot2["id"], v2), h2)
    validate_error(resp, ApiErrorId.ERR_SLOT_OVERLAP.value)


def test_lane_buffer_non_overlapping_slot_books_successfully(api):
    """PRD §3.5: "the requested slot's half-open interval, grown by the buffer, must
    not overlap the interval of any other `CONFIRMED` appointment on the same lane,
    and a collision is rejected with `ERR_SLOT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/lane_buffer_expanded_overlap_half_open
    """
    set_clock()
    program = create_program()
    center = create_center(daily_interview_capacity=10, lane_count=1, buffer_minutes=30)
    slot1 = create_slot(center["id"], lane_index=0,
                        starts_at="2026-06-26T09:00:00Z", ends_at="2026-06-26T09:30:00Z")
    # slot2 starts 10:00, exactly at the end of the buffered busy window [09:00,10:00);
    # half-open semantics mean 10:00 does not collide.
    slot2 = create_slot(center["id"], lane_index=0,
                        starts_at="2026-06-26T10:00:00Z", ends_at="2026-06-26T10:30:00Z")
    applicant1, app1 = setup_cleared_application_at_center(center["id"],
                                                           {"full_name": "Quin C"})
    h1 = make_applicant_headers(applicant1["id"])
    v1 = app_version(app1["id"])
    validate_success(
        api.create_appointment(appointment_payload(app1["id"], slot1["id"], v1), h1),
        expected_status=201,
    )
    applicant2, app2 = setup_cleared_application_at_center(center["id"],
                                                           {"full_name": "Rex D"})
    h2 = make_applicant_headers(applicant2["id"])
    v2 = app_version(app2["id"])
    appt2 = validate_success(
        api.create_appointment(appointment_payload(app2["id"], slot2["id"], v2), h2),
        expected_status=201,
    )
    assert appt2["status"] == "CONFIRMED", (
        "a slot starting at the buffer boundary (10:00) does not overlap"
    )


# ---------------------------------------------------------------------------
# Queue A — resource_temporal_overlap (KTN coverage closed interval)
# ---------------------------------------------------------------------------

def test_ktn_coverage_overlap_blocks_second_approval(api):
    """PRD §3.6: "The credential about to be issued carries a closed coverage
    interval from its `issued_at` to its `expires_at`; that interval must not
    overlap the coverage interval of any existing `ACTIVE` credential for the same
    `applicant_id` and `program_code`. Because the interval is closed, sharing an
    endpoint counts as an overlap... A disallowed overlap is rejected with
    `ERR_KTN_COVERAGE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/ktn_coverage_closed_interval_overlap
    """
    # First application approved -> ACTIVE KTN covering 2026-06-09..2031-06-09.
    program, applicant, app1, center, slot1, _appt1, ktn1 = setup_approved_application()
    assert ktn1["status"] == "ACTIVE"
    # Second independent (non-renewal) PRECHECK application for the SAME applicant.
    h = make_applicant_headers(applicant["id"])
    slot2 = create_slot(center["id"], lane_index=0,
                        starts_at="2026-06-28T09:00:00Z", ends_at="2026-06-28T09:30:00Z")
    app2 = create_draft_application(applicant["id"])
    get_success_data(api.pay_application(app2["id"], pay_payload(7800), h))
    get_success_data(api.submit_application(app2["id"], h))
    get_success_data(
        api.create_background_check(app2["id"], background_check_payload(criminal_hits=1), VETTING)
    )
    get_success_data(api.adjudicate(app2["id"], VETTING))
    v2 = app_version(app2["id"])
    appt2 = get_success_data(
        api.create_appointment(appointment_payload(app2["id"], slot2["id"], v2), h)
    )
    get_success_data(api.create_biometric_capture(biometric_payload(appt2["id"]), ENROLLMENT))
    get_success_data(api.complete_appointment(appt2["id"], ENROLLMENT))
    resp = api.approve_application(app2["id"], ENROLLMENT)
    validate_error(resp, ApiErrorId.ERR_KTN_COVERAGE_OVERLAP.value)
    final_app2 = get_application(app2["id"])
    assert final_app2["status"] == "INTERVIEW_COMPLETE", (
        "blocked approval leaves the second application in INTERVIEW_COMPLETE"
    )


def test_valid_renewal_permitted_despite_coverage_overlap(api):
    """PRD §3.6: "The single exception is a valid renewal: when this application
    renews the application that produced the existing credential, the overlap is
    permitted and the prior credential is superseded rather than blocking issuance."

    Design: Difficulty/resource_temporal_overlap/ktn_coverage_closed_interval_overlap
    """
    # First application approved -> ACTIVE KTN covering 2026-06-09..2031-06-09.
    program, applicant, prior_app, center, slot1, _appt1, ktn1 = setup_approved_application(
        program_overrides={"validity_years": 5, "renewal_window_days": 180}
    )
    # Move into the renewal window (window opens 2030-12-11; KTN still ACTIVE).
    set_clock("2031-03-01T00:00:00Z")
    h = make_applicant_headers(applicant["id"])
    slot2 = create_slot(center["id"], lane_index=0,
                        starts_at="2031-03-05T09:00:00Z", ends_at="2031-03-05T09:30:00Z")
    renewal = create_draft_application(applicant["id"],
                                       renews_from_application_id=prior_app["id"])
    get_success_data(api.pay_application(renewal["id"], pay_payload(7800), h))
    get_success_data(api.submit_application(renewal["id"], h))
    get_success_data(
        api.create_background_check(renewal["id"], background_check_payload(criminal_hits=1), VETTING)
    )
    get_success_data(api.adjudicate(renewal["id"], VETTING))
    v = app_version(renewal["id"])
    appt2 = get_success_data(
        api.create_appointment(appointment_payload(renewal["id"], slot2["id"], v), h)
    )
    get_success_data(api.create_biometric_capture(biometric_payload(appt2["id"]), ENROLLMENT))
    get_success_data(api.complete_appointment(appt2["id"], ENROLLMENT))
    approved = validate_success(
        api.approve_application(renewal["id"], ENROLLMENT), expected_status=200
    )
    assert approved["status"] == "APPROVED", "valid renewal is approved despite overlap"
    prior_ktn = get_success_data(api.get_ktn(ktn1["id"], ADMIN))
    assert prior_ktn["status"] == "SUPERSEDED", "the prior ACTIVE KTN is superseded"


# ---------------------------------------------------------------------------
# Queue A — priority_pair_validation_conflict (slot availability vs overlap)
# ---------------------------------------------------------------------------

def test_slot_not_available_precedes_overlap_check(api):
    """PRD §3.5: "The target slot must be `AVAILABLE`, or the booking is rejected
    with `ERR_SLOT_NOT_AVAILABLE`. The slot's center must be `OPEN`... Two capacity
    rules then apply."

    Design: Difficulty/priority_pair_validation_conflict/slot_not_available_beats_overlap_on_appointments
    """
    set_clock()
    program = create_program()
    center = create_center(daily_interview_capacity=10, lane_count=1, buffer_minutes=30)
    slot1 = create_slot(center["id"], lane_index=0,
                        starts_at="2026-06-22T09:00:00Z", ends_at="2026-06-22T09:30:00Z")
    slot2 = create_slot(center["id"], lane_index=0,
                        starts_at="2026-06-22T09:40:00Z", ends_at="2026-06-22T10:10:00Z")
    applicant1, app1 = setup_cleared_application_at_center(center["id"],
                                                           {"full_name": "Jack One"})
    h1 = make_applicant_headers(applicant1["id"])
    v1 = app_version(app1["id"])
    validate_success(
        api.create_appointment(appointment_payload(app1["id"], slot1["id"], v1), h1),
        expected_status=201,
    )
    # Release slot2: now booking it fails BOTH availability (RELEASED) and overlap
    # (within 30-min buffer of slot1's 09:30 end). Availability wins.
    get_success_data(api.release_slot(slot2["id"], ADMIN))
    applicant2, app2 = setup_cleared_application_at_center(center["id"],
                                                           {"full_name": "Kira Two"})
    h2 = make_applicant_headers(applicant2["id"])
    v2 = app_version(app2["id"])
    resp = api.create_appointment(appointment_payload(app2["id"], slot2["id"], v2), h2)
    validate_error(resp, ApiErrorId.ERR_SLOT_NOT_AVAILABLE.value)


def test_released_slot_inside_buffer_window_reports_unavailable(api):
    """PRD §3.5: "The target slot must be `AVAILABLE`, or the booking is rejected
    with `ERR_SLOT_NOT_AVAILABLE`. The slot's center must be `OPEN`... Two capacity
    rules then apply."

    Design: Difficulty/priority_pair_validation_conflict/slot_not_available_beats_overlap_on_appointments
    """
    # Distinct geometry from the first test: the colliding RELEASED slot sits
    # immediately before the confirmed appointment (buffer extends backward too).
    set_clock()
    program = create_program()
    center = create_center(daily_interview_capacity=10, lane_count=1, buffer_minutes=30)
    slot_busy = create_slot(center["id"], lane_index=0,
                            starts_at="2026-06-25T10:00:00Z", ends_at="2026-06-25T10:30:00Z")
    # slot_early ends 09:50, only 10 min before slot_busy's 10:00 start -> within the
    # 30-min buffer, so it would also collide.
    slot_early = create_slot(center["id"], lane_index=0,
                             starts_at="2026-06-25T09:20:00Z", ends_at="2026-06-25T09:50:00Z")
    applicant1, app1 = setup_cleared_application_at_center(center["id"],
                                                           {"full_name": "Jack Three"})
    h1 = make_applicant_headers(applicant1["id"])
    v1 = app_version(app1["id"])
    validate_success(
        api.create_appointment(appointment_payload(app1["id"], slot_busy["id"], v1), h1),
        expected_status=201,
    )
    # Release slot_early: booking it now fails BOTH availability (RELEASED, terminal)
    # and the same-lane buffer overlap. Availability is checked first.
    get_success_data(api.release_slot(slot_early["id"], ADMIN))
    applicant2, app2 = setup_cleared_application_at_center(center["id"],
                                                           {"full_name": "Kira Four"})
    h2 = make_applicant_headers(applicant2["id"])
    v2 = app_version(app2["id"])
    resp = api.create_appointment(appointment_payload(app2["id"], slot_early["id"], v2), h2)
    validate_error(resp, ApiErrorId.ERR_SLOT_NOT_AVAILABLE.value)


# ---------------------------------------------------------------------------
# Queue B — validations: suspended center
# ---------------------------------------------------------------------------

def test_suspended_center_blocks_booking(api):
    """PRD §3.5: "The slot's center must be `OPEN`; a booking at a suspended center
    is rejected with `ERR_CENTER_SUSPENDED`."

    Design: Corner/validations/center_suspended_blocks_booking
    """
    set_clock()
    program = create_program()
    center = create_center()
    slot = create_slot(center["id"])
    get_success_data(api.suspend_center(center["id"], ADMIN))
    applicant, app = setup_cleared_application_at_center(center["id"],
                                                         {"full_name": "Uri Sus"})
    h = make_applicant_headers(applicant["id"])
    v = app_version(app["id"])
    resp = api.create_appointment(appointment_payload(app["id"], slot["id"], v), h)
    validate_error(resp, ApiErrorId.ERR_CENTER_SUSPENDED.value)


# ---------------------------------------------------------------------------
# Queue B — cross_cutting: no-show cascade
# ---------------------------------------------------------------------------

def test_no_show_cascade_frees_slot_and_reverts_application(api):
    """PRD §3.5: "A no-show likewise frees the slot to `AVAILABLE`, clears
    `held_by_appointment_id`, and reverts an `INTERVIEW_SCHEDULED` application to
    `VETTING`."

    Design: Corner/cross_cutting_complexity_layers/no_show_cascade_frees_slot_and_reverts_application
    """
    program, applicant, app, center, slot, appt = setup_confirmed_appointment(
        slot_overrides={"starts_at": "2026-06-20T09:00:00Z",
                        "ends_at": "2026-06-20T09:30:00Z"}
    )
    # Advance past ends_at so no-show is permitted.
    set_clock("2026-06-20T10:00:00Z")
    no_show = get_success_data(api.no_show_appointment(appt["id"], ENROLLMENT))
    assert no_show["status"] == "NO_SHOW"
    final_slot = get_success_data(api.get_slot(slot["id"], ADMIN))
    assert final_slot["status"] == "AVAILABLE"
    final_app = get_application(app["id"])
    assert final_app["status"] == "VETTING"
