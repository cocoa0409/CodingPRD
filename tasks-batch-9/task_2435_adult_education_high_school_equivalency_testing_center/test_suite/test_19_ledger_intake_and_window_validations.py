"""Validation edges that guard ledgers, intake standing, calendar windows, the three-step
accommodation reference ladder, and the evidence a funding claim must carry.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import ApiErrorId, api_client, factories, fixtures
from test_helpers.assertions import assert_hours_value
from test_helpers.test_users import (
    make_center_administrator_headers,
    make_instructor_headers,
    make_program_coordinator_headers,
    make_registrar_headers,
    make_state_authority_headers,
)
from test_helpers.types import (
    AccommodationDecision,
    AccommodationStatus,
    AllocationStatus,
    CenterDecision,
    EnrollmentStatus,
    IntakeStatus,
    MeasureType,
    OutcomeStatus,
    ProgramTrack,
    SectionStatus,
    Subtest,
    TestEventPurpose,
    TestForm,
    TestFormat,
)

USABLE_EXPIRY = "2027-01-01T00:00:00Z"
PRE_TEST_AT = "2026-08-02T09:00:00Z"
SITTING = ("2026-08-20T09:00:00Z", "2026-08-20T12:00:00Z")

VOUCHER_GRANT_CENTS = 5000
OVERDRAW_CENTS = -6000
FULL_CLAWBACK_CENTS = -5000

WINDOW_CLOCK = "2026-08-15T00:00:00Z"
PAST_SITTING = ("2026-08-14T09:00:00Z", "2026-08-14T12:00:00Z")
SEVEN_HOUR_SITTING = ("2026-08-25T09:00:00Z", "2026-08-25T16:00:00Z")
ZERO_LENGTH_SITTING = ("2026-08-25T12:00:00Z", "2026-08-25T12:00:00Z")
BACKDATED_TEST_EVENT_AT = "2026-08-10T09:00:00Z"

EFFECTIVE_WINDOW_CLOCK = "2026-08-10T00:00:00Z"
FUTURE_ATTENDANCE_DATE = "2026-08-11"
FUTURE_ATTENDANCE_HOURS = 2.00
BACKDATED_VALID_UNTIL = "2026-08-05T00:00:00Z"

LADDER_SITTING = ("2026-08-20T09:00:00Z", "2026-08-20T11:00:00Z")
MATH_BASE_FEE_CENTS = 3000

EXPIRY_SITTING = ("2026-09-10T09:00:00Z", "2026-09-10T11:30:00Z")
LAPSING_VALID_UNTIL = "2026-08-15T00:00:00Z"
ONE_SECOND_PAST_THE_LAPSE = "2026-08-15T00:00:01Z"

FUNDING_LABEL = "FY27-Q1"
FUNDING_WINDOW = ("2026-08-01", "2026-11-01")
RATE_CENTS_PER_WEIGHT = 10000
POOL_CENTS = 500000
EMPLOYMENT_WEIGHT = 1.25
RECORDING_COORDINATOR = "coordinator-1"


def _placed_learner(full_name, email, scale_score=205, test_form=TestForm.CASAS_R_900, **overrides):
    return fixtures.create_placed_student(
        scale_score=scale_score,
        test_form=test_form,
        pre_test_at=PRE_TEST_AT,
        full_name=full_name,
        email=email,
        **overrides,
    )


def _open_section(title, instructor_user_id, program_track=ProgramTrack.HSE_PREP, **overrides):
    return fixtures.create_section(
        status=SectionStatus.OPEN,
        program_track=program_track,
        title=title,
        instructor_user_id=instructor_user_id,
        min_efl_level=1,
        max_efl_level=6,
        seats_total=10,
        weekly_hours=6.00,
        **overrides,
    )


def _register(student_id, session_id, expected_exam_session_version, **overrides):
    return api_client.create_exam_registration(
        factories.create_exam_registration_payload(
            student_id, session_id, expected_exam_session_version, **overrides
        ),
        headers=make_registrar_headers(),
    )


def _adjust_voucher(student_id, delta_cents):
    return api_client.adjust_voucher(
        student_id,
        factories.voucher_adjustment_payload(delta_cents),
        headers=make_program_coordinator_headers(),
    )


def _venue(name, state_code, room_code, proctor_name, seat_capacity=12):
    center = fixtures.create_authorized_center(
        CenterDecision.GRANT_FULL, name=name, state_code=state_code
    )
    room = fixtures.create_room(
        center["id"], room_code=room_code, seat_capacity=seat_capacity
    )
    proctor = fixtures.create_certified_proctor(
        center["id"],
        certification_expires_at=USABLE_EXPIRY,
        full_name=proctor_name,
        daily_hour_cap=8.00,
    )
    return center["id"], room["id"], proctor["id"]


def test_01_a_clawback_may_empty_the_purse_but_never_overdraw_it():
    """"A `ProgramCoordinator` or `StateAuthority` adjusts a learner's voucher funds by
    submitting a `delta_cents` amount, which is added both to the lifetime
    `voucher_granted_cents` and to the spendable `voucher_balance_cents`. A negative
    `delta_cents` claws funds back. An adjustment that would leave `voucher_balance_cents` below
    zero is refused with `ERR_VOUCHER_ADJUSTMENT_INVALID`, leaving the ledger untouched"

    Design: Corner/validations/voucher_adjustment_may_not_drive_the_balance_negative
    """
    student = fixtures.create_student(
        full_name="Kai Brandao",
        email="kai.brandao@example.org",
        primary_track=ProgramTrack.HSE_PREP,
    )
    granted = validate_success(_adjust_voucher(student["id"], VOUCHER_GRANT_CENTS))
    assert granted["voucher_granted_cents"] == VOUCHER_GRANT_CENTS
    assert granted["voucher_balance_cents"] == VOUCHER_GRANT_CENTS

    refused = _adjust_voucher(student["id"], OVERDRAW_CENTS)
    validate_error(refused, ApiErrorId.VOUCHER_ADJUSTMENT_INVALID, expected_status=422)
    assert fixtures.read_student(student["id"])["voucher_balance_cents"] == VOUCHER_GRANT_CENTS

    emptied = validate_success(_adjust_voucher(student["id"], FULL_CLAWBACK_CENTS))
    assert emptied["voucher_balance_cents"] == 0
    assert emptied["voucher_granted_cents"] == 0


def test_02_the_intake_ladder_guards_the_pre_test_and_then_the_enrollment():
    """"Test-event scheduling requires the learner's `intake_status` to be `ORIENTED`, `PLACED`
    or `ENROLLED` — otherwise `ERR_STUDENT_NOT_ORIENTED`. Enrollment requires a non-null
    `placement_efl_level` — otherwise `ERR_PLACEMENT_TEST_MISSING`."

    Design: Corner/validations/intake_gates_block_pre_test_and_enrollment
    """
    student = fixtures.create_student(
        full_name="Lena Ferro",
        email="lena.ferro@example.org",
        primary_track=ProgramTrack.HSE_PREP,
    )
    section = _open_section("Wide Open", "instructor-19")

    too_early = api_client.create_test_event(
        factories.create_test_event_payload(
            student["id"],
            PRE_TEST_AT,
            purpose=TestEventPurpose.PRE_TEST,
            test_form=TestForm.CASAS_R_900,
        ),
        headers=make_registrar_headers(),
    )
    validate_error(too_early, ApiErrorId.STUDENT_NOT_ORIENTED, expected_status=409)

    validate_success(
        api_client.complete_orientation(student["id"], headers=make_registrar_headers())
    )

    unplaced = api_client.create_enrollment(
        factories.create_enrollment_payload(student["id"], section["id"]),
        headers=make_program_coordinator_headers(),
    )
    validate_error(unplaced, ApiErrorId.PLACEMENT_TEST_MISSING, expected_status=409)

    assert fixtures.read_class_section(section["id"])["seats_taken"] == 0
    learner = fixtures.read_student(student["id"])
    assert learner["intake_status"] == IntakeStatus.ORIENTED
    assert learner["active_enrollment_count"] == 0


def test_03_an_oriented_learner_is_not_yet_a_candidate():
    """"After the stale-view guard, the learner must be `PLACED` or `ENROLLED` — a learner still
    `INTAKE_STARTED` or `ORIENTED`, or already `EXITED`, is refused with
    `ERR_STUDENT_NOT_PLACED`."

    Design: Corner/validations/exam_registration_requires_a_placed_student
    """
    center_id, room_id, proctor_id = _venue(
        "Placed Only Center", "MO", "R-1601", "Mira Dulac"
    )
    session = fixtures.create_session(
        center_id, room_id, SITTING[0], SITTING[1], subtest=Subtest.MATH, requested_seats=5
    )
    scheduled = fixtures.assign_session_proctor(center_id, session["id"], proctor_id)

    student = fixtures.create_oriented_student(
        full_name="Nils Achebe",
        email="nils.achebe@example.org",
        primary_track=ProgramTrack.HSE_PREP,
        self_pay_authorized=True,
    )

    refused = _register(student["id"], session["id"], scheduled["version"])
    validate_error(refused, ApiErrorId.STUDENT_NOT_PLACED, expected_status=409)

    stored = fixtures.read_session(session["id"])
    assert stored["seats_taken"] == 0
    assert stored["version"] == scheduled["version"]
    assert fixtures.read_student(student["id"])["exam_fee_owed_cents"] == 0


def test_04_a_sitting_must_be_ahead_of_the_clock_and_no_longer_than_six_hours():
    """"A session's `starts_at` must be strictly later than the clock — otherwise
    `ERR_SESSION_IN_PAST`." and "A session's `ends_at` must be strictly after its `starts_at` and
    the window may not exceed six hours; a test event's `scheduled_for` may not precede the clock.
    Violations report `ERR_INVALID_SESSION_WINDOW`."

    Design: Corner/validations/session_window_rules_reject_past_and_overlong_sittings
    """
    center_id, room_id, _proctor_id = _venue(
        "Window Rules Center", "OH", "R-1701", "Odin Vale"
    )
    student = fixtures.create_oriented_student(
        full_name="Oona Barrell",
        email="oona.barrell@example.org",
        primary_track=ProgramTrack.HSE_PREP,
    )
    fixtures.set_clock(WINDOW_CLOCK)

    def _create(starts_at, ends_at):
        return api_client.create_exam_session(
            factories.create_exam_session_payload(
                room_id, starts_at, ends_at, subtest=Subtest.MATH, requested_seats=5
            ),
            headers=make_center_administrator_headers(center_id),
        )

    validate_error(
        _create(*PAST_SITTING), ApiErrorId.SESSION_IN_PAST, expected_status=422
    )
    validate_error(
        _create(*SEVEN_HOUR_SITTING), ApiErrorId.INVALID_SESSION_WINDOW, expected_status=422
    )
    validate_error(
        _create(*ZERO_LENGTH_SITTING), ApiErrorId.INVALID_SESSION_WINDOW, expected_status=422
    )

    backdated_event = api_client.create_test_event(
        factories.create_test_event_payload(
            student["id"],
            BACKDATED_TEST_EVENT_AT,
            purpose=TestEventPurpose.PRE_TEST,
            test_form=TestForm.CASAS_R_900,
        ),
        headers=make_registrar_headers(),
    )
    validate_error(
        backdated_event, ApiErrorId.INVALID_SESSION_WINDOW, expected_status=422
    )

    _page, meta = validate_paginated(
        api_client.list_exam_sessions(
            headers=make_center_administrator_headers(center_id),
            params={"testing_room_id": room_id, "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 0


def test_05_neither_hours_nor_approvals_may_be_dated_on_the_wrong_side_of_the_clock():
    """"An `attendance_date` later than the logical clock's own UTC date is refused with
    `ERR_INVALID_EFFECTIVE_WINDOW`, because hours cannot be posted for a day that has not
    happened yet." and "A `valid_until` at or before the logical clock is refused with
    `ERR_INVALID_EFFECTIVE_WINDOW`"

    Design: Corner/validations/effective_window_rules_reject_future_attendance_and_past_approvals
    """
    center = fixtures.create_authorized_center(
        CenterDecision.GRANT_FULL, name="Effective Window Center", state_code="MI"
    )
    placed = _placed_learner("Pia Ndiaye", "pia.ndiaye@example.org")
    section = _open_section("Effective Dates", "instructor-20")
    enrollment = fixtures.enroll(placed["student_id"], section["id"])
    assert enrollment["status"] == EnrollmentStatus.ACTIVE

    request = fixtures.create_accommodation(
        placed["student_id"],
        requested_format=TestFormat.EXTRA_TIME,
        documentation_ref="doc-pia-1",
    )
    fixtures.set_clock(EFFECTIVE_WINDOW_CLOCK)

    future_hours = api_client.create_attendance_entry(
        enrollment["id"],
        factories.create_attendance_entry_payload(
            FUTURE_ATTENDANCE_DATE, FUTURE_ATTENDANCE_HOURS
        ),
        headers=make_instructor_headers(),
    )
    validate_error(future_hours, ApiErrorId.INVALID_EFFECTIVE_WINDOW, expected_status=422)
    assert_hours_value(fixtures.read_enrollment(enrollment["id"])["posted_hours"], 0.00)

    backdated_approval = api_client.decide_accommodation(
        request["id"],
        factories.accommodation_decision_payload(
            AccommodationDecision.APPROVE,
            granted_format=TestFormat.EXTRA_TIME,
            valid_until=BACKDATED_VALID_UNTIL,
        ),
        headers=make_center_administrator_headers(center["id"]),
    )
    validate_error(
        backdated_approval, ApiErrorId.INVALID_EFFECTIVE_WINDOW, expected_status=422
    )

    stored = fixtures.read_accommodation(request["id"])
    assert stored["status"] == AccommodationStatus.SUBMITTED
    assert stored["granted_format"] is None


def test_06_a_cited_accommodation_answers_owner_then_standing_then_format():
    """"Where an accommodation is cited, three checks follow in sequence: it must belong to the
    registering learner, or `ERR_ACCOMMODATION_OWNER_MISMATCH`; it must be `APPROVED` and
    unexpired, per §3.7; and the sitting's `supported_formats` must contain the accommodation's
    `granted_format`, or `ERR_ACCOMMODATION_FORMAT_UNAVAILABLE`."

    Design: Corner/validations/accommodation_reference_ladder_owner_then_status_then_format
    """
    center_id, room_id, proctor_id = _venue(
        "Accommodation Ladder Center", "OR", "LADDER-1", "Ines Kovac"
    )
    session = fixtures.create_session(
        center_id,
        room_id,
        LADDER_SITTING[0],
        LADDER_SITTING[1],
        subtest=Subtest.MATH,
        requested_seats=5,
    )
    scheduled = fixtures.assign_session_proctor(center_id, session["id"], proctor_id)
    session_version = scheduled["version"]

    ada = _placed_learner(
        "Ada Rojas",
        "ada.rojas@example.org",
        scale_score=214,
        test_form=TestForm.CASAS_M_900,
        self_pay_authorized=True,
    )
    bo = _placed_learner(
        "Bo Adeyemi",
        "bo.adeyemi@example.org",
        scale_score=214,
        test_form=TestForm.CASAS_M_900,
    )

    bo_request = fixtures.create_accommodation(
        bo["student_id"], requested_format=TestFormat.EXTRA_TIME, documentation_ref="doc-bo-1"
    )
    fixtures.decide_accommodation(
        center_id,
        bo_request["id"],
        AccommodationDecision.APPROVE,
        granted_format=TestFormat.EXTRA_TIME,
        valid_until=USABLE_EXPIRY,
    )
    ada_extra_time = fixtures.create_accommodation(
        ada["student_id"], requested_format=TestFormat.EXTRA_TIME, documentation_ref="doc-ada-1"
    )
    ada_braille = fixtures.create_accommodation(
        ada["student_id"], requested_format=TestFormat.BRAILLE, documentation_ref="doc-ada-2"
    )
    fixtures.decide_accommodation(
        center_id,
        ada_braille["id"],
        AccommodationDecision.APPROVE,
        granted_format=TestFormat.BRAILLE,
        valid_until=USABLE_EXPIRY,
    )

    validate_error(
        _register(
            ada["student_id"],
            session["id"],
            session_version,
            accommodation_request_id=bo_request["id"],
        ),
        ApiErrorId.ACCOMMODATION_OWNER_MISMATCH,
        expected_status=409,
    )
    validate_error(
        _register(
            ada["student_id"],
            session["id"],
            session_version,
            accommodation_request_id=ada_extra_time["id"],
        ),
        ApiErrorId.ACCOMMODATION_NOT_APPROVED,
        expected_status=409,
    )
    validate_error(
        _register(
            ada["student_id"],
            session["id"],
            session_version,
            accommodation_request_id=ada_braille["id"],
        ),
        ApiErrorId.ACCOMMODATION_FORMAT_UNAVAILABLE,
        expected_status=409,
    )
    assert fixtures.read_session(session["id"])["version"] == session_version

    fixtures.decide_accommodation(
        center_id,
        ada_extra_time["id"],
        AccommodationDecision.APPROVE,
        granted_format=TestFormat.EXTRA_TIME,
        valid_until=USABLE_EXPIRY,
    )
    registration = validate_success(
        _register(
            ada["student_id"],
            session["id"],
            session_version,
            accommodation_request_id=ada_extra_time["id"],
        ),
        expected_status=201,
    )
    assert registration["accommodation_request_id"] == ada_extra_time["id"]
    assert registration["accommodation_surcharge_cents"] == 0
    assert registration["gross_fee_cents"] == MATH_BASE_FEE_CENTS
    assert registration["fee_due_cents"] == MATH_BASE_FEE_CENTS

    assert fixtures.read_session(session["id"])["seats_taken"] == 1


def test_07_an_approval_lapses_the_moment_a_seat_is_claimed_against_it():
    """"If the logical clock has reached or passed `valid_until`, the request is first moved from
    `APPROVED` to `EXPIRED` — a terminal state, with the request's `version` increased by one —
    and only then is the registration refused with `ERR_ACCOMMODATION_EXPIRED`. As with a proctor
    lapse, the state change survives the refused request."

    Design: Corner/validations/accommodation_approval_expires_lazily_at_registration_time
    """
    center_id, room_id, proctor_id = _venue(
        "Lazy Expiry Center", "NV", "EXPIRY-1", "Tomas Bell", seat_capacity=8
    )
    session = fixtures.create_session(
        center_id,
        room_id,
        EXPIRY_SITTING[0],
        EXPIRY_SITTING[1],
        subtest=Subtest.RLA,
        requested_seats=4,
    )
    scheduled = fixtures.assign_session_proctor(center_id, session["id"], proctor_id)

    nia = _placed_learner(
        "Nia Frost",
        "nia.frost@example.org",
        scale_score=240,
        self_pay_authorized=True,
    )
    request = fixtures.create_accommodation(
        nia["student_id"], requested_format=TestFormat.EXTRA_TIME, documentation_ref="doc-nia-1"
    )
    approved = fixtures.decide_accommodation(
        center_id,
        request["id"],
        AccommodationDecision.APPROVE,
        granted_format=TestFormat.EXTRA_TIME,
        valid_until=LAPSING_VALID_UNTIL,
    )
    assert approved["status"] == AccommodationStatus.APPROVED
    assert approved["valid_until"] == LAPSING_VALID_UNTIL

    fixtures.set_clock(ONE_SECOND_PAST_THE_LAPSE)

    refused = _register(
        nia["student_id"],
        session["id"],
        scheduled["version"],
        accommodation_request_id=request["id"],
    )
    validate_error(refused, ApiErrorId.ACCOMMODATION_EXPIRED, expected_status=409)

    lapsed = fixtures.read_accommodation(request["id"])
    assert lapsed["status"] == AccommodationStatus.EXPIRED
    assert lapsed["granted_format"] == TestFormat.EXTRA_TIME

    stored_session = fixtures.read_session(session["id"])
    assert stored_session["seats_taken"] == 0
    assert stored_session["version"] == scheduled["version"]

    _page, meta = validate_paginated(
        api_client.list_exam_registrations(
            headers=make_registrar_headers(),
            params={"student_id": nia["student_id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 0


def test_08_a_credential_claim_without_a_credential_is_not_a_claim():
    """"A `CREDENTIAL_ATTAINMENT` claim must carry a `credential_issuance_id` whose credential is
    `ISSUED` rather than voided, and whose own learner is the same learner the outcome is claimed
    for; a missing identifier or a credential belonging to somebody else is refused with
    `ERR_OUTCOME_EVIDENCE_MISMATCH`" and "The other three measure types leave
    `credential_issuance_id` null."

    Design: Corner/validations/credential_attainment_outcome_requires_matching_credential_evidence
    """
    period = fixtures.create_funding_period(
        label=FUNDING_LABEL,
        start_date=FUNDING_WINDOW[0],
        end_date=FUNDING_WINDOW[1],
        rate_cents_per_weight=RATE_CENTS_PER_WEIGHT,
        total_cents=POOL_CENTS,
    )
    fixtures.create_oriented_student(
        full_name="Rex Calder",
        email="rex.calder@example.org",
        primary_track=ProgramTrack.HSE_PREP,
    )
    vera = fixtures.create_oriented_student(
        full_name="Vera Lund",
        email="vera.lund@example.org",
        primary_track=ProgramTrack.HSE_PREP,
    )

    unevidenced = api_client.create_outcome_record(
        factories.create_outcome_record_payload(
            vera["id"],
            period["id"],
            measure_type=MeasureType.CREDENTIAL_ATTAINMENT,
            evidence_ref="NRS-vera-1",
        ),
        headers=make_program_coordinator_headers(RECORDING_COORDINATOR),
    )
    validate_error(unevidenced, ApiErrorId.OUTCOME_EVIDENCE_MISMATCH, expected_status=409)

    employment = validate_success(
        api_client.create_outcome_record(
            factories.create_outcome_record_payload(
                vera["id"],
                period["id"],
                measure_type=MeasureType.EMPLOYMENT_Q2,
                evidence_ref="NRS-vera-2",
            ),
            headers=make_program_coordinator_headers(RECORDING_COORDINATOR),
        ),
        expected_status=201,
    )
    assert employment["status"] == OutcomeStatus.RECORDED
    assert float(employment["weight"]) == EMPLOYMENT_WEIGHT
    assert employment["allocation_status"] == AllocationStatus.UNALLOCATED
    assert employment["credential_issuance_id"] is None

    _page, meta = validate_paginated(
        api_client.list_outcome_records(
            headers=make_state_authority_headers(),
            params={"funding_period_id": period["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 1
