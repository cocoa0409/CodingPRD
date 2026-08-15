"""Queue A — compensating_invariant: conserved quantities across mutations.

Instances:
  - redemption_settle_conserves_net_assets_identity
  - late_fee_cancellation_conserves_commitment_arithmetic
"""
from test_helpers import (
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
    get_investor,
    list_capital_accounts,
    setup_accepted_subscription,
    validate_success,
)

FA = TEST_USERS["fund_admin_headers"]
CO = TEST_USERS["compliance_officer_headers"]
TA = TEST_USERS["transfer_agent_headers"]


class TestRedemptionSettleConservesNetAssets:
    """Two tests for Difficulty/compensating_invariant/redemption_settle_conserves_net_assets_identity."""

    def _build_settled_redemption_ctx(self):
        """Fund with one accepted subscription 500_000c; one APPROVED
        redemption of 200_000c; then finalize+close to settle."""
        ctx = setup_accepted_subscription(
            fund_overrides={"gate_threshold_pct": 0.50},
            commitment_amount_cents=500000,
        )
        fund = ctx["fund"]
        nav_period = ctx["nav_period"]
        ca = ctx["capital_account"]
        red = validate_success(
            api_client.create_redemption(
                fund["id"],
                create_redemption_payload(
                    capital_account_id=ca["id"],
                    requested_amount_cents=200000,
                    requested_effective_period_id=nav_period["id"],
                ),
                TA,
            ),
            201,
        )
        api_client.approve_redemption(fund["id"], red["id"], FA)
        fv2 = get_fund(fund["id"])["version"]
        api_client.finalize_nav_period(
            fund["id"], nav_period["id"],
            {"gross_return_bps": 0, "expected_fund_version": fv2},
            FA,
        )
        api_client.close_nav_period(fund["id"], nav_period["id"], FA)
        return ctx

    def test_fund_net_assets_decremented_by_settled_amount(self, api, fund_admin_headers):
        """PRD §3.7: "the capital account's current_balance_cents is reduced
        by that amount, the fund's total_net_assets_cents is reduced by the
        same amount."

        Design: Difficulty/compensating_invariant/redemption_settle_conserves_net_assets_identity
        """
        ctx = self._build_settled_redemption_ctx()
        fund_after = get_fund(ctx["fund"]["id"])
        assert fund_after["total_net_assets_cents"] == 500000 - 200000

    def test_capital_account_balance_decremented_by_settled_amount(
        self, api, fund_admin_headers
    ):
        """PRD §3.7: "the capital account's current_balance_cents is
        reduced by that amount, the fund's total_net_assets_cents is
        reduced by the same amount."

        Design: Difficulty/compensating_invariant/redemption_settle_conserves_net_assets_identity
        """
        ctx = self._build_settled_redemption_ctx()
        ca_id = ctx["capital_account"]["id"]
        inv_id = ctx["investor"]["id"]
        ca_after = validate_success(
            api.get_capital_account(inv_id, ca_id, fund_admin_headers), 200
        )
        assert ca_after["current_balance_cents"] == 500000 - 200000


class TestLateFeeCancellationInvariant:
    """Two tests for Difficulty/compensating_invariant/late_fee_cancellation_conserves_commitment_arithmetic."""

    def _build_partial_funding_ctx(self, funded_amount_cents=333, commitment=100000):
        fund = validate_success(api_client.create_fund(create_fund_payload(), FA), 201)
        cls = validate_success(
            api_client.create_share_class(
                fund["id"],
                create_share_class_payload(
                    min_initial_investment_cents=100, min_additional_investment_cents=50,
                ),
                FA,
            ),
            201,
        )
        inv = validate_success(api_client.create_investor(create_investor_payload(), FA), 201)
        sub = validate_success(
            api_client.create_subscription(
                fund["id"],
                create_subscription_payload(
                    investor_id=inv["id"], share_class_id=cls["id"],
                    commitment_amount_cents=commitment,
                    funding_deadline_utc="2026-08-05T00:00:00Z",
                ),
                FA,
            ),
            201,
        )
        api_client.submit_subscription(fund["id"], sub["id"], TA)
        api_client.compliance_approve_subscription(fund["id"], sub["id"], CO)
        api_client.record_funding(
            fund["id"], sub["id"],
            create_funding_payload(
                amount_cents=funded_amount_cents, received_at_utc="2026-08-04T00:00:00Z"
            ),
            TA,
        )
        return {"fund": fund, "inv": inv, "sub": sub, "commitment": commitment,
                "funded": funded_amount_cents}

    def test_aggregate_unfunded_commitment_reflects_partial_funding(
        self, api, fund_admin_headers
    ):
        """PRD §3.4: "recomputes the investor's
        aggregate_unfunded_commitment_cents (which sums, across all the
        investor's subscriptions in ACCEPTED or FUNDING_PARTIAL status,
        each subscription's commitment minus its funded amount)."

        Design: Difficulty/compensating_invariant/late_fee_cancellation_conserves_commitment_arithmetic
        """
        ctx = self._build_partial_funding_ctx(funded_amount_cents=333, commitment=1000)
        inv_after = get_investor(ctx["inv"]["id"])
        # Unfunded = 1000 - 333 = 667.
        assert inv_after["aggregate_unfunded_commitment_cents"] == 667

    def test_aggregate_unfunded_zero_after_cancellation(self, api, fund_admin_headers):
        """PRD §3.4: "If the funding deadline passes with a subscription
        still in FUNDING_PARTIAL, a FundAdmin may cancel it. Cancellation
        ... recomputes the investor's aggregate_unfunded_commitment_cents."
        Once cancelled, the subscription is no longer in FUNDING_PARTIAL,
        so it drops out of the aggregate.

        Design: Difficulty/compensating_invariant/late_fee_cancellation_conserves_commitment_arithmetic
        """
        ctx = self._build_partial_funding_ctx(funded_amount_cents=333, commitment=1000)
        api_client.set_current_utc({"to_iso8601": "2026-08-08T00:00:00Z"}, fund_admin_headers)
        api_client.cancel_subscription(ctx["fund"]["id"], ctx["sub"]["id"], fund_admin_headers)
        inv_after = get_investor(ctx["inv"]["id"])
        assert inv_after["aggregate_unfunded_commitment_cents"] == 0
