"""Weekly certification submission and approval cascade — PRD §3.3.

Covers Saturday rule, week-range rule, duplicate-week guard,
work-search threshold, and the SUBMITTED -> APPROVED/DENIED branch
along with the payable_amount_cents calculation.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    MIN_WORK_SEARCH_CONTACTS,
    TEST_USERS,
    approve_one_weekly_certification,
    assert_benefit_payment,
    assert_weekly_certification,
    create_eligible_claim,
    create_weekly_certification_payload,
    date_to_iso,
    make_claimant_headers,
    n_work_search_entries,
    next_certifiable_saturday,
    previous_saturday_on_or_before,
    submit_weekly_certification,
    validate_error,
    validate_success,
)


class TestSaturdayRule:

    def test_non_saturday_week_ending_rejected(self, api):
        """PRD §3.3: "Submitting a certification whose week_ending_date
        is not a Saturday is rejected with ERR_NOT_SATURDAY."
        """
        bundle = create_eligible_claim()
        claim, claimant = bundle["claim"], bundle["claimant"]
        saturday = next_certifiable_saturday(claim)
        # Use the day before (Friday) — not a Saturday.
        friday = saturday - timedelta(days=1)
        payload = create_weekly_certification_payload(
            week_ending_date=date_to_iso(friday),
        )
        resp = api.create_weekly_certification(
            claim["id"], payload,
            make_claimant_headers(claimant["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_SATURDAY.value)


class TestWorkSearchCount:

    def test_two_entries_below_threshold_auto_denied(self, api):
        """PRD §3.3: "A certification with fewer than three work-search
        entries is also rejected at submit-time with
        ERR_INSUFFICIENT_WORK_SEARCH."

        Difficulty: boundary_precision_check/work_search_zero_count_boundary
        — count == 2 (just below 3).
        # difficulty: boundary_precision_check/work_search_zero_count_boundary
        """
        bundle = create_eligible_claim()
        claim, claimant = bundle["claim"], bundle["claimant"]
        sat = next_certifiable_saturday(claim)
        payload = create_weekly_certification_payload(
            week_ending_date=date_to_iso(sat),
            work_search_entries=n_work_search_entries(2),
        )
        resp = api.create_weekly_certification(
            claim["id"], payload,
            make_claimant_headers(claimant["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_INSUFFICIENT_WORK_SEARCH.value,
        )

    def test_three_entries_at_threshold_approved(self, api):
        """PRD §3.3: "work_search_count is at least 3 (the minimum
        required work-search contacts)."

        Boundary: count == 3 (the inclusive minimum).
        # difficulty: boundary_precision_check/work_search_zero_count_boundary
        """
        bundle = create_eligible_claim()
        cert = approve_one_weekly_certification(bundle)
        assert cert["status"] == "APPROVED"
        assert cert["work_search_count"] == 3


class TestApprovalAndPayment:

    def test_approved_certification_creates_payment(self, api):
        """PRD §3.3: "the system creates a BenefitPayment whose
        amount_cents equals payable_amount_cents, whose claim_id and
        certification_id link back to the parent records, whose
        issued_at is SystemClock.now, and whose status starts at
        ISSUED with reversed_reason null."
        """
        bundle = create_eligible_claim()
        cert = approve_one_weekly_certification(bundle)
        assert cert["status"] == "APPROVED"
        assert cert["payment_id"], "payment_id must be set on APPROVED"
        # Read the certification back to inspect linked payment fields.
        resp = api.get_weekly_certification(
            cert["id"], TEST_USERS["system_admin_headers"],
        )
        data = validate_success(resp)
        # payment_id is on the cert; payable_amount_cents should equal
        # the WBA (earnings=0).
        assert data["payable_amount_cents"] == bundle["claim"][
            "weekly_benefit_amount_cents"
        ]

    def test_first_approval_transitions_claim_to_active(self, api):
        """PRD §3.3: "If the claim was MONETARILY_ELIGIBLE it now
        transitions to ACTIVE (this is the entry point into the
        active-payment phase)."
        """
        from test_helpers import get_claim
        bundle = create_eligible_claim()
        approve_one_weekly_certification(bundle)
        claim = get_claim(bundle["claim"]["id"])
        assert claim["status"] == "ACTIVE"
        assert claim["weeks_paid"] == 1

    def test_payable_amount_with_zero_earnings_equals_wba(self, api):
        """PRD §3.3: "First, an earnings disregard is computed: take
        25% of weekly_benefit_amount_cents and floor the result
        (truncate toward zero) to integer cents. Second, the earnings
        offset is the greater of zero and (earnings_reported_cents
        minus the disregard) ... Third, the payable amount is the
        greater of zero and (weekly_benefit_amount_cents minus the
        offset)."

        With earnings=0, offset=0, payable == WBA.
        """
        bundle = create_eligible_claim()
        cert = approve_one_weekly_certification(bundle)
        assert cert["payable_amount_cents"] == (
            bundle["claim"]["weekly_benefit_amount_cents"]
        )

    def test_payable_amount_with_earnings_below_disregard(self, api):
        """PRD §3.3: "any earnings up to the disregard do not reduce the
        benefit, while every cent above the disregard reduces the
        benefit dollar-for-dollar."

        WBA=30_000 (high_quarter=780_000 -> floor 30_000); disregard =
        floor(30_000 * 25 / 100) = 7_500. Earnings = 5_000 (below
        disregard) -> offset = 0 -> payable = 30_000.
        """
        bundle = create_eligible_claim(
            high_quarter_cents=780_000,
            other_quarter_cents=200_000,
        )
        claim, claimant = bundle["claim"], bundle["claimant"]
        # Verify WBA is 30_000 as designed
        assert claim["weekly_benefit_amount_cents"] == 30_000
        cert = submit_weekly_certification(
            claim_id=claim["id"], claimant_id=claimant["id"],
            week_ending_date=next_certifiable_saturday(claim),
            earnings_reported_cents=5_000,
        )
        assert cert["status"] == "APPROVED"
        assert cert["payable_amount_cents"] == 30_000

    def test_payable_amount_with_earnings_above_disregard(self, api):
        """PRD §3.3: "every cent above the disregard reduces the
        benefit dollar-for-dollar."

        WBA=30_000, disregard=7_500. Earnings = 10_000 -> offset =
        max(0, 10_000-7_500)=2_500 -> payable = 30_000-2_500=27_500.

        # difficulty: combinatorial_formula/weekly_payable_amount_mode_a_nested_min_max
        """
        bundle = create_eligible_claim(
            high_quarter_cents=780_000,
            other_quarter_cents=200_000,
        )
        claim, claimant = bundle["claim"], bundle["claimant"]
        cert = submit_weekly_certification(
            claim_id=claim["id"], claimant_id=claimant["id"],
            week_ending_date=next_certifiable_saturday(claim),
            earnings_reported_cents=10_000,
        )
        assert cert["status"] == "APPROVED"
        assert cert["payable_amount_cents"] == 27_500

    def test_payable_amount_zero_when_earnings_swamp_wba(self, api):
        """PRD §3.3: "Third, the payable amount is the greater of zero
        and (weekly_benefit_amount_cents minus the offset)."

        With huge earnings, payable clamps to 0 -> auto-DENIED (since
        payable_amount_cents must be strictly greater than zero).
        """
        bundle = create_eligible_claim(
            high_quarter_cents=780_000,
            other_quarter_cents=200_000,
        )
        claim, claimant = bundle["claim"], bundle["claimant"]
        cert = submit_weekly_certification(
            claim_id=claim["id"], claimant_id=claimant["id"],
            week_ending_date=next_certifiable_saturday(claim),
            earnings_reported_cents=10_000_000,
        )
        # payable would be 0 -> denied per the SUBMITTED -> DENIED
        # transition precondition ("payable_amount_cents == 0").
        assert cert["status"] == "DENIED"
        assert cert["payable_amount_cents"] == 0


class TestApprovalDenials:

    def test_able_and_available_false_denied(self, api):
        """PRD §3.3: "When able_and_available is false, or
        work_search_count is below 3, or payable_amount_cents is zero,
        the certification instead transitions SUBMITTED → DENIED and
        no payment is issued."
        """
        bundle = create_eligible_claim()
        claim, claimant = bundle["claim"], bundle["claimant"]
        cert = submit_weekly_certification(
            claim_id=claim["id"], claimant_id=claimant["id"],
            week_ending_date=next_certifiable_saturday(claim),
            able_and_available=False,
        )
        assert cert["status"] == "DENIED"
        assert cert.get("payment_id") in (None, "")


class TestDuplicateAndOrdering:

    def test_duplicate_week_rejected(self, api):
        """PRD §3.3: "Submitting one whose (claim_id, week_ending_date)
        collides with any existing certification is rejected with
        ERR_DUPLICATE_WEEK."

        To uniquely exercise the duplicate-week rule (priority 11 per
        §2.10) without also tripping the "strictly later than latest
        APPROVED" check (priority 10, which would surface as
        ERR_WEEK_OUT_OF_RANGE), the prior cert at the same week must
        NOT be APPROVED. We submit a DENIED cert first (via
        able_and_available=False with the required >= 3 work-search
        entries — PRD §3.3: "When able_and_available is false ... the
        certification instead transitions SUBMITTED -> DENIED").

        # difficulty: resource_temporal_overlap/weekly_certification_week_uniqueness_strict_after
        """
        bundle = create_eligible_claim()
        claim, claimant = bundle["claim"], bundle["claimant"]
        sat = next_certifiable_saturday(claim)
        # Produce a DENIED cert at `sat`. With >= 3 work-search entries
        # the §2.10 ERR_INSUFFICIENT_WORK_SEARCH guard is bypassed; with
        # able_and_available=False the cert transitions to DENIED per
        # §3.3.
        cert1 = submit_weekly_certification(
            claim_id=claim["id"], claimant_id=claimant["id"],
            week_ending_date=sat,
            able_and_available=False,
        )
        assert cert1["status"] == "DENIED"
        # Re-submit same Saturday. Because the prior cert is DENIED
        # (not APPROVED), the "strictly later than latest APPROVED"
        # rule does not fire — only the uniqueness rule does, yielding
        # ERR_DUPLICATE_WEEK.
        payload = create_weekly_certification_payload(
            week_ending_date=date_to_iso(sat),
        )
        resp = api.create_weekly_certification(
            claim["id"], payload,
            make_claimant_headers(claimant["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_WEEK.value)

    def test_earlier_week_rejected_as_out_of_range(self, api):
        """PRD §3.3: "Submitting one whose week_ending_date is not
        strictly later than the latest APPROVED week or falls outside
        [benefit_year_start, benefit_year_end] is rejected with
        ERR_WEEK_OUT_OF_RANGE."

        # difficulty: resource_temporal_overlap/weekly_certification_week_uniqueness_strict_after
        """
        bundle = create_eligible_claim()
        claim, claimant = bundle["claim"], bundle["claimant"]
        sat = next_certifiable_saturday(claim)
        # Approve at sat.
        submit_weekly_certification(
            claim_id=claim["id"], claimant_id=claimant["id"],
            week_ending_date=sat,
        )
        # Attempt earlier week.
        earlier = sat - timedelta(days=7)
        payload = create_weekly_certification_payload(
            week_ending_date=date_to_iso(earlier),
        )
        resp = api.create_weekly_certification(
            claim["id"], payload,
            make_claimant_headers(claimant["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WEEK_OUT_OF_RANGE.value)
