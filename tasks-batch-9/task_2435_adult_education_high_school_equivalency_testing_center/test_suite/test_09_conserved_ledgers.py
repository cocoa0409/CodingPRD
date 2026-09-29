"""Three conserved quantities held across compensating operations: the learner's voucher
ledger, the period's funding pool, and the instructional-hour ledger at both levels.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId, api_client, factories, fixtures
from test_helpers.assertions import (
    assert_funding_pool_conserved,
    assert_hours_value,
    assert_voucher_ledger_conserved,
)
from test_helpers.test_users import (
    make_program_coordinator_headers,
    make_registrar_headers,
)
from test_helpers.types import (
    AllocationStatus,
    AllocationVariant,
    AttendanceStatus,
    CenterDecision,
    MeasureType,
    OutcomeStatus,
    ProgramTrack,
    RegistrationStatus,
    RescissionReason,
    SectionStatus,
    Subtest,
)

VOUCHER_SITTING_STARTS = "2026-08-10T09:00:00Z"
VOUCHER_SITTING_ENDS = "2026-08-10T11:00:00Z"
VOUCHER_GRANT_CENTS = 5000
MATH_SEAT_CENTS = 3000

FUNDING_PRE_TEST_AT = "2026-08-03T09:00:00Z"
FUNDING_POST_TEST_AT = "2026-09-02T10:00:00Z"
FUNDING_TOTAL_CENTS = 25000
FUNDING_RATE_CENTS = 10000

HOUR_LEDGER_DATES = ("2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07")
ESL_HOUR_DATES = ("2026-08-05", "2026-08-06")


# ---------------------------------------------------------------------------
# Instance builders
# ---------------------------------------------------------------------------


def _setup_voucher_funded_candidate():
    """A learner who cannot self-pay, holding a 5000-cent grant against a 3000-cent seat."""
    center = fixtures.create_authorized_center(
        CenterDecision.GRANT_FULL, name="Ledger Center", state_code="OH"
    )
    room = fixtures.create_room(
        center["id"], room_code="R1", seat_capacity=8, turnaround_buffer_minutes=45
    )
    proctor = fixtures.create_certified_proctor(
        center["id"],
        certification_expires_at="2027-01-01T00:00:00Z",
        full_name="Zeke Proctor",
        daily_hour_cap=8.00,
    )
    placed = fixtures.create_placed_student(
        scale_score=205, pre_test_at="2026-08-02T09:00:00Z"
    )
    fixtures.grant_voucher(placed["student_id"], VOUCHER_GRANT_CENTS)
    session = fixtures.create_session(
        center["id"],
        room["id"],
        VOUCHER_SITTING_STARTS,
        VOUCHER_SITTING_ENDS,
        subtest=Subtest.MATH,
        requested_seats=4,
    )
    scheduled = fixtures.assign_session_proctor(center["id"], session["id"], proctor["id"])
    return {
        "center_id": center["id"],
        "student_id": placed["student_id"],
        "session_id": session["id"],
        "session_version": scheduled["version"],
    }


def _cancel_registration(registration_id):
    return api_client.cancel_exam_registration(
        registration_id, headers=make_registrar_headers()
    )


def _setup_two_committed_lines_on_a_tight_pool():
    """A 25000-cent pool carrying an EFL_GAIN line of 10000 and a second line of 14000."""
    period = fixtures.create_funding_period(
        label="PY2026",
        rate_cents_per_weight=FUNDING_RATE_CENTS,
        total_cents=FUNDING_TOTAL_CENTS,
    )
    gainer = fixtures.setup_enrollment_with_hours(
        total_hours=40.00,
        program_track=ProgramTrack.HSE_PREP,
        scale_score=205,
        first_date=HOUR_LEDGER_DATES[0],
        section_overrides={"title": "HSE Ledger", "seats_total": 10, "weekly_hours": 8.00},
    )
    enrollment_id = gainer["enrollment"]["id"]
    fixtures.score_post_test(
        gainer["student_id"], enrollment_id, FUNDING_POST_TEST_AT, 225
    )
    other = fixtures.create_student()

    gain_line = fixtures.certified_outcome(
        gainer["student_id"],
        period["id"],
        measure_type=MeasureType.EFL_GAIN,
        evidence_ref="NRS-EFL-A",
    )
    other_line = fixtures.certified_outcome(
        other["id"],
        period["id"],
        measure_type=MeasureType.POSTSECONDARY_ENROLLMENT,
        evidence_ref="NSC-B",
    )
    fixtures.run_allocation(period["id"], variant=AllocationVariant.FINAL)
    return {
        "period_id": period["id"],
        "enrollment_id": enrollment_id,
        "first_entry_id": gainer["entries"][0]["id"],
        "gain_line_id": gain_line["id"],
        "other_line_id": other_line["id"],
    }


def _setup_two_enrollments_with_posted_hours():
    """One learner banking 40.00 hours on one track and 10.00 on another."""
    placed = fixtures.create_placed_student(scale_score=205, pre_test_at=FUNDING_PRE_TEST_AT)
    hse_section = fixtures.create_section(
        status=SectionStatus.OPEN,
        program_track=ProgramTrack.HSE_PREP,
        title="HSE Hours",
        seats_total=10,
        weekly_hours=8.00,
    )
    esl_section = fixtures.create_section(
        status=SectionStatus.OPEN,
        program_track=ProgramTrack.ESL,
        title="ESL Hours",
        instructor_user_id="instructor-2",
        seats_total=10,
        weekly_hours=4.00,
    )
    hse_enrollment = fixtures.enroll(placed["student_id"], hse_section["id"])
    esl_enrollment = fixtures.enroll(placed["student_id"], esl_section["id"])

    hse_entries = [
        fixtures.post_attendance(hse_enrollment["id"], date, 8.00) for date in HOUR_LEDGER_DATES
    ]
    for date in ESL_HOUR_DATES:
        fixtures.post_attendance(esl_enrollment["id"], date, 5.00)

    return {
        "student_id": placed["student_id"],
        "hse_enrollment_id": hse_enrollment["id"],
        "esl_enrollment_id": esl_enrollment["id"],
        "first_entry_id": hse_entries[0]["id"],
        "second_entry_id": hse_entries[1]["id"],
    }


def _void(entry_id, version, void_reason="Wrong roster"):
    return api_client.void_attendance_entry(
        entry_id,
        factories.void_attendance_payload(version, void_reason=void_reason),
        headers=make_program_coordinator_headers(),
    )


def _posted_entries(enrollment_id):
    return fixtures.list_all(
        api_client.list_attendance_entries,
        make_program_coordinator_headers(),
        enrollment_id=enrollment_id,
        status=AttendanceStatus.POSTED,
    )


# ---------------------------------------------------------------------------
# The voucher ledger
# ---------------------------------------------------------------------------


def test_01_applying_a_voucher_moves_cents_from_balance_to_spent():
    """"The **voucher ledger** on a learner satisfies a single identity: the lifetime
    `voucher_granted_cents` always equals `voucher_balance_cents` plus
    `voucher_spent_cents`." and "Applying a voucher to a registration moves cents from
    balance to spent; refunding a registration moves exactly the same cents back."

    Design: Difficulty/compensating_invariant/voucher_cents_conserved_across_registration_and_cancellation
    """
    context = _setup_voucher_funded_candidate()

    before = fixtures.read_student(context["student_id"])
    assert_voucher_ledger_conserved(before)
    assert before["voucher_granted_cents"] == VOUCHER_GRANT_CENTS
    assert before["voucher_balance_cents"] == VOUCHER_GRANT_CENTS
    assert before["voucher_spent_cents"] == 0
    assert before["exam_fee_owed_cents"] == 0

    registration = fixtures.register_candidate(
        context["student_id"],
        context["session_id"],
        expected_exam_session_version=context["session_version"],
    )
    assert registration["voucher_applied_cents"] == MATH_SEAT_CENTS
    assert registration["fee_due_cents"] == 0

    after = fixtures.read_student(context["student_id"])
    assert_voucher_ledger_conserved(after)
    assert after["voucher_balance_cents"] == 2000
    assert after["voucher_spent_cents"] == MATH_SEAT_CENTS
    assert after["voucher_granted_cents"] == VOUCHER_GRANT_CENTS
    assert fixtures.read_session(context["session_id"])["seats_taken"] == 1


def test_02_cancelling_returns_exactly_the_same_cents_and_releases_the_seat():
    """"It moves `registration_status` to `CANCELLED`, sets `refunded_cents` to whatever the
    registration had consumed as `voucher_applied_cents`, releases the seat by decrementing
    the sitting's `seats_taken`, and settles the learner ledger by raising
    `voucher_balance_cents` by the refunded amount, lowering `voucher_spent_cents` by the
    same amount, and lowering `exam_fee_owed_cents` by the registration's `fee_due_cents`."

    Design: Difficulty/compensating_invariant/voucher_cents_conserved_across_registration_and_cancellation
    """
    context = _setup_voucher_funded_candidate()
    registration = fixtures.register_candidate(
        context["student_id"],
        context["session_id"],
        expected_exam_session_version=context["session_version"],
    )

    cancelled = validate_success(_cancel_registration(registration["id"]))
    assert cancelled["registration_status"] == RegistrationStatus.CANCELLED
    assert cancelled["refunded_cents"] == MATH_SEAT_CENTS

    student = fixtures.read_student(context["student_id"])
    assert_voucher_ledger_conserved(student)
    assert student["voucher_balance_cents"] == VOUCHER_GRANT_CENTS
    assert student["voucher_spent_cents"] == 0
    assert student["voucher_granted_cents"] == VOUCHER_GRANT_CENTS
    assert student["exam_fee_owed_cents"] == 0
    assert fixtures.read_session(context["session_id"])["seats_taken"] == 0


def test_03_a_second_cancellation_cannot_apply_the_refund_twice():
    """"Cancellation by a `Registrar` or by the `Student` applies only to a registration
    still `REGISTERED`; anything else reports `ERR_REGISTRATION_NOT_OPEN`." and "A retake
    multiplier is derived from `prior_scored_attempts`, the count of the learner's *earlier*
    registrations on the **same** subtest whose `registration_status` is `SCORED` or
    `RESULT_INVALIDATED`, frozen onto the new registration at creation."

    Design: Difficulty/compensating_invariant/voucher_cents_conserved_across_registration_and_cancellation
    """
    context = _setup_voucher_funded_candidate()
    registration = fixtures.register_candidate(
        context["student_id"],
        context["session_id"],
        expected_exam_session_version=context["session_version"],
    )
    validate_success(_cancel_registration(registration["id"]))

    repeat = _cancel_registration(registration["id"])
    validate_error(repeat, ApiErrorId.REGISTRATION_NOT_OPEN, expected_status=409)

    unchanged = fixtures.read_registration(registration["id"])
    assert unchanged["refunded_cents"] == MATH_SEAT_CENTS
    student_after_refusal = fixtures.read_student(context["student_id"])
    assert_voucher_ledger_conserved(student_after_refusal)
    assert student_after_refusal["voucher_balance_cents"] == VOUCHER_GRANT_CENTS

    # Re-registering draws exactly the same cents again, and the cancelled seat was
    # never a scored attempt, so no retake multiplier applies.
    again = fixtures.register_candidate(
        context["student_id"],
        context["session_id"],
        expected_exam_session_version=fixtures.current_exam_session_version(
            context["session_id"]
        ),
    )
    assert again["prior_scored_attempts"] == 0
    assert again["voucher_applied_cents"] == MATH_SEAT_CENTS

    student = fixtures.read_student(context["student_id"])
    assert_voucher_ledger_conserved(student)
    assert student["voucher_balance_cents"] == 2000
    assert student["voucher_spent_cents"] == MATH_SEAT_CENTS
    assert student["voucher_granted_cents"] == VOUCHER_GRANT_CENTS


# ---------------------------------------------------------------------------
# The funding pool
# ---------------------------------------------------------------------------


def test_04_a_run_commits_the_exact_rounded_sum_of_its_lines():
    """"When the walk finishes, the period's `committed_cents` rises by the exact integer
    sum of the committed line amounts, each already rounded, and `available_cents` is
    recomputed as `total_cents` less `committed_cents`."

    Design: Difficulty/compensating_invariant/funding_cents_conserved_across_allocation_and_rescission
    """
    context = _setup_two_committed_lines_on_a_tight_pool()

    period = fixtures.read_funding_period(context["period_id"])
    assert_funding_pool_conserved(period)
    assert period["committed_cents"] == 24000
    assert period["available_cents"] == 1000
    assert period["total_cents"] == FUNDING_TOTAL_CENTS

    gain_line = fixtures.read_outcome(context["gain_line_id"])
    assert gain_line["allocated_cents"] == 10000
    assert gain_line["allocation_status"] == AllocationStatus.COMMITTED

    other_line = fixtures.read_outcome(context["other_line_id"])
    assert other_line["allocated_cents"] == 14000
    assert other_line["allocation_status"] == AllocationStatus.COMMITTED

    assert (
        gain_line["allocated_cents"] + other_line["allocated_cents"]
        == period["committed_cents"]
    )


def test_05_revoking_one_line_returns_its_cents_and_leaves_the_other_alone():
    """"The **funding pool** on a period satisfies `available_cents` equalling `total_cents`
    less `committed_cents`, where `committed_cents` is the sum of `allocated_cents` over
    that period's outcome lines whose `allocation_status` is `COMMITTED`. Revoking a
    committed line returns its cents to the pool in the same request that revokes it."

    Design: Difficulty/compensating_invariant/funding_cents_conserved_across_allocation_and_rescission
    """
    context = _setup_two_committed_lines_on_a_tight_pool()

    fixtures.void_attendance(
        context["first_entry_id"],
        context["enrollment_id"],
        void_reason="Duplicate sign-in",
    )

    rescinded = fixtures.read_outcome(context["gain_line_id"])
    assert rescinded["status"] == OutcomeStatus.RESCINDED
    assert rescinded["rescission_reason"] == RescissionReason.POST_TEST_INVALIDATED
    assert rescinded["allocated_cents"] == 0
    assert rescinded["allocation_status"] == AllocationStatus.REVOKED

    untouched = fixtures.read_outcome(context["other_line_id"])
    assert untouched["status"] == OutcomeStatus.CERTIFIED
    assert untouched["allocated_cents"] == 14000
    assert untouched["allocation_status"] == AllocationStatus.COMMITTED

    period = fixtures.read_funding_period(context["period_id"])
    assert_funding_pool_conserved(period)
    assert period["committed_cents"] == 14000
    assert period["available_cents"] == 11000


def test_06_a_revoked_line_never_re_enters_a_later_run():
    """"Claims that are `RESCINDED` or `REJECTED` never qualify under either variant, and
    claims already `COMMITTED`, `DEFERRED` or `REVOKED` never re-enter a run at all — in
    particular a line deferred for lack of funds is not reconsidered by a later run even if
    the pool has since recovered."

    Design: Difficulty/compensating_invariant/funding_cents_conserved_across_allocation_and_rescission
    """
    context = _setup_two_committed_lines_on_a_tight_pool()
    fixtures.void_attendance(
        context["first_entry_id"],
        context["enrollment_id"],
        void_reason="Duplicate sign-in",
    )

    rerun = fixtures.run_allocation(context["period_id"], variant=AllocationVariant.FINAL)
    assert_funding_pool_conserved(rerun)
    assert rerun["committed_cents"] == 14000
    assert rerun["available_cents"] == 11000
    assert rerun["allocation_run_count"] == 2

    revoked = fixtures.read_outcome(context["gain_line_id"])
    assert revoked["allocation_status"] == AllocationStatus.REVOKED
    assert revoked["allocated_cents"] == 0
    assert (
        fixtures.read_outcome(context["other_line_id"])["allocated_cents"]
        == rerun["committed_cents"]
    )


# ---------------------------------------------------------------------------
# The instructional-hour ledger
# ---------------------------------------------------------------------------


def test_07_the_hour_ledger_holds_at_both_levels_across_a_void():
    """"An enrollment's `posted_hours` is the sum of the `hours` of that enrollment's
    entries whose `status` is `POSTED` — voided entries contribute nothing. A learner's
    `total_instructional_hours` is the sum of `posted_hours` across every one of that
    learner's enrollments regardless of enrollment status"

    Design: Difficulty/compensating_invariant/instructional_hours_conserved_across_post_and_void
    """
    context = _setup_two_enrollments_with_posted_hours()

    assert_hours_value(
        fixtures.read_enrollment(context["hse_enrollment_id"])["posted_hours"], 40.00
    )
    assert_hours_value(
        fixtures.read_enrollment(context["esl_enrollment_id"])["posted_hours"], 10.00
    )
    assert_hours_value(
        fixtures.read_student(context["student_id"])["total_instructional_hours"], 50.00
    )

    fixtures.void_attendance(context["first_entry_id"], context["hse_enrollment_id"])

    hse = fixtures.read_enrollment(context["hse_enrollment_id"])
    assert_hours_value(hse["posted_hours"], 32.00)
    assert hse["post_test_eligible"] is False
    assert_hours_value(
        fixtures.read_enrollment(context["esl_enrollment_id"])["posted_hours"], 10.00
    )
    assert_hours_value(
        fixtures.read_student(context["student_id"])["total_instructional_hours"], 42.00
    )


def test_08_a_stale_view_void_subtracts_nothing_at_all():
    """"Voiding an attendance entry requires `expected_enrollment_version` matching the
    parent `Enrollment`'s current `version`. A mismatch is rejected with
    `ERR_STALE_ENROLLMENT_VERSION` (412)."

    Design: Difficulty/compensating_invariant/instructional_hours_conserved_across_post_and_void
    """
    context = _setup_two_enrollments_with_posted_hours()
    stale_version = fixtures.current_enrollment_version(context["hse_enrollment_id"])

    fixtures.void_attendance(
        context["first_entry_id"],
        context["hse_enrollment_id"],
        expected_enrollment_version=stale_version,
    )

    refused = _void(context["second_entry_id"], stale_version)
    validate_error(refused, ApiErrorId.STALE_ENROLLMENT_VERSION, expected_status=412)

    assert_hours_value(
        fixtures.read_enrollment(context["hse_enrollment_id"])["posted_hours"], 32.00
    )
    assert_hours_value(
        fixtures.read_student(context["student_id"])["total_instructional_hours"], 42.00
    )
    assert (
        fixtures.read_attendance_entry(context["second_entry_id"])["status"]
        == AttendanceStatus.POSTED
    )

    retried = fixtures.void_attendance(
        context["second_entry_id"], context["hse_enrollment_id"]
    )
    assert retried["status"] == AttendanceStatus.VOIDED
    assert_hours_value(
        fixtures.read_enrollment(context["hse_enrollment_id"])["posted_hours"], 24.00
    )
    assert_hours_value(
        fixtures.read_student(context["student_id"])["total_instructional_hours"], 34.00
    )


def test_09_a_second_void_of_the_same_entry_cannot_subtract_twice():
    """"Once the stale-view guard has passed, the entry itself must still be `POSTED` — a
    second void reports `ERR_ATTENDANCE_ALREADY_VOIDED`" and "Order of posting is
    irrelevant to either sum."

    Design: Difficulty/compensating_invariant/instructional_hours_conserved_across_post_and_void
    """
    context = _setup_two_enrollments_with_posted_hours()

    fixtures.void_attendance(context["first_entry_id"], context["hse_enrollment_id"])
    fixtures.void_attendance(context["second_entry_id"], context["hse_enrollment_id"])

    repeat = _void(
        context["first_entry_id"],
        fixtures.current_enrollment_version(context["hse_enrollment_id"]),
        void_reason="Duplicate correction",
    )
    validate_error(repeat, ApiErrorId.ATTENDANCE_ALREADY_VOIDED, expected_status=409)

    enrollment = fixtures.read_enrollment(context["hse_enrollment_id"])
    assert_hours_value(enrollment["posted_hours"], 24.00)
    assert_hours_value(
        fixtures.read_student(context["student_id"])["total_instructional_hours"], 34.00
    )

    remaining = _posted_entries(context["hse_enrollment_id"])
    assert len(remaining) == 3
    assert sum(float(entry["hours"]) for entry in remaining) == float(
        enrollment["posted_hours"]
    )
