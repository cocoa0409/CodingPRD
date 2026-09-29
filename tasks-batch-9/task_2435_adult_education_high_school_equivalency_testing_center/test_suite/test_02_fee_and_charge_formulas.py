"""The three pinned money formulas: the nine-step exam fee, per-line allocation
rounding, and the five-step transcript charge whose circularity is cut by order.
"""

from __future__ import annotations

from test_helpers import fixtures
from test_helpers.assertions import (
    assert_exam_registration,
    assert_funding_pool_conserved,
    assert_transcript_order,
    assert_voucher_ledger_conserved,
)
from test_helpers.types import (
    AllocationStatus,
    AllocationVariant,
    CredentialIssuanceStatus,
    MeasureType,
    SectionStatus,
    Subtest,
    TestFormat,
    TranscriptDelivery,
    TranscriptDestination,
    TranscriptOrderStatus,
)

FIRST_SITTING_STARTS = "2026-08-04T09:00:00Z"
FIRST_SITTING_ENDS = "2026-08-04T11:00:00Z"
SECOND_SITTING_STARTS = "2026-08-06T13:00:00Z"
SECOND_SITTING_ENDS = "2026-08-06T15:00:00Z"


def _setup_retake_with_braille_and_hours():
    """A learner facing an RLA retake with a Braille grant, 24.00 hours and 2000 in vouchers."""
    venue = fixtures.setup_center_with_room_and_proctor(
        seat_capacity=10,
        turnaround_buffer_minutes=45,
        daily_hour_cap=8.00,
        certification_expires_at="2027-01-01T00:00:00Z",
    )
    placed = fixtures.create_placed_student(self_pay_authorized=True)
    student_id = placed["student_id"]

    first_session = fixtures.create_session(
        venue["center_id"],
        venue["room_id"],
        FIRST_SITTING_STARTS,
        FIRST_SITTING_ENDS,
        subtest=Subtest.RLA,
        requested_seats=5,
        supported_formats=[TestFormat.STANDARD],
    )
    first_session = fixtures.assign_session_proctor(
        venue["center_id"], first_session["id"], venue["proctor_id"]
    )
    first_registration = fixtures.register_candidate(student_id, first_session["id"])
    fixtures.seat_and_score_candidate(
        first_registration["id"], venue["proctor_id"], FIRST_SITTING_STARTS, scale_score=150
    )

    section = fixtures.create_section(status=SectionStatus.OPEN)
    enrollment = fixtures.enroll(student_id, section["id"])
    fixtures.post_instructional_hours(enrollment["id"], 24.00, first_date="2026-08-02")

    accommodation = fixtures.setup_approved_accommodation(
        venue["center_id"],
        student_id,
        requested_format=TestFormat.BRAILLE,
        valid_until="2026-12-31T00:00:00Z",
    )
    fixtures.grant_voucher(student_id, 2000)

    second_session = fixtures.create_session(
        venue["center_id"],
        venue["room_id"],
        SECOND_SITTING_STARTS,
        SECOND_SITTING_ENDS,
        subtest=Subtest.RLA,
        requested_seats=5,
        supported_formats=[TestFormat.STANDARD, TestFormat.BRAILLE],
    )
    second_session = fixtures.assign_session_proctor(
        venue["center_id"], second_session["id"], venue["proctor_id"]
    )
    return {
        "student_id": student_id,
        "accommodation_id": accommodation["id"],
        "first_registration_id": first_registration["id"],
        "second_session_id": second_session["id"],
    }


def _setup_two_certified_employment_lines(rate_cents_per_weight=33333, total_cents=1000000):
    period = fixtures.create_funding_period(
        rate_cents_per_weight=rate_cents_per_weight, total_cents=total_cents
    )
    first = fixtures.certified_outcome(
        fixtures.create_placed_student()["student_id"],
        period["id"],
        measure_type=MeasureType.EMPLOYMENT_Q2,
        evidence_ref="WAGE-1",
    )
    second = fixtures.certified_outcome(
        fixtures.create_placed_student()["student_id"],
        period["id"],
        measure_type=MeasureType.EMPLOYMENT_Q2,
        evidence_ref="WAGE-2",
    )
    return {
        "period_id": period["id"],
        "first_outcome_id": first["id"],
        "second_outcome_id": second["id"],
    }


