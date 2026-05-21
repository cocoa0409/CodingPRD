"""Contribution posting: amount calculation, accrual cap, state
preconditions.

References PRD §3.4, §2.7.
"""
from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    add_days,
    advance_clock_to,
    assert_contribution,
    create_contribution_payload,
    enroll_participant,
    make_participant_headers,
    new_participant_id,
    post_contribution,
    purchase_fmv_payload,
    run_sweep,
    setup_active_plan_with_open_period,
    setup_enrollment_with_contributions,
    setup_period_at_closed_state,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# Contribution amount calculation — PRD §3.4 step 1
# ===========================================================================
class TestContributionAmountRoundHalfUp:
    """PRD §3.4 first step + §2.7 rounding rule."""

    def test_simple_15_percent_rate(self, api):
        """PRD §3.4: "gross pay in cents is multiplied by the
        enrollment's `contribution_rate_bp` and divided by ten
        thousand, with the result rounded half-up to the nearest whole
        cent."

        Claim: gross=100_000 cents, rate_bp=1500 -> amount_cents=15_000
        (100000 * 1500 / 10000 = 15000, exact).
        """
        plan, op1 = setup_active_plan_with_open_period(
            initial_clock_iso="2023-12-01T00:00:00.000Z",
            effective_date="2024-01-01T00:00:00.000Z",
            grant_date_fmv_cents=1000,
        )
        pid, enr = enroll_participant(
            offering_period_id=op1["id"], contribution_rate_bp=1500,
        )
        resp = api.create_contribution(
            enr["id"],
            create_contribution_payload(
                pay_period_end=op1["start_date"],
                gross_pay_cents=100_000,
            ),
            TEST_USERS["payroll_agent_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert_contribution(data)
        assert data["amount_cents"] == 15_000, (
            f"Expected amount_cents=15000, got {data['amount_cents']}"
        )
        assert data["status"] == "POSTED"

    def test_round_half_up_on_fractional_cent(self, api):
        """PRD §3.4: "with the result rounded half-up to the nearest
        whole cent."
        PRD §2.7: "the resulting cents value is rounded half-up to the
        nearest whole cent."

        Claim: gross=333 cents, rate_bp=1500 -> raw = 333*1500/10000 =
        49.95 cents -> round_half_up = 50 cents.
        """
        plan, op1 = setup_active_plan_with_open_period(
            initial_clock_iso="2023-12-01T00:00:00.000Z",
            effective_date="2024-01-01T00:00:00.000Z",
            grant_date_fmv_cents=1000,
        )
        pid, enr = enroll_participant(
            offering_period_id=op1["id"], contribution_rate_bp=1500,
        )
        resp = api.create_contribution(
            enr["id"],
            create_contribution_payload(
                pay_period_end=op1["start_date"],
                gross_pay_cents=333,
            ),
            TEST_USERS["payroll_agent_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["amount_cents"] == 50, (
            f"Expected round_half_up(49.95)=50, got {data['amount_cents']}"
        )


# ===========================================================================
# State preconditions on contribution post — PRD §3.4
# ===========================================================================
class TestContributionStatePreconditions:

    def test_post_on_closed_period_rejected(self, api):
        """PRD §3.4: "A contribution may be posted only when the owning
        enrollment is in `ACTIVE` status and the parent offering period
        is `OPEN`; otherwise the post is rejected with
        `ERR_PERIOD_NOT_OPEN` (if the period is not `OPEN`)".

        Claim: contribution on enrollment under CLOSED period ->
        ERR_PERIOD_NOT_OPEN.
        """
        plan, op_closed, _pid, enrollment = setup_period_at_closed_state()
        resp = api.create_contribution(
            enrollment["id"],
            create_contribution_payload(
                pay_period_end="2024-07-15T00:00:00.000Z",
                gross_pay_cents=100_000,
            ),
            TEST_USERS["payroll_agent_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_OPEN.value)

    def test_post_on_withdrawn_enrollment_rejected(self, api):
        """PRD §3.4: "or `ERR_INVALID_ENROLLMENT_STATE` (if the
        enrollment is not `ACTIVE`)."

        Claim: contribution on WITHDRAWN enrollment ->
        ERR_INVALID_ENROLLMENT_STATE.
        """
        plan, op1 = setup_active_plan_with_open_period(
            initial_clock_iso="2023-12-01T00:00:00.000Z",
            effective_date="2024-01-01T00:00:00.000Z",
            grant_date_fmv_cents=1000,
        )
        pid, enr = enroll_participant(
            offering_period_id=op1["id"], contribution_rate_bp=500,
        )
        w = api.withdraw_enrollment(
            enr["id"], make_participant_headers(pid),
        )
        validate_success(w)
        resp = api.create_contribution(
            enr["id"],
            create_contribution_payload(
                pay_period_end=op1["start_date"],
                gross_pay_cents=10_000,
            ),
            TEST_USERS["payroll_agent_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_ENROLLMENT_STATE.value)
