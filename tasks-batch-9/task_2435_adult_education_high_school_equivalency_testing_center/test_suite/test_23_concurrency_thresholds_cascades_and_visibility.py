"""The layers that cut across every entity: a shared seat counter guarded by a version that moves
on every write, one quarter of an hour that flips two unrelated consumers of the same ledger at
once, the five-link chain a single revocation drags from a signature to the funding pool, and the
promise that a derived figure is already there in the response that caused it.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import ApiErrorId, api_client, factories, fixtures
from test_helpers.assertions import assert_hours_value
from test_helpers.test_users import (
    make_instructor_headers,
    make_program_coordinator_headers,
    make_registrar_headers,
    make_state_authority_headers,
)
from test_helpers.types import (
    AllocationStatus,
    AllocationVariant,
    CenterDecision,
    CredentialIssuanceStatus,
    CredentialStanding,
    EnrollmentStatus,
    HoldReason,
    MeasureType,
    OutcomeStatus,
    ProctorCertificationStatus,
    ProctorDecision,
    ProgramTrack,
    RegistrationStatus,
    RescissionReason,
    ResultOutcome,
    SectionStatus,
    SessionStatus,
    Subtest,
    TestForm,
    TranscriptDelivery,
    TranscriptDestination,
    TranscriptOrderStatus,
    VoidReason,
)

USABLE_EXPIRY = "2027-01-01T00:00:00Z"
PRE_TEST_AT = "2026-08-02T09:00:00Z"

VERSION_SITTING = ("2026-08-25T09:00:00Z", "2026-08-25T11:00:00Z")
VERSION_SEATS = 5
MATH_PLACEMENT_SCORE = 214

THRESHOLD_SITTINGS = (
    ("2026-09-05T09:00:00Z", "2026-09-05T11:00:00Z"),
    ("2026-09-05T13:00:00Z", "2026-09-05T15:00:00Z"),
)
THRESHOLD_SEATS = 4
THRESHOLD_SECTION = {
    "title": "Threshold Section",
    "instructor_user_id": "instructor-41",
    "min_efl_level": 1,
    "max_efl_level": 6,
    "seats_total": 10,
    "weekly_hours": 8.00,
}
FULL_DAYS = ("2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06")
FULL_DAY_HOURS = 8.00
SHORT_DAY = "2026-08-07"
SHORT_DAY_HOURS = 7.75
LEDGER_CLOCK = "2026-08-07T18:00:00Z"
HOURS_BEFORE = 39.75
LATER_CLOCK = "2026-08-10T18:00:00Z"
LAST_DAY = "2026-08-10"
LAST_DAY_HOURS = 0.25
HOURS_AFTER = 40.00
MATH_BASE_FEE_CENTS = 3000
QUARTER_TIER_DISCOUNT_CENTS = 750
QUARTER_TIER_DUE_CENTS = 2250
HALF_TIER_DISCOUNT_CENTS = 1500
HALF_TIER_DUE_CENTS = 1500

CASCADE_SITTINGS = (
    (Subtest.MATH, "2026-08-20T09:00:00Z", "2026-08-20T10:30:00Z"),
    (Subtest.RLA, "2026-08-20T11:15:00Z", "2026-08-20T12:45:00Z"),
    (Subtest.SCIENCE, "2026-08-20T13:30:00Z", "2026-08-20T15:00:00Z"),
    (Subtest.SOCIAL_STUDIES, "2026-08-20T15:45:00Z", "2026-08-20T17:15:00Z"),
)
CASCADE_SEATS = 3
CASCADE_SEATING_CLOCK = "2026-08-20T08:30:00Z"
CASCADE_CHECK_IN_CLOCKS = (
    "2026-08-20T08:30:00Z",
    "2026-08-20T11:00:00Z",
    "2026-08-20T13:15:00Z",
    "2026-08-20T15:30:00Z",
)
CASCADE_SUBTEST_SCORE = 150
CASCADE_COMPOSITE = 600
CASCADE_PLACEMENT_SCORE = 227
CASCADE_PERIOD = {
    "label": "FY27-CASCADE",
    "start_date": "2026-08-01",
    "end_date": "2026-12-01",
    "rate_cents_per_weight": 10000,
    "total_cents": 500000,
}
CREDENTIAL_WEIGHT = 1.50
CREDENTIAL_LINE_CENTS = 15000
POOL_AFTER_RUN_CENTS = 485000
EMPTY_POOL_CENTS = 0

IMMEDIATE_SECTION = {
    "title": "Immediate Section",
    "instructor_user_id": "instructor-51",
    "min_efl_level": 1,
    "max_efl_level": 6,
    "seats_total": 10,
    "weekly_hours": 6.00,
}
IMMEDIATE_PLACEMENT_SCORE = 205
IMMEDIATE_ENTRY_LEVEL = 2
IMMEDIATE_ATTENDANCE_DATE = "2026-08-02"
IMMEDIATE_HOURS = 3.25


def _math_candidate(full_name, email):
    return fixtures.create_placed_student(
        scale_score=MATH_PLACEMENT_SCORE,
        test_form=TestForm.CASAS_M_900,
        pre_test_at=PRE_TEST_AT,
        full_name=full_name,
        email=email,
        primary_track=ProgramTrack.HSE_PREP,
        self_pay_authorized=True,
    )


def _register(student_id, session_id, expected_exam_session_version):
    return api_client.create_exam_registration(
        factories.create_exam_registration_payload(
            student_id, session_id, expected_exam_session_version
        ),
        headers=make_registrar_headers(),
    )


def _setup_version_venue():
    """One scheduled MATH sitting with five free seats and two placed candidates."""
    center = fixtures.create_authorized_center(
        CenterDecision.GRANT_FULL, name="Version Center", state_code="SD"
    )
    room = fixtures.create_room(center["id"], room_code="VER-1", seat_capacity=10)
    proctor = fixtures.create_certified_proctor(
        center["id"], certification_expires_at=USABLE_EXPIRY, full_name="Vera Nolan"
    )
    draft = fixtures.create_session(
        center["id"],
        room["id"],
        VERSION_SITTING[0],
        VERSION_SITTING[1],
        subtest=Subtest.MATH,
        requested_seats=VERSION_SEATS,
    )
    scheduled = fixtures.assign_session_proctor(center["id"], draft["id"], proctor["id"])
    first = _math_candidate("Hana Vidal", "hana.vidal@example.org")
    second = _math_candidate("Iker Solano", "iker.solano@example.org")
    return {
        "session_id": draft["id"],
        "created_version": draft["version"],
        "assigned_version": scheduled["version"],
        "first_student_id": first["student_id"],
        "second_student_id": second["student_id"],
    }


def _setup_threshold_context():
    """A learner one quarter-hour short of forty, with two sittings waiting to be bought."""
    center = fixtures.create_authorized_center(
        CenterDecision.GRANT_FULL, name="Threshold Center", state_code="MT"
    )
    room = fixtures.create_room(center["id"], room_code="THR-1", seat_capacity=10)
    proctor = fixtures.create_certified_proctor(
        center["id"], certification_expires_at=USABLE_EXPIRY, full_name="Tess Arnaud"
    )
    sittings = []
    for starts_at, ends_at in THRESHOLD_SITTINGS:
        draft = fixtures.create_session(
            center["id"],
            room["id"],
            starts_at,
            ends_at,
            subtest=Subtest.MATH,
            requested_seats=THRESHOLD_SEATS,
        )
        scheduled = fixtures.assign_session_proctor(
            center["id"], draft["id"], proctor["id"]
        )
        sittings.append({"id": draft["id"], "version": scheduled["version"]})

    placed = _math_candidate("Jonas Pike", "jonas.pike@example.org")
    section = fixtures.create_section(
        status=SectionStatus.OPEN, program_track=ProgramTrack.HSE_PREP, **THRESHOLD_SECTION
    )
    enrollment = fixtures.enroll(placed["student_id"], section["id"])

    fixtures.set_clock(LEDGER_CLOCK)
    for attendance_date in FULL_DAYS:
        fixtures.post_attendance(enrollment["id"], attendance_date, FULL_DAY_HOURS)
    fixtures.post_attendance(enrollment["id"], SHORT_DAY, SHORT_DAY_HOURS)

    return {
        "student_id": placed["student_id"],
        "enrollment_id": enrollment["id"],
        "sittings": sittings,
    }


def _post_the_last_quarter_hour(enrollment_id):
    fixtures.set_clock(LATER_CLOCK)
    return fixtures.post_attendance(enrollment_id, LAST_DAY, LAST_DAY_HOURS)


def _setup_cascade_chain():
    """One proctor's signature underwriting four results, a credential, an order and a claim."""
    center = fixtures.create_authorized_center(
        CenterDecision.GRANT_FULL, name="Cascade Center", state_code="NH"
    )
    room = fixtures.create_room(center["id"], room_code="CASC-1", seat_capacity=10)
    proctor = fixtures.create_certified_proctor(
        center["id"], certification_expires_at=USABLE_EXPIRY, full_name="Nadia Ferro"
    )
    sittings = []
    for subtest, starts_at, ends_at in CASCADE_SITTINGS:
        draft = fixtures.create_session(
            center["id"],
            room["id"],
            starts_at,
            ends_at,
            subtest=subtest,
            requested_seats=CASCADE_SEATS,
        )
        scheduled = fixtures.assign_session_proctor(
            center["id"], draft["id"], proctor["id"]
        )
        sittings.append({"id": draft["id"], "version": scheduled["version"]})

    placed = fixtures.create_placed_student(
        scale_score=CASCADE_PLACEMENT_SCORE,
        test_form=TestForm.CASAS_M_900,
        pre_test_at=PRE_TEST_AT,
        full_name="Mira Okonkwo",
        email="mira.okonkwo@example.org",
        primary_track=ProgramTrack.HSE_PREP,
        self_pay_authorized=True,
    )
    student_id = placed["student_id"]
    registrations = [
        fixtures.register_candidate(
            student_id, sitting["id"], expected_exam_session_version=sitting["version"]
        )
        for sitting in sittings
    ]

    fixtures.set_clock(CASCADE_SEATING_CLOCK)
    for registration in registrations:
        fixtures.verify_candidate_identity(registration["id"], proctor["id"])
    for registration, seating_clock in zip(registrations, CASCADE_CHECK_IN_CLOCKS):
        fixtures.set_clock(seating_clock)
        fixtures.check_in_candidate(registration["id"], proctor["id"])
        fixtures.record_candidate_result(
            registration["id"], proctor["id"], CASCADE_SUBTEST_SCORE
        )

    credential = fixtures.issue_credential(student_id)
    order = fixtures.create_transcript_order(
        student_id,
        credential["id"],
        copies=2,
        delivery=TranscriptDelivery.STANDARD,
        destination_type=TranscriptDestination.EMPLOYER,
    )
    period = fixtures.create_funding_period(**CASCADE_PERIOD)
    outcome = fixtures.record_outcome(
        student_id,
        period["id"],
        measure_type=MeasureType.CREDENTIAL_ATTAINMENT,
        evidence_ref="ev-mira-cred",
        credential_issuance_id=credential["id"],
    )
    fixtures.decide_outcome(outcome["id"])
    run = fixtures.run_allocation(period["id"], variant=AllocationVariant.FINAL)

    return {
        "student_id": student_id,
        "proctor_id": proctor["id"],
        "session_ids": [sitting["id"] for sitting in sittings],
        "registration_ids": [registration["id"] for registration in registrations],
        "credential_id": credential["id"],
        "order_id": order["id"],
        "period_id": period["id"],
        "outcome_id": outcome["id"],
        "run": run,
    }