def test_01_retake_multiplier_precedes_the_alternate_format_surcharge():
    """"`gross_fee_cents` is the base fee multiplied by that multiplier, rounded half up
    to whole cents." and "The billable amount is `gross_fee_cents` plus
    `accommodation_surcharge_cents`."

    Design: Difficulty/combinatorial_formula/exam_fee_tiered_retake_surcharge_voucher_chain
    """
    context = _setup_retake_with_braille_and_hours()

    registration = fixtures.register_candidate(
        context["student_id"],
        context["second_session_id"],
        accommodation_request_id=context["accommodation_id"],
    )
    assert_exam_registration(registration)

    assert registration["prior_scored_attempts"] == 1
    # 3400 cents for reading-language-arts multiplied by 1.25 for one prior sitting.
    assert registration["gross_fee_cents"] == 4250
    assert registration["accommodation_surcharge_cents"] == 1200


def test_02_hour_tier_discount_floors_the_billable_sum_not_the_gross_fee():
    """"`discount_cents` is the billable amount multiplied by that percentage and divided
    by one hundred, then **floored** to whole cents; it is never rounded up, so the
    discount never exceeds the exact percentage."

    Design: Difficulty/combinatorial_formula/exam_fee_tiered_retake_surcharge_voucher_chain
    """
    context = _setup_retake_with_braille_and_hours()

    registration = fixtures.register_candidate(
        context["student_id"],
        context["second_session_id"],
        accommodation_request_id=context["accommodation_id"],
    )

    # 25 percent of the 5450-cent billable amount is 1362.5, floored to 1362 —
    # a quarter of the 4250-cent gross alone would have been 1062.
    assert registration["discount_cents"] == 1362


def test_03_voucher_draws_down_only_the_discounted_residue():
    """"`voucher_applied_cents` is the smaller of that net amount and the learner's
    `voucher_balance_cents` — vouchers are applied as far as they go and no further."
    and "`fee_due_cents` is the net amount less `voucher_applied_cents`, and is the
    out-of-pocket remainder."

    Design: Difficulty/combinatorial_formula/exam_fee_tiered_retake_surcharge_voucher_chain
    """
    context = _setup_retake_with_braille_and_hours()

    registration = fixtures.register_candidate(
        context["student_id"],
        context["second_session_id"],
        accommodation_request_id=context["accommodation_id"],
    )

    assert registration["voucher_applied_cents"] == 2000
    assert registration["fee_due_cents"] == 2088


def test_04_ledger_and_the_earlier_sitting_reflect_the_pinned_chain():
    """"The assessment then writes the learner's ledger in the same request:
    `voucher_balance_cents` falls by `voucher_applied_cents`, `voucher_spent_cents`
    rises by the same amount, and `exam_fee_owed_cents` rises by `fee_due_cents`"

    Design: Difficulty/combinatorial_formula/exam_fee_tiered_retake_surcharge_voucher_chain
    """
    context = _setup_retake_with_braille_and_hours()

    fixtures.register_candidate(
        context["student_id"],
        context["second_session_id"],
        accommodation_request_id=context["accommodation_id"],
    )

    student = fixtures.read_student(context["student_id"])
    assert_voucher_ledger_conserved(student)
    assert student["voucher_balance_cents"] == 0
    assert student["voucher_spent_cents"] == 2000
    assert student["exam_fee_owed_cents"] == 5488

    # The first sitting was charged before any hours, grant or accommodation existed.
    first = fixtures.read_registration(context["first_registration_id"])
    assert first["gross_fee_cents"] == 3400
    assert first["discount_cents"] == 0
    assert first["voucher_applied_cents"] == 0
    assert first["fee_due_cents"] == 3400


def test_05_allocation_preview_projects_the_per_line_rounded_sum():
    """"Where a funding total is assembled from several lines, the order is pinned: each
    line is rounded first and the rounded lines are then summed exactly. Summing
    unrounded weights and rounding once at the end produces a different figure and is
    not acceptable."

    Design: Difficulty/combinatorial_formula/allocation_round_per_line_then_sum_pinned
    """
    context = _setup_two_certified_employment_lines()

    preview = fixtures.read_allocation_preview(
        context["period_id"], variant=AllocationVariant.FINAL
    )
    assert float(preview["total_weight"]) == 2.50
    assert preview["line_count"] == 2
    # 33333 * 1.25 = 41666.25 per line, each rounded to 41666, summing to 83332.
    assert preview["projected_committed_cents"] == 83332
    assert preview["projected_committed_cents"] != 83333


