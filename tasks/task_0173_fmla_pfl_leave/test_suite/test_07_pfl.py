"""State PFL claim — creation, weekly benefit calculation, claim_type
alignment with case reason, weeks_authorized boundary.

Covers PRD §3.8 (PFL claim, weekly benefit), §3.3 (linkage), §5
(error codes).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    PFL_WEEKLY_CAP_CENTS,
    advance_clock_to,
    assert_pfl_claim,
    create_pfl_claim,
    create_pfl_claim_payload,
    make_employee_headers,
    setup_eligible_employee,
    submit_leave_case,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# Creation — PRD §3.8
# ===========================================================================
class TestPflCreation:

    def test_pfl_claim_starts_submitted_with_zero_paid(self, api):
        """PRD §3.8: "On creation the claim begins at `claim_status` of
        `SUBMITTED` and carries `weeks_paid` of 0"."""
        _e, _w, employee = setup_eligible_employee(
            state_pfl_program="STATE_PFL_8WEEK",
        )
        claim = create_pfl_claim(
            employee_id=employee["id"],
            claim_type="BABY_BONDING",
            weeks_authorized=8,
        )
        assert_pfl_claim(claim)
        assert claim["claim_status"] == "SUBMITTED"
        assert claim["weeks_paid"] == 0

    def test_pfl_claim_with_none_program_returns_pfl_not_available(self, api):
        """PRD §3.8: "if the employer's `state_pfl_program` is `NONE`,
        claim creation is refused with `ERR_PFL_NOT_AVAILABLE`"."""
        _e, _w, employee = setup_eligible_employee(
            state_pfl_program="NONE",
        )
        h = make_employee_headers(employee["id"])
        resp = api.create_pfl_claim(
            create_pfl_claim_payload(
                employee_id=employee["id"],
                claim_type="BABY_BONDING",
                weeks_authorized=4,
            ),
            h,
        )
        validate_error(resp, "ERR_PFL_NOT_AVAILABLE")

    @pytest.mark.parametrize("weeks_authorized", [0, 9, 100])
    def test_pfl_claim_with_weeks_out_of_range_rejected(
        self, api, weeks_authorized,
    ):
        """PRD §3.8: "any submission with `weeks_authorized` outside
        the 1-to-8 range" is refused with `ERR_PFL_NOT_AVAILABLE`."""
        _e, _w, employee = setup_eligible_employee(
            state_pfl_program="STATE_PFL_8WEEK",
        )
        h = make_employee_headers(employee["id"])
        resp = api.create_pfl_claim(
            create_pfl_claim_payload(
                employee_id=employee["id"],
                claim_type="BABY_BONDING",
                weeks_authorized=weeks_authorized,
            ),
            h,
        )
        validate_error(resp, "ERR_PFL_NOT_AVAILABLE")

    @pytest.mark.parametrize("weeks_authorized", [1, 8])
    def test_pfl_claim_with_weeks_at_boundary_succeeds(
        self, api, weeks_authorized,
    ):
        """PRD §3.8: "`weeks_authorized` (an integer between 1 and 8
        inclusive)"."""
        _e, _w, employee = setup_eligible_employee(
            state_pfl_program="STATE_PFL_8WEEK",
        )
        h = make_employee_headers(employee["id"])
        resp = api.create_pfl_claim(
            create_pfl_claim_payload(
                employee_id=employee["id"],
                claim_type="BABY_BONDING",
                weeks_authorized=weeks_authorized,
            ),
            h,
        )
        validate_success(resp, expected_status=201)


# ===========================================================================
# Weekly benefit — PRD §3.8 (per-step rounding)
# ===========================================================================
class TestWeeklyBenefit:

    def test_under_cap_branch_pins_per_step_rounded_value(self, api):
        """PRD §3.8: "Step one converts the employee's
        `monthly_wage_cents` into a weekly wage in cents by multiplying
        by twelve, dividing by fifty-two, and rounding half-up to whole
        cents. Step two applies the wage-replacement ratio of sixty
        percent by multiplying the result of step one by 0.60 and
        rounding half-up to whole cents".

        For monthly_wage_cents=500_000:
            Step 1: round_half_up(500_000 * 12 / 52) = round_half_up(115_384.6153...) = 115_385
            Step 2: round_half_up(115_385 * 0.60)    = round_half_up(69_231.0) = 69_231
            Step 3: min(69_231, 162_900) = 69_231 (under-cap branch)
        """
        _e, _w, employee = setup_eligible_employee(
            state_pfl_program="STATE_PFL_8WEEK",
            monthly_wage_cents=500_000,
        )
        claim = create_pfl_claim(
            employee_id=employee["id"],
            claim_type="BABY_BONDING",
            weeks_authorized=8,
        )
        assert claim["weekly_benefit_cents"] == 69_231, (
            f"PRD §3.8 per-step rounding: 500_000*12/52 -> 115_385, "
            f"*0.60 -> 69_231; got {claim['weekly_benefit_cents']!r}"
        )

    def test_at_cap_branch_pins_cap(self, api):
        """PRD §3.8: "if the raw weekly benefit exceeds the cap the
        at-cap variant applies and the final value equals the cap"
        (PFL_WEEKLY_CAP_CENTS = 162_900).

        For monthly_wage_cents=2_000_000:
            Step 1: round_half_up(2_000_000 * 12 / 52) = round_half_up(461_538.4615...) = 461_538
            Step 2: round_half_up(461_538 * 0.60)      = round_half_up(276_922.8) = 276_923
            Step 3: min(276_923, 162_900) = 162_900 (at-cap branch)
        """
        _e, _w, employee = setup_eligible_employee(
            state_pfl_program="STATE_PFL_8WEEK",
            monthly_wage_cents=2_000_000,
        )
        claim = create_pfl_claim(
            employee_id=employee["id"],
            claim_type="BABY_BONDING",
            weeks_authorized=8,
        )
        assert claim["weekly_benefit_cents"] == PFL_WEEKLY_CAP_CENTS, (
            f"PRD §3.8 at-cap: weekly_benefit_cents = cap "
            f"{PFL_WEEKLY_CAP_CENTS}; got {claim['weekly_benefit_cents']!r}"
        )


