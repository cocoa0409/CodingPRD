"""Difficulty Rule 2 — combinatorial_formula.

Tests for calculations whose formulas combine several inputs non-linearly with a
pinned rounding order: the I-485 under-14 filing fee and the officer workload's
age-weighted summation.
"""
import pytest

from test_helpers import (
    set_clock,
    register_applicant,
    create_draft_case,
    file_case,
    setup_officer_two_case_pool,
    make_applicant_headers,
    TEST_USERS,
    validate_success,
)


class TestFilingFeeUnder14DiscountRoundingOrder:
    """The discount is multiplied against the subtotal (base+surcharge) FIRST,
    then rounded half-up exactly once. For an under-14 I-485 applicant the
    formula yields 112_875 cents.
    """

    def test_i485_under14_filing_fee_pinned_at_112875_cents(self, api):
        """PRD §3.2: "When the case type is I-485 and the applicant's is_under_14 flag is true
        at the file date, a child discount of 25 percent is applied to that subtotal —
        that is, the subtotal is multiplied by 0.75 — and the result is rounded
        half-up to a whole-cent integer; this rounding is applied exactly once,
        to the discounted value, and not separately to the base and surcharge components."

        Design: Difficulty/combinatorial_formula/filing_fee_under14_discount_rounding_order_pinned_mode_b
        """
        # Clock fixed at 2026-06-15 so file_date stamps to 2026-06-15.
        set_clock("2026-06-15T00:00:00Z")
        # Applicant born 2020-06-15: age 6 at file_date → is_under_14 = true.
        applicant = register_applicant(date_of_birth="2020-06-15")
        case = create_draft_case(applicant, case_type="I-485")
        filed = file_case(case, applicant)
        # (142_000 + 8_500) * 0.75 = 112_875.0 → 112_875 cents.
        assert filed["filing_fee_cents"] == 112_875
        assert filed["case_type"] == "I-485"

    def test_under_14_flag_is_recomputed_at_file_date(self, api):
        """PRD §3.2: "It recomputes the applicant's `is_under_14` flag against the new
        `file_date`: `is_under_14` is true exactly when the applicant's age in
        completed years at `file_date`, derived from `date_of_birth`, is strictly
        less than 14."

        Design: Difficulty/combinatorial_formula/filing_fee_under14_discount_rounding_order_pinned_mode_b
        """
        set_clock("2026-06-15T00:00:00Z")
        applicant = register_applicant(date_of_birth="2020-06-15")
        case = create_draft_case(applicant, case_type="I-485")
        filed = file_case(case, applicant)
        # The PRD requires the file flow to recompute Applicant.is_under_14;
        # re-read the applicant and check.
        headers = make_applicant_headers(applicant["id"])
        body = validate_success(api.get_applicant(applicant["id"], headers), 200)
        assert body["is_under_14"] is True
        # And the discount took effect (subtotal = 150_500 cents would imply no
        # discount; pinned formula yields 112_875).
        assert filed["filing_fee_cents"] == 112_875


class TestWorkloadScoreWeightedAgeNonlinear:
    """Three-input formula: status weight × age multiplier (capped 1.0–2.0),
    summed over the pool with a single final round_half_up to 2 decimals.
    """

    def test_workload_score_at_14_days_age_yields_6_23(self, api):
        """PRD §3.8: "The age multiplier is one plus the smaller of two values:
        the case's age in whole days (computed as the difference between the
        calendar-date portion of `ClockState.current_utc` and the case's `file_date`)
        divided by 365, and the cap of 1.0."
        PRD §3.8: "The `workload_score` is the sum of every case's contribution, rounded
        half-up to two decimal places. The rounding is applied exactly once to the
        final sum — never per case — to avoid accumulated rounding drift."

        Design: Difficulty/combinatorial_formula/workload_score_weighted_age_nonlinear_three_input_mode_a
        """
        officer_id, _officer_headers, _case_a, _case_b = setup_officer_two_case_pool(
            initial_clock="2026-06-01T00:00:00Z",
            final_clock="2026-06-15T00:00:00Z",
            biom_at="2026-07-01T15:00:00Z",
        )
        # (BIOMETRICS_SCHEDULED weight=2 + UNDER_REVIEW weight=4) = 6
        # multiplier = 1 + min(14/365, 1.0) = 1 + 0.0383561... = 1.0383561...
        # 6 * 1.0383561... = 6.230136... → round_half_up to 2dp → 6.23
        res = api.get_officer_workload(officer_id,
                                       TEST_USERS["field_office_admin_headers"])
        body = validate_success(res, 200)
        assert body["workload_score"] == pytest.approx(6.23, abs=0.005)
        assert body["case_count"] == 2

    def test_age_multiplier_is_one_for_zero_age_pool(self, api):
        """PRD §3.8: "a freshly filed case carries a multiplier of exactly 1.0"

        Design: Difficulty/combinatorial_formula/workload_score_weighted_age_nonlinear_three_input_mode_a
        """
        # Both files happen at the same wall-clock instant we then read from.
        officer_id, _officer_headers, _case_a, _case_b = setup_officer_two_case_pool(
            initial_clock="2026-06-01T00:00:00Z",
            final_clock="2026-06-01T00:00:00Z",  # age = 0 days
            biom_at="2026-07-01T15:00:00Z",
        )
        # (BIOMETRICS_SCHEDULED 2 + UNDER_REVIEW 4) * 1.0 = 6.00 exactly.
        res = api.get_officer_workload(officer_id,
                                       TEST_USERS["field_office_admin_headers"])
        body = validate_success(res, 200)
        assert body["workload_score"] == pytest.approx(6.00, abs=0.005)
        assert body["case_count"] == 2