def test_06_allocation_run_commits_the_per_line_rounded_sum():
    """"When the walk finishes, the period's `committed_cents` rises by the exact integer
    sum of the committed line amounts, each already rounded, and `available_cents` is
    recomputed as `total_cents` less `committed_cents`. Summing the weights first and
    rounding once at the end is a defect, as §2.8 states."

    Design: Difficulty/combinatorial_formula/allocation_round_per_line_then_sum_pinned
    """
    context = _setup_two_certified_employment_lines()

    period = fixtures.run_allocation(context["period_id"], variant=AllocationVariant.FINAL)
    assert_funding_pool_conserved(period)
    assert period["committed_cents"] == 83332
    assert period["committed_cents"] != 83333
    assert period["available_cents"] == 916668

    for outcome_id in (context["first_outcome_id"], context["second_outcome_id"]):
        line = fixtures.read_outcome(outcome_id)
        assert line["allocated_cents"] == 41666
        assert line["allocation_status"] == AllocationStatus.COMMITTED


def test_07_two_copy_standard_order_waives_before_the_records_fee():
    """"`state_records_fee_cents` is keyed on that net figure: 0 when the net is exactly
    zero, 200 cents when the net is above zero but below 3000, and 500 cents when the
    net is 3000 cents or more. This fee never re-enters the waiver decision in step 2"

    Design: Difficulty/combinatorial_formula/transcript_charge_waiver_then_state_fee_order
    """
    context = fixtures.setup_issued_credential(exam_date="2026-08-10")
    assert context["credential"]["composite_score"] == 600
    assert context["credential"]["status"] == CredentialIssuanceStatus.ISSUED

    order = fixtures.create_transcript_order(
        context["student_id"],
        context["credential_id"],
        copies=2,
        delivery=TranscriptDelivery.STANDARD,
        destination_type=TranscriptDestination.SELF,
    )
    assert_transcript_order(order)

    assert order["base_charge_cents"] == 3000
    assert order["waiver_cents"] == 300
    assert order["state_records_fee_cents"] == 200
    # Feeding the 200-cent fee back into the tier decision would have produced 3150.
    assert order["total_charge_cents"] == 2900
    assert order["status"] == TranscriptOrderStatus.QUEUED


def test_08_rush_order_takes_the_upper_waiver_tier_and_the_higher_records_fee():
    """"`base_charge_cents` is 1500 cents per copy, plus a flat 2500 cents when `delivery`
    is `RUSH` and nothing extra when it is `STANDARD`." and "A waiver percentage is
    chosen from `base_charge_cents` alone: nothing below 3000 cents, 10 percent from
    3000 cents up to but not including 6000, and 20 percent at 6000 cents or above."

    Design: Difficulty/combinatorial_formula/transcript_charge_waiver_then_state_fee_order
    """
    context = fixtures.setup_issued_credential(exam_date="2026-08-10")

    order = fixtures.create_transcript_order(
        context["student_id"],
        context["credential_id"],
        copies=4,
        delivery=TranscriptDelivery.RUSH,
        destination_type=TranscriptDestination.POSTSECONDARY,
    )
    assert_transcript_order(order)

    assert order["base_charge_cents"] == 8500
    assert order["waiver_cents"] == 1700
    assert order["state_records_fee_cents"] == 500
    assert order["total_charge_cents"] == 7300
    assert order["status"] == TranscriptOrderStatus.QUEUED


def test_09_single_copy_order_earns_no_waiver_yet_still_pays_the_records_fee():
    """"The `destination_type` has no effect on the charge; it exists to route the sealed
    copies and to distinguish a state-records filing from a copy sent to an employer."

    Design: Difficulty/combinatorial_formula/transcript_charge_waiver_then_state_fee_order
    """
    context = fixtures.setup_issued_credential(exam_date="2026-08-10")

    order = fixtures.create_transcript_order(
        context["student_id"],
        context["credential_id"],
        copies=1,
        delivery=TranscriptDelivery.STANDARD,
        destination_type=TranscriptDestination.EMPLOYER,
    )
    assert_transcript_order(order)

    assert order["base_charge_cents"] == 1500
    assert order["waiver_cents"] == 0
    assert order["state_records_fee_cents"] == 200
    assert order["total_charge_cents"] == 1700
    assert order["status"] == TranscriptOrderStatus.QUEUED
