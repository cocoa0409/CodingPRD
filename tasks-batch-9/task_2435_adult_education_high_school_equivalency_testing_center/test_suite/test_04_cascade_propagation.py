"""Three cascades with different triggers and different depths: an hour-ledger void,
a certification revocation, and a centre suspension.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error

from test_helpers import ApiErrorId, api_client, factories, fixtures
from test_helpers.assertions import (
    assert_funding_pool_conserved,
    assert_hours_value,
    assert_voucher_ledger_conserved,
)
from test_helpers.test_users import (
    make_center_administrator_headers,
    make_state_authority_headers,
)
from test_helpers.types import (
    AllocationStatus,
    AllocationVariant,
    AttendanceStatus,
    CancelReason,
    CenterAuthorizationStatus,
    IdentityStatus,
    InvalidationReason,
    MeasureType,
    MsgVariant,
    OutcomeStatus,
    ProctorCertificationStatus,
    ProctorDecision,
    ProgramTrack,
    RegistrationStatus,
    RescissionReason,
    RoomStatus,
    SessionStatus,
    Subtest,
    TestEventStatus,
)

POST_TEST_AT = "2026-09-02T10:00:00Z"

REVOCATION_SITTING_STARTS = "2026-08-05T09:00:00Z"
REVOCATION_SITTING_ENDS = "2026-08-05T11:00:00Z"
INSIDE_SEATING_WINDOW = "2026-08-05T08:30:00Z"

SUSPENSION_SITTING_STARTS = "2026-08-10T09:00:00Z"
SUSPENSION_SITTING_ENDS = "2026-08-10T11:00:00Z"
LATER_SITTING_STARTS = "2026-08-12T09:00:00Z"
LATER_SITTING_ENDS = "2026-08-12T11:00:00Z"


def _setup_committed_gain_on_forty_hours():
    """A certified, allocated skill-gain claim resting on exactly 40.00 posted hours."""
    period = fixtures.create_funding_period(rate_cents_per_weight=10000, total_cents=100000)
    context = fixtures.setup_enrollment_with_hours(
        total_hours=40.00,
        program_track=ProgramTrack.LITERACY,
        scale_score=205,
        first_date="2026-08-03",
        section_overrides={"title": "Literacy AM", "seats_total": 15, "weekly_hours": 8.00},
    )
    student_id = context["student_id"]
    enrollment_id = context["enrollment"]["id"]
    post_test = fixtures.score_post_test(student_id, enrollment_id, POST_TEST_AT, 225)
    outcome = fixtures.record_outcome(
        student_id,
        period["id"],
        measure_type=MeasureType.EFL_GAIN,
        evidence_ref="NRS-EFL-9",
    )
    fixtures.decide_outcome(outcome["id"])
    fixtures.run_allocation(period["id"], variant=AllocationVariant.FINAL)
    return {
        "period_id": period["id"],
        "student_id": student_id,
        "enrollment_id": enrollment_id,
        "first_entry_id": context["entries"][0]["id"],
        "pre_test_id": context["pre_test"]["id"],
        "post_test_id": post_test["id"],
        "outcome_id": outcome["id"],
    }


def _setup_verified_candidate_before_revocation():
    context = fixtures.setup_registered_candidate(
        starts_at=REVOCATION_SITTING_STARTS,
        ends_at=REVOCATION_SITTING_ENDS,
        subtest=Subtest.MATH,
        self_pay_authorized=True,
        requested_seats=4,
        seat_capacity=8,
        turnaround_buffer_minutes=45,
        daily_hour_cap=8.00,
    )
    fixtures.ensure_clock(INSIDE_SEATING_WINDOW)
    fixtures.verify_candidate_identity(context["registration_id"], context["proctor_id"])
    return context


def _setup_voucher_funded_seat_before_suspension():
    return fixtures.setup_registered_candidate(
        starts_at=SUSPENSION_SITTING_STARTS,
        ends_at=SUSPENSION_SITTING_ENDS,
        subtest=Subtest.MATH,
        self_pay_authorized=True,
        voucher_cents=5000,
        requested_seats=4,
        seat_capacity=8,
        turnaround_buffer_minutes=45,
        daily_hour_cap=8.00,
    )


def test_01_voiding_an_entry_withdraws_hours_and_invalidates_the_post_test():
    """"**Link 1** subtracts the voided entry's `hours` from the enrollment's
    `posted_hours` and from the learner's `total_instructional_hours`, and recomputes
    the enrollment's `post_test_eligible` flag from the new total. **Link 2** fires only
    when that subtraction drops `posted_hours` below forty hours: every test event
    carrying this `enrollment_id` whose `purpose` is `POST_TEST` and whose `status` is
    `SCHEDULED` or `SCORED` is walked in `created_at` ascending order and moved to
    `INVALIDATED`, with `invalidation_reason` set to `HOURS_WITHDRAWN`."

    Design: Difficulty/transitive_cascade/attendance_void_hours_posttest_outcome_funding_depth4
    """
    context = _setup_committed_gain_on_forty_hours()

    before = fixtures.read_enrollment(context["enrollment_id"])
    assert_hours_value(before["posted_hours"], 40.00)
    assert before["post_test_eligible"] is True

    voided = fixtures.void_attendance(
        context["first_entry_id"],
        context["enrollment_id"],
        void_reason="Sign-in sheet was for another section",
    )
    assert voided["status"] == AttendanceStatus.VOIDED

    after = fixtures.read_enrollment(context["enrollment_id"])
    assert_hours_value(after["posted_hours"], 32.00)
    assert after["post_test_eligible"] is False
    assert_hours_value(
        fixtures.read_student(context["student_id"])["total_instructional_hours"], 32.00
    )

    post_test = fixtures.read_test_event(context["post_test_id"])
    assert post_test["status"] == TestEventStatus.INVALIDATED
    assert post_test["invalidation_reason"] == InvalidationReason.HOURS_WITHDRAWN

    pre_test = fixtures.read_test_event(context["pre_test_id"])
    assert pre_test["status"] == TestEventStatus.SCORED
    assert pre_test["invalidation_reason"] is None


def test_02_losing_the_post_test_rescinds_the_claim_and_returns_the_money():
    """"**Link 4**, caused by link 3, unwinds the money: for each rescinded outcome whose
    `allocation_status` was `COMMITTED`, the funding period's `committed_cents` is
    reduced by that line's `allocated_cents`, the same amount is returned to the
    period's `available_cents`, the line's `allocation_status` becomes `REVOKED` and its
    `allocated_cents` becomes 0."

    Design: Difficulty/transitive_cascade/attendance_void_hours_posttest_outcome_funding_depth4
    """
    context = _setup_committed_gain_on_forty_hours()

    before_period = fixtures.read_funding_period(context["period_id"])
    assert before_period["committed_cents"] == 10000
    assert before_period["available_cents"] == 90000
    before_outcome = fixtures.read_outcome(context["outcome_id"])
    assert before_outcome["status"] == OutcomeStatus.CERTIFIED
    assert before_outcome["allocated_cents"] == 10000
    assert before_outcome["allocation_status"] == AllocationStatus.COMMITTED

    fixtures.void_attendance(
        context["first_entry_id"],
        context["enrollment_id"],
        void_reason="Sign-in sheet was for another section",
    )

    outcome = fixtures.read_outcome(context["outcome_id"])
    assert outcome["status"] == OutcomeStatus.RESCINDED
    assert outcome["rescission_reason"] == RescissionReason.POST_TEST_INVALIDATED
    assert outcome["allocated_cents"] == 0
    assert outcome["allocation_status"] == AllocationStatus.REVOKED

    period = fixtures.read_funding_period(context["period_id"])
    assert_funding_pool_conserved(period)
    assert period["committed_cents"] == 0
    assert period["available_cents"] == 100000


def test_03_the_audited_reading_reports_no_gain_once_the_post_test_is_invalidated():
    """"events that are `SCHEDULED` or `INVALIDATED` are excluded from consideration
    entirely. When there is no qualifying pre-test, or no qualifying post-test at all,
    no gain is claimed: the determination reports a null post side and no achievement."

    Design: Difficulty/transitive_cascade/attendance_void_hours_posttest_outcome_funding_depth4
    """
    context = _setup_committed_gain_on_forty_hours()

    fixtures.void_attendance(
        context["first_entry_id"],
        context["enrollment_id"],
        void_reason="Sign-in sheet was for another section",
    )

    reading = fixtures.read_skill_gain(
        context["student_id"],
        variant=MsgVariant.LATEST_POST,
        funding_period_id=context["period_id"],
    )
    assert reading["msg_achieved"] is False
    assert reading["post_efl_level"] is None


def test_04_revocation_reverts_the_sitting_and_clears_the_assigned_load():
    """"**Link 1** takes every exam session whose `proctor_id` is the revoked proctor and
    whose `status` is `SCHEDULED` back to `DRAFT`, clearing `proctor_id` to null — the
    sitting is not cancelled, it merely loses its supervisor and becomes re-assignable
    to another certified proctor"

    Design: Difficulty/transitive_cascade/proctor_revocation_session_identity_depth2
    """
    context = _setup_verified_candidate_before_revocation()

    revoked = fixtures.decide_proctor(
        context["proctor_id"], ProctorDecision.REVOKE, certification_expires_at=None
    )
    assert revoked["certification_status"] == ProctorCertificationStatus.REVOKED
    assert revoked["assigned_session_count"] == 0

    session = fixtures.read_session(context["session_id"])
    assert session["status"] == SessionStatus.DRAFT
    assert session["proctor_id"] is None
    assert session["seats_taken"] == 1


def test_05_the_withdrawn_signature_resets_identity_and_the_chain_stops_there():
    """"**Link 2a**, caused by link 1, resets identity on those reverted sessions: every
    registration on them whose `identity_status` is `VERIFIED` returns to `UNVERIFIED`
    and has `identity_verified_by_proctor_id` cleared to null, while
    `identity_document_type` is retained for audit."

    Design: Difficulty/transitive_cascade/proctor_revocation_session_identity_depth2
    """
    context = _setup_verified_candidate_before_revocation()
    before = fixtures.read_registration(context["registration_id"])

    fixtures.decide_proctor(
        context["proctor_id"], ProctorDecision.REVOKE, certification_expires_at=None
    )

    registration = fixtures.read_registration(context["registration_id"])
    assert registration["identity_status"] == IdentityStatus.UNVERIFIED
    assert registration["identity_verified_by_proctor_id"] is None
    assert registration["identity_document_type"] == before["identity_document_type"]

    # The seat axis and the money are untouched: the candidate was never seated, so
    # there is no scored registration for links 2b through 5 to reach.
    assert registration["registration_status"] == RegistrationStatus.REGISTERED
    assert registration["fee_due_cents"] == before["fee_due_cents"]
    assert registration["refunded_cents"] == 0
    assert fixtures.list_all(api_client.list_credentials, make_state_authority_headers()) == []


def test_06_suspension_empties_the_scope_and_retires_the_active_room():
    """"the centre moves to `SUSPENDED`, which is terminal, its supplied reason is
    recorded, its `allowed_subtests` is emptied and its `max_sessions_per_week` is set
    to 0." and "**Link 1** takes every testing room of that centre whose `status` is
    `ACTIVE` to `OUT_OF_SERVICE`."

    Design: Difficulty/transitive_cascade/center_suspension_room_session_registration_voucher_depth4
    """
    context = _setup_voucher_funded_seat_before_suspension()

    suspended = fixtures.suspend_center(
        context["center_id"], "State audit finding: unsecured test materials"
    )
    assert suspended["authorization_status"] == CenterAuthorizationStatus.SUSPENDED
    assert suspended["allowed_subtests"] == []
    assert suspended["max_sessions_per_week"] == 0
    assert suspended["suspended_reason"] == "State audit finding: unsecured test materials"

    room = fixtures.read_testing_room(context["room_id"])
    assert room["status"] == RoomStatus.OUT_OF_SERVICE

    # A new sitting in that room is refused by the centre gate.
    refused = api_client.create_exam_session(
        factories.create_exam_session_payload(
            context["room_id"],
            LATER_SITTING_STARTS,
            LATER_SITTING_ENDS,
            subtest=Subtest.MATH,
            requested_seats=4,
        ),
        headers=make_center_administrator_headers(context["center_id"]),
    )
    validate_error(refused, ApiErrorId.CENTER_SUSPENDED, expected_status=409)


def test_07_the_retired_room_cancels_its_sitting_and_frees_the_proctor():
    """"**Link 2**, caused by link 1, cancels every exam session in those rooms whose
    `status` is `DRAFT` or `SCHEDULED`, setting each one's `cancel_reason` to
    `CENTER_SUSPENDED`; where a cancelled session had a proctor assigned, that proctor's
    `assigned_session_count` is decremented."

    Design: Difficulty/transitive_cascade/center_suspension_room_session_registration_voucher_depth4
    """
    context = _setup_voucher_funded_seat_before_suspension()

    before_session = fixtures.read_session(context["session_id"])
    assert before_session["status"] == SessionStatus.SCHEDULED
    assert before_session["seats_taken"] == 1

    fixtures.suspend_center(context["center_id"], "State audit finding")

    session = fixtures.read_session(context["session_id"])
    assert session["status"] == SessionStatus.CANCELLED
    assert session["cancel_reason"] == CancelReason.CENTER_SUSPENDED
    assert session["seats_taken"] == 0

    assert fixtures.read_proctor(context["proctor_id"])["assigned_session_count"] == 0


def test_08_the_cancelled_seat_is_refunded_onto_the_learner_ledger():
    """"**Link 3**, caused by link 2, takes every registration on each cancelled session
    whose `registration_status` is `REGISTERED` to `CANCELLED_BY_CENTER`, sets its
    `refunded_cents` to whatever it had consumed as `voucher_applied_cents`" and
    "**Link 4**, caused by link 3, settles the learner ledgers: for each refunded
    registration the learner's `voucher_balance_cents` rises by the refunded amount,
    their `voucher_spent_cents` falls by the same amount, and their
    `exam_fee_owed_cents` falls by that registration's `fee_due_cents`."

    Design: Difficulty/transitive_cascade/center_suspension_room_session_registration_voucher_depth4
    """
    context = _setup_voucher_funded_seat_before_suspension()

    before_student = fixtures.read_student(context["student_id"])
    assert before_student["voucher_balance_cents"] == 2000
    assert before_student["voucher_spent_cents"] == 3000

    fixtures.suspend_center(context["center_id"], "State audit finding")

    registration = fixtures.read_registration(context["registration_id"])
    assert registration["registration_status"] == RegistrationStatus.CANCELLED_BY_CENTER
    assert registration["refunded_cents"] == 3000

    student = fixtures.read_student(context["student_id"])
    assert_voucher_ledger_conserved(student)
    assert student["voucher_balance_cents"] == 5000
    assert student["voucher_spent_cents"] == 0
    assert student["exam_fee_owed_cents"] == 0