def _revoke(proctor_id):
    return fixtures.decide_proctor(
        proctor_id, ProctorDecision.REVOKE, certification_expires_at=None
    )


def _setup_immediate_learner_and_section():
    placed = fixtures.create_placed_student(
        scale_score=IMMEDIATE_PLACEMENT_SCORE,
        test_form=TestForm.CASAS_R_900,
        pre_test_at=PRE_TEST_AT,
        full_name="Sol Aguirre",
        email="sol.aguirre@example.org",
        primary_track=ProgramTrack.HSE_PREP,
    )
    section = fixtures.create_section(
        status=SectionStatus.OPEN, program_track=ProgramTrack.HSE_PREP, **IMMEDIATE_SECTION
    )
    return placed["student_id"], section


def _post_immediate_attendance(enrollment_id):
    return validate_success(
        api_client.create_attendance_entry(
            enrollment_id,
            factories.create_attendance_entry_payload(
                IMMEDIATE_ATTENDANCE_DATE, IMMEDIATE_HOURS
            ),
            headers=make_instructor_headers(),
        ),
        expected_status=201,
    )


def test_01_every_write_on_a_sitting_moves_the_counter_the_registrar_must_quote():
    """"`version` is an integer that starts at 1 when the record is created and increases by
    exactly one on every mutation of that record." and "It increments the sitting's `seats_taken`
    and raises the sitting's `version` by one."

    Design: Corner/cross-cutting complexity layers/exam_session_version_increments_on_every_write_and_the_current_version_is_accepted
    """
    venue = _setup_version_venue()
    assert venue["created_version"] == 1
    assert venue["assigned_version"] == 2

    validate_success(
        _register(
            venue["first_student_id"], venue["session_id"], venue["assigned_version"]
        ),
        expected_status=201,
    )

    after_first = fixtures.read_session(venue["session_id"], headers=make_registrar_headers())
    assert after_first["version"] == 3
    assert after_first["seats_taken"] == 1


