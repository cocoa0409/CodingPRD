"""Arithmetic on the testing-day and funding side: the discount tier that begins at exactly
twelve hours, the capped retake exponent, the candidate set a second run finds empty, the two
occupancy gates that ignore unconfirmed or cancelled sittings, and the composite at its floor.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import ApiErrorId, api_client, factories, fixtures
from test_helpers.assertions import (
    assert_funding_pool_conserved,
    assert_registration_fee_arithmetic,
    assert_transcript_charge_arithmetic,
)
from test_helpers.test_users import (
    make_center_administrator_headers,
    make_program_coordinator_headers,
    make_state_authority_headers,
)
from test_helpers.types import (
    AllocationStatus,
    AllocationVariant,
    CenterDecision,
    CredentialIssuanceStatus,
    CredentialStanding,
    CredentialType,
    IntakeStatus,
    MeasureType,
    OutcomeDecision,
    OutcomeStatus,
    ProgramTrack,
    SectionStatus,
    SessionStatus,
    Subtest,
    TestForm,
    TranscriptDelivery,
    TranscriptDestination,
    TranscriptOrderStatus,
)

USABLE_EXPIRY = "2027-01-01T00:00:00Z"
PRE_TEST_AT = "2026-08-02T09:00:00Z"

TIER_CLOCK = "2026-08-05T00:00:00Z"
TIER_POSTINGS = (("2026-08-03", 8.00), ("2026-08-04", 4.00))
TIER_SITTING = ("2026-08-20T09:00:00Z", "2026-08-20T12:00:00Z")

RETAKE_DATES = ("2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13")
RETAKE_SCORE = 150

RATE_CENTS_PER_WEIGHT = 10000
POOL_CENTS = 500000
EMPLOYMENT_LINE_CENTS = 12500
POSTSECONDARY_LINE_CENTS = 14000
RECORDING_COORDINATOR = "coordinator-1"
CERTIFYING_AUTHORITY = "state-1"

DRAFT_LOAD_MORNING = ("2026-08-20T09:00:00Z", "2026-08-20T13:00:00Z")
DRAFT_LOAD_AFTERNOON = ("2026-08-20T14:00:00Z", "2026-08-20T18:00:00Z")
DAILY_CAP_HOURS = 4.00

BUFFERED_SITTING = ("2026-08-20T09:00:00Z", "2026-08-20T12:00:00Z")
BACK_TO_BACK_SITTING = ("2026-08-20T12:00:00Z", "2026-08-20T15:00:00Z")
NO_CANDIDATES_REASON = "no candidates registered"

COMPOSITE_SLOTS = (
    (Subtest.MATH, "2026-08-20T09:00:00Z", "2026-08-20T10:30:00Z"),
    (Subtest.RLA, "2026-08-20T11:15:00Z", "2026-08-20T12:45:00Z"),
    (Subtest.SCIENCE, "2026-08-20T13:30:00Z", "2026-08-20T15:00:00Z"),
    (Subtest.SOCIAL_STUDIES, "2026-08-20T15:45:00Z", "2026-08-20T17:15:00Z"),
)
RETAKE_SLOT = ("2026-08-20T18:00:00Z", "2026-08-20T19:30:00Z")
PASSING_SCORE = 145
ONE_SHORT_SCORE = 144
MINIMUM_COMPOSITE = 580


def _issue_credential(student_id):
    return api_client.issue_credential(
        factories.create_credential_issuance_payload(student_id),
        headers=make_state_authority_headers(),
    )


def _setup_learner_at_twelve_hours():
    """A self-paying learner whose ledger holds exactly twelve hours, plus a MATH sitting."""
    center = fixtures.create_authorized_center(
        CenterDecision.GRANT_FULL, name="Tier Boundary Center", state_code="IA"
    )
    room = fixtures.create_room(center["id"], room_code="R-901", seat_capacity=12)
    proctor = fixtures.create_certified_proctor(
        center["id"],
        certification_expires_at=USABLE_EXPIRY,
        full_name="Rune Salas",
        daily_hour_cap=8.00,
    )
    session = fixtures.create_session(
        center["id"],
        room["id"],
        TIER_SITTING[0],
        TIER_SITTING[1],
        subtest=Subtest.MATH,
        requested_seats=5,
    )
    fixtures.assign_session_proctor(center["id"], session["id"], proctor["id"])

    placed = fixtures.create_placed_student(
        scale_score=205,
        test_form=TestForm.CASAS_R_900,
        pre_test_at=PRE_TEST_AT,
        full_name="Sol Ekwueme",
        email="sol.ekwueme@example.org",
        primary_track=ProgramTrack.HSE_PREP,
        self_pay_authorized=True,
    )
    section = fixtures.create_section(
        status=SectionStatus.OPEN,
        program_track=ProgramTrack.HSE_PREP,
        title="Twelve Hours",
        instructor_user_id="instructor-13",
        min_efl_level=1,
        max_efl_level=6,
        seats_total=10,
        weekly_hours=8.00,
    )
    enrollment = fixtures.enroll(placed["student_id"], section["id"])
    fixtures.set_clock(TIER_CLOCK)
    for attendance_date, hours in TIER_POSTINGS:
        fixtures.post_attendance(enrollment["id"], attendance_date, hours)

    return {"student_id": placed["student_id"], "session_id": session["id"]}


def _setup_four_math_sittings():
    """One self-paying learner with no hours and four MATH sittings on four separate days."""
    center = fixtures.create_authorized_center(
        CenterDecision.GRANT_FULL, name="Retake Cap Center", state_code="NE"
    )
    room = fixtures.create_room(center["id"], room_code="R-1001", seat_capacity=12)
    proctor = fixtures.create_certified_proctor(
        center["id"],
        certification_expires_at=USABLE_EXPIRY,
        full_name="Tam Oyelaran",
        daily_hour_cap=8.00,
    )
    sessions = []
    for exam_date in RETAKE_DATES:
        session = fixtures.create_session(
            center["id"],
            room["id"],
            f"{exam_date}T09:00:00Z",
            f"{exam_date}T12:00:00Z",
            subtest=Subtest.MATH,
            requested_seats=5,
        )
        sessions.append(fixtures.assign_session_proctor(center["id"], session["id"], proctor["id"]))

    placed = fixtures.create_placed_student(
        scale_score=205,
        test_form=TestForm.CASAS_R_900,
        pre_test_at=PRE_TEST_AT,
        full_name="Uzo Farrant",
        email="uzo.farrant@example.org",
        primary_track=ProgramTrack.HSE_PREP,
        self_pay_authorized=True,
    )
    return {
        "student_id": placed["student_id"],
        "proctor_id": proctor["id"],
        "sessions": sessions,
    }


def _setup_credential_at_the_minimum():
    """A learner holding an HSE credential assembled from four scores of exactly 145."""
    center = fixtures.create_authorized_center(
        CenterDecision.GRANT_FULL, name="Composite Boundary Center", state_code="MN"
    )
    room = fixtures.create_room(
        center["id"], room_code="R-1301", seat_capacity=20, turnaround_buffer_minutes=45
    )
    proctor = fixtures.create_certified_proctor(
        center["id"],
        certification_expires_at=USABLE_EXPIRY,
        full_name="Yusuf Brandt",
        daily_hour_cap=8.00,
    )
    placed = fixtures.create_placed_student(
        scale_score=205,
        test_form=TestForm.CASAS_R_900,
        pre_test_at=PRE_TEST_AT,
        full_name="Zia Moraes",
        email="zia.moraes@example.org",
        primary_track=ProgramTrack.HSE_PREP,
        self_pay_authorized=True,
    )

    first_scores = {
        Subtest.MATH: PASSING_SCORE,
        Subtest.RLA: PASSING_SCORE,
        Subtest.SCIENCE: PASSING_SCORE,
        Subtest.SOCIAL_STUDIES: ONE_SHORT_SCORE,
    }
    registrations = {}
    for subtest, starts_at, ends_at in COMPOSITE_SLOTS:
        session = fixtures.create_session(
            center["id"], room["id"], starts_at, ends_at, subtest=subtest, requested_seats=5
        )
        fixtures.assign_session_proctor(center["id"], session["id"], proctor["id"])
        registrations[subtest] = fixtures.register_candidate(placed["student_id"], session["id"])
    for subtest, starts_at, _ends_at in COMPOSITE_SLOTS:
        fixtures.seat_and_score_candidate(
            registrations[subtest]["id"],
            proctor["id"],
            starts_at,
            scale_score=first_scores[subtest],
        )

    short_of_the_floor = _issue_credential(placed["student_id"])

    retake_session = fixtures.create_session(
        center["id"],
        room["id"],
        RETAKE_SLOT[0],
        RETAKE_SLOT[1],
        subtest=Subtest.SOCIAL_STUDIES,
        requested_seats=5,
    )
    fixtures.assign_session_proctor(center["id"], retake_session["id"], proctor["id"])
    retake = fixtures.register_candidate(placed["student_id"], retake_session["id"])
    fixtures.seat_and_score_candidate(
        retake["id"], proctor["id"], RETAKE_SLOT[0], scale_score=PASSING_SCORE
    )

    return {
        "student_id": placed["student_id"],
        "registrations": registrations,
        "retake": retake,
        "short_of_the_floor": short_of_the_floor,
    }


def test_01_the_discount_tier_opens_at_exactly_twelve_banked_hours():
    """"A learner with fewer than twelve hours receives nothing. From twelve hours up to but not
    including forty, the tier is 25 percent." and "`discount_cents` is the billable amount
    multiplied by that percentage and divided by one hundred, then **floored** to whole cents"

    Design: Corner/calculations/exam_fee_tier_boundary_at_exactly_twelve_hours
    """
    context = _setup_learner_at_twelve_hours()

    registration = fixtures.register_candidate(context["student_id"], context["session_id"])
    assert registration["prior_scored_attempts"] == 0
    assert registration["gross_fee_cents"] == 3000
    assert registration["accommodation_surcharge_cents"] == 0
    assert registration["discount_cents"] == 750
    assert registration["voucher_applied_cents"] == 0
    assert registration["fee_due_cents"] == 2250
    assert_registration_fee_arithmetic(registration)

    learner = fixtures.read_student(context["student_id"])
    assert learner["exam_fee_owed_cents"] == 2250
    assert learner["voucher_balance_cents"] == 0
    assert learner["voucher_spent_cents"] == 0


def test_02_a_fourth_sitting_costs_no_more_than_the_third():
    """"The multiplier is 1.25 raised to the power of that count, with the exponent capped at 2
    — so a first sitting is charged at the base, a second at one and a quarter times the base,
    and a third or any later sitting at one and a quarter squared, which is 1.5625 times the
    base. The cap means a fourth retake costs no more than a third."

    Design: Corner/calculations/exam_fee_retake_multiplier_capped_at_two_exponents
    """
    context = _setup_four_math_sittings()
    sessions = context["sessions"]
    expected_gross = (3000, 3750, 4688)

    for index, gross in enumerate(expected_gross):
        registration = fixtures.register_candidate(
            context["student_id"], sessions[index]["id"]
        )
        assert registration["prior_scored_attempts"] == index
        assert registration["gross_fee_cents"] == gross
        fixtures.seat_and_score_candidate(
            registration["id"],
            context["proctor_id"],
            sessions[index]["starts_at"],
            scale_score=RETAKE_SCORE,
        )

    fourth = fixtures.register_candidate(context["student_id"], sessions[3]["id"])
    assert fourth["prior_scored_attempts"] == 3
    assert fourth["gross_fee_cents"] == 4688
    assert fourth["discount_cents"] == 0
    assert fourth["fee_due_cents"] == 4688
    assert_registration_fee_arithmetic(fourth)

    learner = fixtures.read_student(context["student_id"])
    assert learner["exam_fee_owed_cents"] == 16126
    assert learner["voucher_spent_cents"] == 0


def test_03_a_second_run_finds_no_candidates_left_to_pay():
    """"Claims that are `RESCINDED` or `REJECTED` never qualify under either variant, and claims
    already `COMMITTED`, `DEFERRED` or `REVOKED` never re-enter a run at all" and "The run also
    increments `allocation_run_count` by one, stamps `last_allocation_run_at` from the logical
    clock, and records the applied variant as `last_allocation_variant`."

    Design: Corner/calculations/funding_allocation_input_set_excludes_committed_and_rejected_rows
    """
    period = fixtures.create_funding_period(
        label="PY26-FILTER",
        start_date="2026-07-01",
        end_date="2026-09-30",
        rate_cents_per_weight=RATE_CENTS_PER_WEIGHT,
        total_cents=POOL_CENTS,
    )
    placed = fixtures.create_placed_student(
        scale_score=205,
        test_form=TestForm.CASAS_R_900,
        pre_test_at=PRE_TEST_AT,
        full_name="Vera Ilves",
        email="vera.ilves@example.org",
        primary_track=ProgramTrack.HSE_PREP,
    )
    claims = []
    for measure_type, evidence_ref, decision in (
        (MeasureType.EMPLOYMENT_Q2, "wage-v1", OutcomeDecision.CERTIFY),
        (MeasureType.POSTSECONDARY_ENROLLMENT, "clearinghouse-v1", OutcomeDecision.CERTIFY),
        (MeasureType.EMPLOYMENT_Q2, "wage-v2-unverifiable", OutcomeDecision.REJECT),
    ):
        claim = fixtures.record_outcome(
            placed["student_id"],
            period["id"],
            measure_type=measure_type,
            evidence_ref=evidence_ref,
            headers=make_program_coordinator_headers(RECORDING_COORDINATOR),
        )
        fixtures.decide_outcome(
            claim["id"],
            decision,
            headers=make_state_authority_headers(CERTIFYING_AUTHORITY),
        )
        claims.append(claim["id"])

    first_run = fixtures.run_allocation(period["id"], AllocationVariant.FINAL)
    assert first_run["committed_cents"] == EMPLOYMENT_LINE_CENTS + POSTSECONDARY_LINE_CENTS
    assert first_run["available_cents"] == POOL_CENTS - 26500
    assert first_run["allocation_run_count"] == 1
    assert first_run["last_allocation_variant"] == AllocationVariant.FINAL
    assert_funding_pool_conserved(first_run)

    second_run = fixtures.run_allocation(period["id"], AllocationVariant.FINAL)
    assert second_run["committed_cents"] == 26500
    assert second_run["available_cents"] == POOL_CENTS - 26500
    assert second_run["allocation_run_count"] == 2
    assert_funding_pool_conserved(second_run)

    page, meta = validate_paginated(
        api_client.list_outcome_records(
            headers=make_state_authority_headers(),
            params={"funding_period_id": period["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 3
    rows = {row["id"]: row for row in page}
    assert rows[claims[0]]["allocated_cents"] == EMPLOYMENT_LINE_CENTS
    assert rows[claims[0]]["allocation_status"] == AllocationStatus.COMMITTED
    assert rows[claims[1]]["allocated_cents"] == POSTSECONDARY_LINE_CENTS
    assert rows[claims[1]]["allocation_status"] == AllocationStatus.COMMITTED
    assert rows[claims[2]]["allocated_cents"] == 0
    assert rows[claims[2]]["status"] == OutcomeStatus.REJECTED
    assert rows[claims[2]]["allocation_status"] == AllocationStatus.UNALLOCATED


def test_04_an_unconfirmed_sitting_adds_nothing_to_the_daily_projection():
    """"`DRAFT` and `CANCELLED` sittings are excluded from the sum. When the projected total is
    strictly greater than the proctor's `daily_hour_cap` the assignment is refused with
    `ERR_PROCTOR_DAILY_CAP_EXCEEDED`; a projection landing exactly on the cap is allowed."

    Design: Corner/calculations/proctor_daily_load_ignores_draft_sessions
    """
    center = fixtures.create_authorized_center(
        CenterDecision.GRANT_FULL, name="Draft Excluded Center", state_code="SD"
    )
    first_room = fixtures.create_room(center["id"], room_code="R-1101", seat_capacity=10)
    second_room = fixtures.create_room(center["id"], room_code="R-1102", seat_capacity=10)
    proctor = fixtures.create_certified_proctor(
        center["id"],
        certification_expires_at=USABLE_EXPIRY,
        full_name="Wynn Abadi",
        daily_hour_cap=DAILY_CAP_HOURS,
    )
    afternoon = fixtures.create_session(
        center["id"],
        first_room["id"],
        DRAFT_LOAD_AFTERNOON[0],
        DRAFT_LOAD_AFTERNOON[1],
        subtest=Subtest.MATH,
        requested_seats=5,
    )
    morning = fixtures.create_session(
        center["id"],
        second_room["id"],
        DRAFT_LOAD_MORNING[0],
        DRAFT_LOAD_MORNING[1],
        subtest=Subtest.RLA,
        requested_seats=5,
    )
    assert afternoon["status"] == SessionStatus.DRAFT
    assert morning["status"] == SessionStatus.DRAFT

    scheduled = fixtures.assign_session_proctor(center["id"], morning["id"], proctor["id"])
    assert scheduled["status"] == SessionStatus.SCHEDULED
    assert float(scheduled["duration_hours"]) == DAILY_CAP_HOURS

    response = api_client.assign_proctor(
        afternoon["id"],
        factories.proctor_assignment_payload(proctor["id"]),
        headers=make_center_administrator_headers(center["id"]),
    )
    validate_error(response, ApiErrorId.PROCTOR_DAILY_CAP_EXCEEDED, expected_status=409)

    stored = fixtures.read_session(afternoon["id"])
    assert stored["status"] == SessionStatus.DRAFT
    assert stored["proctor_id"] is None
    assert fixtures.read_proctor(proctor["id"])["assigned_session_count"] == 1


def test_05_a_cancelled_sitting_stops_occupying_its_room():
    """"The sittings compared are every non-cancelled one in the same room — those whose
    `status` is `DRAFT`, `SCHEDULED`, `IN_PROGRESS` or `COMPLETED`. A `CANCELLED` sitting
    occupies nothing and frees its slot for immediate rebooking."

    Design: Corner/calculations/room_occupation_conflict_ignores_cancelled_sessions
    """
    center = fixtures.create_authorized_center(
        CenterDecision.GRANT_FULL, name="Cancelled Footprint Center", state_code="ND"
    )
    room = fixtures.create_room(
        center["id"], room_code="R-1201", seat_capacity=10, turnaround_buffer_minutes=45
    )
    occupant = fixtures.create_session(
        center["id"],
        room["id"],
        BUFFERED_SITTING[0],
        BUFFERED_SITTING[1],
        subtest=Subtest.MATH,
        requested_seats=5,
    )

    def _book_replacement():
        return api_client.create_exam_session(
            factories.create_exam_session_payload(
                room["id"],
                BACK_TO_BACK_SITTING[0],
                BACK_TO_BACK_SITTING[1],
                subtest=Subtest.RLA,
                requested_seats=5,
            ),
            headers=make_center_administrator_headers(center["id"]),
        )

    validate_error(_book_replacement(), ApiErrorId.ROOM_BUFFER_CONFLICT, expected_status=409)

    cancelled = fixtures.cancel_session(
        center["id"], occupant["id"], cancel_reason=NO_CANDIDATES_REASON
    )
    assert cancelled["status"] == SessionStatus.CANCELLED

    replacement = validate_success(_book_replacement(), expected_status=201)
    assert replacement["status"] == SessionStatus.DRAFT
    assert float(replacement["duration_hours"]) == 3.00
    assert replacement["seat_capacity"] == 5


def test_06_four_scores_of_exactly_the_pass_mark_issue_one_credential_and_only_one():
    """"The learner qualifies only when all four subtests have a score and every one of those
    scores is at least 145." and "Issuance additionally requires that `composite_score` reach at
    least 580 — a learner can pass all four subtests at exactly 145 each, totalling 580, and
    that is sufficient, while 579 is not."

    Design: Corner/calculations/credential_composite_exactly_at_the_minimum_then_transcript_charge_tiers
    """
    context = _setup_credential_at_the_minimum()
    validate_error(
        context["short_of_the_floor"],
        ApiErrorId.CREDENTIAL_REQUIREMENTS_NOT_MET,
        expected_status=409,
    )
    assert context["retake"]["prior_scored_attempts"] == 1
    assert context["retake"]["gross_fee_cents"] == 3750

    credential = validate_success(
        _issue_credential(context["student_id"]), expected_status=201
    )
    assert credential["status"] == CredentialIssuanceStatus.ISSUED
    assert credential["credential_type"] == CredentialType.HSE_DIPLOMA
    assert credential["issued_at"] == RETAKE_SLOT[0]
    assert credential["composite_score"] == MINIMUM_COMPOSITE
    assert credential["subtest_scores"] == {
        Subtest.MATH: PASSING_SCORE,
        Subtest.RLA: PASSING_SCORE,
        Subtest.SCIENCE: PASSING_SCORE,
        Subtest.SOCIAL_STUDIES: PASSING_SCORE,
    }
    assert credential["qualifying_registration_ids"] == [
        context["registrations"][Subtest.MATH]["id"],
        context["registrations"][Subtest.RLA]["id"],
        context["registrations"][Subtest.SCIENCE]["id"],
        context["retake"]["id"],
    ]

    duplicate = _issue_credential(context["student_id"])
    validate_error(duplicate, ApiErrorId.DUPLICATE_CREDENTIAL, expected_status=409)

    learner = fixtures.read_student(context["student_id"])
    assert learner["credential_status"] == CredentialStanding.ISSUED
    assert learner["intake_status"] == IntakeStatus.EXITED


def test_07_the_transcript_charge_walks_its_waiver_and_records_fee_tiers():
    """"A waiver percentage is chosen from `base_charge_cents` alone: nothing below 3000 cents,
    10 percent from 3000 cents up to but not including 6000, and 20 percent at 6000 cents or
    above." and "`state_records_fee_cents` is keyed on that net figure: 0 when the net is
    exactly zero, 200 cents when the net is above zero but below 3000, and 500 cents when the
    net is 3000 cents or more."

    Design: Corner/calculations/credential_composite_exactly_at_the_minimum_then_transcript_charge_tiers
    """
    context = _setup_credential_at_the_minimum()
    credential = validate_success(
        _issue_credential(context["student_id"]), expected_status=201
    )

    single = fixtures.create_transcript_order(
        context["student_id"],
        credential["id"],
        copies=1,
        delivery=TranscriptDelivery.STANDARD,
        destination_type=TranscriptDestination.POSTSECONDARY,
    )
    assert single["base_charge_cents"] == 1500
    assert single["waiver_cents"] == 0
    assert single["state_records_fee_cents"] == 200
    assert single["total_charge_cents"] == 1700
    assert_transcript_charge_arithmetic(single)

    pair = fixtures.create_transcript_order(
        context["student_id"],
        credential["id"],
        copies=2,
        delivery=TranscriptDelivery.STANDARD,
        destination_type=TranscriptDestination.EMPLOYER,
    )
    assert pair["base_charge_cents"] == 3000
    assert pair["waiver_cents"] == 300
    assert pair["state_records_fee_cents"] == 200
    assert pair["total_charge_cents"] == 2900
    assert_transcript_charge_arithmetic(pair)

    rush = fixtures.create_transcript_order(
        context["student_id"],
        credential["id"],
        copies=4,
        delivery=TranscriptDelivery.RUSH,
        destination_type=TranscriptDestination.STATE_RECORDS,
    )
    assert rush["base_charge_cents"] == 8500
    assert rush["waiver_cents"] == 1700
    assert rush["state_records_fee_cents"] == 500
    assert rush["total_charge_cents"] == 7300
    assert_transcript_charge_arithmetic(rush)


def test_08_an_order_can_only_be_fulfilled_once():
    """"It moves the order from `QUEUED` to `FULFILLED`, which is terminal, stamps
    `fulfilled_at` from the logical clock and raises the order's `version` by one." and
    "Fulfilment, performed by a `Registrar` or `ProgramCoordinator`, requires the order to still
    be `QUEUED` — otherwise `ERR_TRANSCRIPT_ORDER_NOT_QUEUED`"

    Design: Corner/calculations/credential_composite_exactly_at_the_minimum_then_transcript_charge_tiers
    """
    context = _setup_credential_at_the_minimum()
    credential = validate_success(
        _issue_credential(context["student_id"]), expected_status=201
    )
    order = fixtures.create_transcript_order(
        context["student_id"],
        credential["id"],
        copies=1,
        delivery=TranscriptDelivery.STANDARD,
        destination_type=TranscriptDestination.POSTSECONDARY,
    )
    assert order["status"] == TranscriptOrderStatus.QUEUED
    assert order["fulfilled_at"] is None

    fulfilled = fixtures.fulfill_transcript_order(order["id"])
    assert fulfilled["status"] == TranscriptOrderStatus.FULFILLED
    assert fulfilled["fulfilled_at"] == RETAKE_SLOT[0]
    assert fulfilled["version"] == order["version"] + 1

    repeat = api_client.fulfill_transcript_order(
        order["id"], headers=make_program_coordinator_headers()
    )
    validate_error(repeat, ApiErrorId.TRANSCRIPT_ORDER_NOT_QUEUED, expected_status=409)

    assert (
        fixtures.read_transcript_order(order["id"])["status"]
        == TranscriptOrderStatus.FULFILLED
    )
