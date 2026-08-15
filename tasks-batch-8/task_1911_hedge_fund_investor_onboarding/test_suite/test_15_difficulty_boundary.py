"""Queue A — boundary_precision_check: X-1, X, X+1 around numeric thresholds.

Instances:
  - notice_days_exactly_at_boundary
  - funding_exactly_at_deadline_vs_after
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_fund_payload,
    create_share_class_payload,
    create_investor_payload,
    create_subscription_payload,
    create_funding_payload,
    create_nav_period_payload,
    create_redemption_payload,
    get_fund,
    list_capital_accounts,
    setup_accepted_subscription,
    validate_error,
    validate_success,
)

FA = TEST_USERS["fund_admin_headers"]
CO = TEST_USERS["compliance_officer_headers"]
TA = TEST_USERS["transfer_agent_headers"]


class TestNoticeDaysBoundary:
    """Two tests for Difficulty/boundary_precision_check/notice_days_exactly_at_boundary."""

    def _build_ctx(self, notice_days=30, period_end="2026-09-30T00:00:00Z"):
        return setup_accepted_subscription(
            fund_overrides={"lockup_months_default": 0, "notice_days_default": notice_days},
            class_overrides={
                "lockup_months": 0,
                "notice_days": notice_days,
                "redemption_frequency": "QUARTERLY",
            },
            commitment_amount_cents=500000,
            funding_deadline_utc="2026-08-05T00:00:00Z",
            funding_received_at_utc="2026-08-04T00:00:00Z",
            period_end_utc=period_end,
        )

    def test_notice_exactly_at_required_days_approved(self, api, fund_admin_headers):
        """PRD §3.7: "The boundary operator is inclusive: an actual notice
        exactly equal to the required notice is valid."

        Design: Difficulty/boundary_precision_check/notice_days_exactly_at_boundary
        """
        ctx = self._build_ctx(notice_days=30, period_end="2026-09-30T00:00:00Z")
        fund = ctx["fund"]
        nav_period = ctx["nav_period"]
        capital_account = ctx["capital_account"]

        # Advance clock so notice is exactly 30 days before period end.
        api.set_current_utc({"to_iso8601": "2026-08-31T00:00:00Z"}, fund_admin_headers)
        red = validate_success(
            api.create_redemption(
                fund["id"],
                create_redemption_payload(
                    capital_account_id=capital_account["id"],
                    requested_amount_cents=100000,
                    requested_effective_period_id=nav_period["id"],
                ),
                TA,
            ),
            201,
        )
        resp = api.approve_redemption(fund["id"], red["id"], fund_admin_headers)
        approved = validate_success(resp, 200)
        assert approved["status"] == "APPROVED"

    def test_notice_one_day_short_rejected(self, api, fund_admin_headers):
        """PRD §3.7: "the notice given must satisfy the notice requirement
        (otherwise ERR_INSUFFICIENT_NOTICE)". One day short of the boundary
        must fail.

        Design: Difficulty/boundary_precision_check/notice_days_exactly_at_boundary
        """
        ctx = self._build_ctx(notice_days=30, period_end="2026-09-30T00:00:00Z")
        fund = ctx["fund"]
        nav_period = ctx["nav_period"]
        capital_account = ctx["capital_account"]

        # 29 days before period end — one day short.
        api.set_current_utc({"to_iso8601": "2026-09-01T00:00:00Z"}, fund_admin_headers)
        red = validate_success(
            api.create_redemption(
                fund["id"],
                create_redemption_payload(
                    capital_account_id=capital_account["id"],
                    requested_amount_cents=100000,
                    requested_effective_period_id=nav_period["id"],
                ),
                TA,
            ),
            201,
        )
        resp = api.approve_redemption(fund["id"], red["id"], fund_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_NOTICE)


class TestFundingDeadlineBoundary:
    """Two tests for Difficulty/boundary_precision_check/funding_exactly_at_deadline_vs_after."""

    def _build_compliance_approved_sub(self, deadline="2026-08-10T00:00:00Z"):
        fund = validate_success(api_client.create_fund(create_fund_payload(), FA), 201)
        cls = validate_success(
            api_client.create_share_class(fund["id"], create_share_class_payload(), FA), 201
        )
        inv = validate_success(api_client.create_investor(create_investor_payload(), FA), 201)
        sub = validate_success(
            api_client.create_subscription(
                fund["id"],
                create_subscription_payload(
                    investor_id=inv["id"], share_class_id=cls["id"],
                    commitment_amount_cents=200000,
                    funding_deadline_utc=deadline,
                ),
                FA,
            ),
            201,
        )
        api_client.submit_subscription(fund["id"], sub["id"], TA)
        api_client.compliance_approve_subscription(fund["id"], sub["id"], CO)
        return {"fund": fund, "sub": sub}

    def test_funding_at_exact_deadline_succeeds(self, api, fund_admin_headers):
        """PRD §3.4: "The receipt must also arrive on or before the
        subscription's funding_deadline_utc as measured by the logical
        clock; a receipt after the deadline is rejected with
        ERR_FUNDING_DEADLINE_PASSED." "On or before" pins the boundary
        operator to <=.

        Design: Difficulty/boundary_precision_check/funding_exactly_at_deadline_vs_after
        """
        ctx = self._build_compliance_approved_sub(deadline="2026-08-10T00:00:00Z")
        # Set clock exactly at deadline.
        api_client.set_current_utc({"to_iso8601": "2026-08-10T00:00:00Z"}, fund_admin_headers)
        resp = api_client.record_funding(
            ctx["fund"]["id"], ctx["sub"]["id"],
            create_funding_payload(amount_cents=200000, received_at_utc="2026-08-10T00:00:00Z"),
            TA,
        )
        funded = validate_success(resp, 201)
        assert funded["status"] == "FUNDED", (
            f"Funding at exactly the deadline must succeed; status={funded['status']}"
        )

    def test_funding_one_second_after_deadline_rejected(self, api, fund_admin_headers):
        """PRD §3.4: "a receipt after the deadline is rejected with
        ERR_FUNDING_DEADLINE_PASSED."

        Design: Difficulty/boundary_precision_check/funding_exactly_at_deadline_vs_after
        """
        ctx = self._build_compliance_approved_sub(deadline="2026-08-10T00:00:00Z")
        api_client.set_current_utc({"to_iso8601": "2026-08-10T00:00:01Z"}, fund_admin_headers)
        resp = api_client.record_funding(
            ctx["fund"]["id"], ctx["sub"]["id"],
            create_funding_payload(amount_cents=200000, received_at_utc="2026-08-10T00:00:01Z"),
            TA,
        )
        validate_error(resp, ApiErrorId.ERR_FUNDING_DEADLINE_PASSED)