def test_02_a_view_stale_by_one_write_is_refused_while_free_seats_remain():
    """"If it does not equal that parent's current `version`, the write is refused and nothing is
    changed." and "A mismatch is rejected with `ERR_STALE_EXAM_SESSION_VERSION` (412). The
    client's view may have gone stale because another registrar consumed a seat"

    Design: Corner/cross-cutting complexity layers/exam_session_version_increments_on_every_write_and_the_current_version_is_accepted
    """
    venue = _setup_version_venue()
    stale_version = venue["assigned_version"]
    validate_success(
        _register(venue["first_student_id"], venue["session_id"], stale_version),
        expected_status=201,
    )

    current_version = fixtures.read_session(venue["session_id"])["version"]
    refused = _register(venue["second_student_id"], venue["session_id"], stale_version)
    validate_error(refused, ApiErrorId.STALE_EXAM_SESSION_VERSION, expected_status=412)

    retry = validate_success(
        _register(venue["second_student_id"], venue["session_id"], current_version),
        expected_status=201,
    )
    assert retry["registration_status"] == RegistrationStatus.REGISTERED

    settled = fixtures.read_session(venue["session_id"])
    assert settled["version"] == 4
    assert settled["seats_taken"] == 2

    _rows, meta = validate_paginated(
        api_client.list_exam_registrations(
            headers=make_registrar_headers(),
            params={"exam_session_id": venue["session_id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 2


def test_03_one_quarter_hour_short_of_forty_earns_the_lower_tier_and_no_eligibility():
    """"The stored `post_test_eligible` flag on an enrollment tracks the hour gate alone: it is
    true exactly when `posted_hours` has reached at least forty hours, and false otherwise." and
    "From twelve hours up to but not including forty, the tier is 25 percent."

    Design: Corner/cross-cutting complexity layers/forty_hour_threshold_flips_post_test_eligibility_and_the_fee_tier_together
    """
    context = _setup_threshold_context()

    before = fixtures.read_enrollment(
        context["enrollment_id"], headers=make_program_coordinator_headers()
    )
    assert_hours_value(before["posted_hours"], HOURS_BEFORE)
    assert before["post_test_eligible"] is False

    first_sitting = context["sittings"][0]
    registration = validate_success(
        _register(context["student_id"], first_sitting["id"], first_sitting["version"]),
        expected_status=201,
    )
    assert registration["gross_fee_cents"] == MATH_BASE_FEE_CENTS
    assert registration["discount_cents"] == QUARTER_TIER_DISCOUNT_CENTS
    assert registration["fee_due_cents"] == QUARTER_TIER_DUE_CENTS


def test_04_the_last_quarter_hour_flips_the_flag_and_the_tier_in_one_posting():
    """"From forty hours up to but not including one hundred, it is 50 percent." and "the
    interval gate is evaluated first, so a learner who is short on both hours and days is told
    `ERR_POST_TEST_INTERVAL_NOT_MET`"

    Design: Corner/cross-cutting complexity layers/forty_hour_threshold_flips_post_test_eligibility_and_the_fee_tier_together
    """
    context = _setup_threshold_context()
    first_sitting, second_sitting = context["sittings"]
    validate_success(
        _register(context["student_id"], first_sitting["id"], first_sitting["version"]),
        expected_status=201,
    )

    _post_the_last_quarter_hour(context["enrollment_id"])

    after = fixtures.read_enrollment(
        context["enrollment_id"], headers=make_program_coordinator_headers()
    )
    assert_hours_value(after["posted_hours"], HOURS_AFTER)
    assert after["post_test_eligible"] is True

    registration = validate_success(
        _register(context["student_id"], second_sitting["id"], second_sitting["version"]),
        expected_status=201,
    )
    assert registration["gross_fee_cents"] == MATH_BASE_FEE_CENTS
    assert registration["discount_cents"] == HALF_TIER_DISCOUNT_CENTS
    assert registration["fee_due_cents"] == HALF_TIER_DUE_CENTS

    _entries, meta = validate_paginated(
        api_client.list_attendance_entries(
            headers=make_program_coordinator_headers(),
            params={"enrollment_id": context["enrollment_id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 6


def test_05_revoking_the_witness_invalidates_the_results_and_leaves_the_sittings_alone():
    """"`certification_expires_at` is left exactly as it was — the record of what the expiry had
    been is preserved — while `assigned_session_count` is set to 0." and "every registration
    anywhere whose `identity_verified_by_proctor_id` is the revoked proctor and whose
    `registration_status` is `SCORED` moves to `RESULT_INVALIDATED`, retaining its
    `result_outcome` and `scale_score` for audit" and "takes every exam session whose `proctor_id`
    is the revoked proctor and whose `status` is `SCHEDULED` back to `DRAFT`, clearing `proctor_id`
    to null"

    Design: Corner/cross-cutting complexity layers/proctor_revocation_cascade_five_links_from_registration_to_the_funding_pool
    """
    chain = _setup_cascade_chain()
    before_credential = fixtures.read_credential(chain["credential_id"])
    assert before_credential["status"] == CredentialIssuanceStatus.ISSUED
    assert before_credential["composite_score"] == CASCADE_COMPOSITE

    revoked = _revoke(chain["proctor_id"])
    assert revoked["certification_status"] == ProctorCertificationStatus.REVOKED
    assert revoked["assigned_session_count"] == 0

    sittings, sitting_meta = validate_paginated(
        api_client.list_exam_sessions(
            headers=make_state_authority_headers(),
            params={"proctor_id": chain["proctor_id"], "limit": 10, "offset": 0},
        )
    )
    assert sitting_meta["total_count"] == 4
    assert all(row["status"] == SessionStatus.COMPLETED for row in sittings)

    invalidated, invalidated_meta = validate_paginated(
        api_client.list_exam_registrations(
            headers=make_state_authority_headers(),
            params={
                "student_id": chain["student_id"],
                "registration_status": RegistrationStatus.RESULT_INVALIDATED,
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert invalidated_meta["total_count"] == 4
    assert all(row["result_outcome"] == ResultOutcome.PASSED for row in invalidated)
    assert all(row["scale_score"] == CASCADE_SUBTEST_SCORE for row in invalidated)


def test_06_the_void_travels_through_the_order_and_the_claim_back_into_the_pool():
    """"every credential issuance whose `status` is `ISSUED` and whose
    `qualifying_registration_ids` include an invalidated registration moves to `VOIDED` with
    `void_reason` set to `PROCTOR_REVOKED`, and the holder's `credential_status` becomes
    `REVOKED`." and "for each rescinded outcome whose `allocation_status` was `COMMITTED`, the
    funding period's `committed_cents` falls by that line's `allocated_cents`, its
    `available_cents` rises by the same amount, and the line becomes `REVOKED` with
    `allocated_cents` reset to 0." and "A credential that has been voided rather than issued is
    refused with `ERR_CREDENTIAL_NOT_ISSUED`."

    Design: Corner/cross-cutting complexity layers/proctor_revocation_cascade_five_links_from_registration_to_the_funding_pool
    """
    chain = _setup_cascade_chain()
    assert chain["run"]["committed_cents"] == CREDENTIAL_LINE_CENTS
    assert chain["run"]["available_cents"] == POOL_AFTER_RUN_CENTS

    before_order = fixtures.read_transcript_order(chain["order_id"])
    assert before_order["status"] == TranscriptOrderStatus.QUEUED
    before_outcome = fixtures.read_outcome(chain["outcome_id"])
    assert before_outcome["status"] == OutcomeStatus.CERTIFIED
    assert float(before_outcome["weight"]) == CREDENTIAL_WEIGHT
    assert before_outcome["allocated_cents"] == CREDENTIAL_LINE_CENTS
    assert before_outcome["allocation_status"] == AllocationStatus.COMMITTED

    _revoke(chain["proctor_id"])

    credential = fixtures.read_credential(chain["credential_id"])
    assert credential["status"] == CredentialIssuanceStatus.VOIDED
    assert credential["void_reason"] == VoidReason.PROCTOR_REVOKED
    assert (
        fixtures.read_student(chain["student_id"])["credential_status"]
        == CredentialStanding.REVOKED
    )

    order = fixtures.read_transcript_order(chain["order_id"])
    assert order["status"] == TranscriptOrderStatus.HELD
    assert order["hold_reason"] == HoldReason.CREDENTIAL_VOIDED
    assert order["fulfilled_at"] is None

    outcome = fixtures.read_outcome(chain["outcome_id"])
    assert outcome["status"] == OutcomeStatus.RESCINDED
    assert outcome["rescission_reason"] == RescissionReason.CREDENTIAL_VOIDED
    assert outcome["allocation_status"] == AllocationStatus.REVOKED
    assert outcome["allocated_cents"] == 0

    period = fixtures.read_funding_period(chain["period_id"])
    assert period["committed_cents"] == EMPTY_POOL_CENTS
    assert period["available_cents"] == CASCADE_PERIOD["total_cents"]

    refused = api_client.create_transcript_order(
        chain["student_id"],
        factories.create_transcript_order_payload(
            chain["credential_id"],
            copies=1,
            delivery=TranscriptDelivery.STANDARD,
            destination_type=TranscriptDestination.SELF,
        ),
        headers=make_registrar_headers(),
    )
    validate_error(refused, ApiErrorId.CREDENTIAL_NOT_ISSUED, expected_status=409)

    _orders, order_meta = validate_paginated(
        api_client.list_transcript_orders(
            headers=make_state_authority_headers(),
            params={
                "credential_issuance_id": chain["credential_id"],
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert order_meta["total_count"] == 1


def test_07_the_parent_counter_and_the_hour_accumulator_are_current_on_the_next_read():
    """"Creation also increments the section's `seats_taken` and recomputes `seats_available`,
    increments the learner's `active_enrollment_count`" and "Posting also re-evaluates the
    enrollment's `post_test_eligible` flag and increases the enrollment's `version` by one"

    Design: Corner/consistency model/derived_fields_are_visible_immediately_in_the_same_request_cycle
    """
    student_id, section = _setup_immediate_learner_and_section()

    enrollment = validate_success(
        api_client.create_enrollment(
            factories.create_enrollment_payload(student_id, section["id"]),
            headers=make_program_coordinator_headers(),
        ),
        expected_status=201,
    )
    assert enrollment["status"] == EnrollmentStatus.ACTIVE
    assert enrollment["entry_efl_level"] == IMMEDIATE_ENTRY_LEVEL

    assert (
        fixtures.read_class_section(section["id"])["seats_taken"] == 1
    )

    _post_immediate_attendance(enrollment["id"])

    posted = fixtures.read_enrollment(enrollment["id"], headers=make_instructor_headers())
    assert_hours_value(posted["posted_hours"], IMMEDIATE_HOURS)
    assert posted["post_test_eligible"] is False


def test_08_the_closing_transition_has_already_settled_the_enrollment_it_returns():
    """"an enrollment whose `posted_hours` has reached at least forty hours becomes `COMPLETED`,
    while one below that threshold becomes `WITHDRAWN`. Both outcomes record `exit_reason` as
    `SECTION_CLOSED`, but only the `WITHDRAWN` branch stamps `withdrawn_at` with the logical
    clock's current instant"

    Design: Corner/consistency model/derived_fields_are_visible_immediately_in_the_same_request_cycle
    """
    student_id, section = _setup_immediate_learner_and_section()
    enrollment = fixtures.enroll(student_id, section["id"])
    _post_immediate_attendance(enrollment["id"])

    fixtures.transition_section(section["id"], SectionStatus.IN_SESSION)
    closed = validate_success(
        api_client.transition_class_section(
            section["id"],
            factories.section_transition_payload(SectionStatus.CLOSED),
            headers=make_program_coordinator_headers(),
        )
    )
    assert closed["status"] == SectionStatus.CLOSED

    settled = fixtures.read_enrollment(
        enrollment["id"], headers=make_program_coordinator_headers()
    )
    assert settled["status"] == EnrollmentStatus.WITHDRAWN
    assert settled["withdrawn_at"] == PRE_TEST_AT