# ===========================================================================
# PFL linkage at submission — PRD §3.3
# ===========================================================================
class TestPflLinkage:

    def test_link_pfl_with_employer_program_none_returns_pfl_not_available(
        self, api,
    ):
        """PRD §3.3: "the employer's `state_pfl_program` must equal
        `STATE_PFL_8WEEK`; otherwise the submission is refused with
        `ERR_PFL_NOT_AVAILABLE`"."""
        # Create an employer with state_pfl_program=STATE_PFL_8WEEK to
        # mint a valid PfLClaim, then create a SEPARATE employer with
        # NONE and a fresh employee; attempting to link the foreign
        # claim should fail with ERR_PFL_NOT_AVAILABLE.
        _e1, _w1, employee_pfl = setup_eligible_employee(
            state_pfl_program="STATE_PFL_8WEEK",
        )
        claim = create_pfl_claim(
            employee_id=employee_pfl["id"],
            claim_type="BABY_BONDING",
            weeks_authorized=8,
        )
        _e2, _w2, employee_none = setup_eligible_employee(
            state_pfl_program="NONE",
            initial_clock_iso=None,  # do not re-anchor clock
        )
        h = make_employee_headers(employee_none["id"])
        from test_helpers import create_leave_case_payload
        resp = api.create_leave_case(
            employee_none["id"],
            create_leave_case_payload(
                reason="BABY_BONDING",
                leave_pattern="CONTINUOUS",
                requested_start_date="2026-06-01",
                expected_end_date="2026-06-30",
                pfl_claim_id=claim["id"],
            ),
            h,
        )
        validate_error(resp, "ERR_PFL_NOT_AVAILABLE")

    def test_link_pfl_mismatching_claim_type_returns_pfl_mismatch(self, api):
        """PRD §3.3: "its `claim_type` must align with the case `reason`
        — a `claim_type` of `FAMILY_CARE` aligns with a case `reason`
        of `FAMILY_SERIOUS_HEALTH`, and a `claim_type` of `BABY_BONDING`
        aligns with a case `reason` of `BABY_BONDING`. Any mismatch —
        wrong employee or non-aligning category pair — surfaces as
        `ERR_PFL_MISMATCH`"."""
        _e, _w, employee = setup_eligible_employee(
            state_pfl_program="STATE_PFL_8WEEK",
        )
        claim = create_pfl_claim(
            employee_id=employee["id"],
            claim_type="BABY_BONDING",
            weeks_authorized=8,
        )
        h = make_employee_headers(employee["id"])
        from test_helpers import create_leave_case_payload
        resp = api.create_leave_case(
            employee["id"],
            create_leave_case_payload(
                reason="FAMILY_SERIOUS_HEALTH",  # mismatch with BABY_BONDING claim
                leave_pattern="CONTINUOUS",
                requested_start_date="2026-06-01",
                expected_end_date="2026-06-30",
                pfl_claim_id=claim["id"],
            ),
            h,
        )
        validate_error(resp, "ERR_PFL_MISMATCH")

    def test_link_pfl_wrong_employee_returns_pfl_mismatch(self, api):
        """PRD §3.3: "Any mismatch — wrong employee or non-aligning
        category pair — surfaces as `ERR_PFL_MISMATCH`"."""
        # Two employees on same STATE_PFL_8WEEK employer.
        from test_helpers import create_employee
        employer, worksite, employee_a = setup_eligible_employee(
            state_pfl_program="STATE_PFL_8WEEK",
        )
        employee_b = create_employee(
            employer_id=employer["id"], worksite_id=worksite["id"],
            hire_date="2023-01-01", hours_worked_trailing_12mo=2080,
        )
        claim_for_a = create_pfl_claim(
            employee_id=employee_a["id"],
            claim_type="BABY_BONDING",
            weeks_authorized=8,
        )
        # Employee B tries to submit a case linking to A's claim.
        h = make_employee_headers(employee_b["id"])
        from test_helpers import create_leave_case_payload
        resp = api.create_leave_case(
            employee_b["id"],
            create_leave_case_payload(
                reason="BABY_BONDING",
                leave_pattern="CONTINUOUS",
                requested_start_date="2026-06-01",
                expected_end_date="2026-06-30",
                pfl_claim_id=claim_for_a["id"],
            ),
            h,
        )
        validate_error(resp, "ERR_PFL_MISMATCH")
