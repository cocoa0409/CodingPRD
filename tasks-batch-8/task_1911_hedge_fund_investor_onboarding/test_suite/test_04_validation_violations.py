"""Single-failure validation rules: each test exercises exactly one rule."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_fund_payload,
    create_share_class_payload,
    create_investor_payload,
    create_subscription_payload,
    create_funding_payload,
    create_nav_period_payload,
    create_redemption_payload,
    setup_accepted_subscription,
    validate_error,
    validate_success,
)


class TestFundingAmountValidation:
    def test_funding_amount_zero_returns_invalid_amount(
        self, api, fund_admin_headers, transfer_agent_headers, compliance_officer_headers
    ):
        """PRD §3.4: "The amount must be positive — zero or negative amounts
        are rejected with ERR_INVALID_AMOUNT."

        Design: Corner/validations/funding_amount_zero_returns_invalid_amount
        """
        fund = validate_success(api.create_fund(create_fund_payload(), fund_admin_headers), 201)
        cls = validate_success(
            api.create_share_class(
                fund["id"],
                create_share_class_payload(
                    min_initial_investment_cents=100, min_additional_investment_cents=50
                ),
                fund_admin_headers,
            ),
            201,
        )
        inv = validate_success(
            api.create_investor(create_investor_payload(), fund_admin_headers), 201
        )
        sub = validate_success(
            api.create_subscription(
                fund["id"],
                create_subscription_payload(
                    investor_id=inv["id"], share_class_id=cls["id"],
                    commitment_amount_cents=500, funding_deadline_utc="2026-08-10T00:00:00Z",
                ),
                fund_admin_headers,
            ),
            201,
        )
        api.submit_subscription(fund["id"], sub["id"], transfer_agent_headers)
        api.compliance_approve_subscription(fund["id"], sub["id"], compliance_officer_headers)

        resp = api.record_funding(
            fund["id"], sub["id"],
            create_funding_payload(amount_cents=0, received_at_utc="2026-08-05T00:00:00Z"),
            transfer_agent_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_AMOUNT)


class TestMinimumInvestment:
    def test_below_minimum_investment_returns_error(self, api, fund_admin_headers):
        """PRD §3.4: "commitment_amount_cents must be at least the share
        class's min_initial_investment_cents (else ERR_BELOW_MIN_INVESTMENT)."

        Design: Corner/validations/below_minimum_investment_returns_error
        """
        fund = validate_success(api.create_fund(create_fund_payload(), fund_admin_headers), 201)
        cls = validate_success(
            api.create_share_class(
                fund["id"],
                create_share_class_payload(min_initial_investment_cents=100000),
                fund_admin_headers,
            ),
            201,
        )
        inv = validate_success(
            api.create_investor(create_investor_payload(), fund_admin_headers), 201
        )
        resp = api.create_subscription(
            fund["id"],
            create_subscription_payload(
                investor_id=inv["id"], share_class_id=cls["id"],
                commitment_amount_cents=99999,
                funding_deadline_utc="2026-08-10T00:00:00Z",
            ),
            fund_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_BELOW_MIN_INVESTMENT)


class TestRedemptionBalance:
    def test_redemption_exceeding_balance_returns_insufficient_balance(
        self, api, fund_admin_headers, transfer_agent_headers
    ):
        """PRD §3.7: "The requested amount must not exceed the capital
        account's current_balance_cents, else the request is rejected with
        ERR_INSUFFICIENT_BALANCE."

        Design: Corner/validations/redemption_exceeding_balance_returns_insufficient_balance
        """
        ctx = setup_accepted_subscription(commitment_amount_cents=100000)
        fund = ctx["fund"]
        nav_period = ctx["nav_period"]
        capital_account = ctx["capital_account"]

        resp = api.create_redemption(
            fund["id"],
            create_redemption_payload(
                capital_account_id=capital_account["id"],
                requested_amount_cents=999999,
                requested_effective_period_id=nav_period["id"],
            ),
            transfer_agent_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BALANCE)


class TestSuspendedFundRedemption:
    def test_suspended_fund_blocks_redemption_approve(
        self, api, fund_admin_headers, transfer_agent_headers
    ):
        """PRD §3.1: "Suspension blocks redemption approvals with
        ERR_REDEMPTIONS_SUSPENDED until lifted."

        Design: Corner/validations/suspended_fund_blocks_redemption_approve
        """
        ctx = setup_accepted_subscription(
            fund_overrides={"gate_threshold_pct": 0.50},
            commitment_amount_cents=200000,
        )
        fund = ctx["fund"]
        nav_period = ctx["nav_period"]
        capital_account = ctx["capital_account"]

        red = validate_success(
            api.create_redemption(
                fund["id"],
                create_redemption_payload(
                    capital_account_id=capital_account["id"],
                    requested_amount_cents=50000,
                    requested_effective_period_id=nav_period["id"],
                ),
                transfer_agent_headers,
            ),
            201,
        )
        # Suspend the fund, then attempt approval.
        api.suspend_redemptions(fund["id"], fund_admin_headers)
        resp = api.approve_redemption(fund["id"], red["id"], fund_admin_headers)
        validate_error(resp, ApiErrorId.ERR_REDEMPTIONS_SUSPENDED)
