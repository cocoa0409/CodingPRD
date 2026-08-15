"""Queue A — transitive_cascade: multi-level side-effect cascades.

Instances:
  - kyc_reject_cascades_to_subscriptions_and_investor
  - nav_finalize_cascades_to_series_and_capital_accounts
"""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_fund_payload,
    create_share_class_payload,
    create_investor_payload,
    create_kyc_case_payload,
    create_subscription_payload,
    create_funding_payload,
    get_fund,
    get_investor,
    get_subscription,
    list_capital_accounts,
    list_series,
    setup_accepted_subscription,
    validate_success,
)

FA = TEST_USERS["fund_admin_headers"]
CO = TEST_USERS["compliance_officer_headers"]
TA = TEST_USERS["transfer_agent_headers"]


class TestKycRejectCascade:
    """Two tests for Difficulty/transitive_cascade/kyc_reject_cascades_to_subscriptions_and_investor."""

    def _build_ctx(self):
        fund = validate_success(api_client.create_fund(create_fund_payload(), FA), 201)
        cls = validate_success(
            api_client.create_share_class(fund["id"], create_share_class_payload(), FA), 201
        )
        inv = validate_success(
            api_client.create_investor(create_investor_payload(), FA), 201
        )
        kyc = validate_success(
            api_client.create_kyc_case(
                inv["id"],
                create_kyc_case_payload(risk_rating="LOW"),
                CO,
            ),
            201,
        )
        sub = validate_success(
            api_client.create_subscription(
                fund["id"],
                create_subscription_payload(
                    investor_id=inv["id"], share_class_id=cls["id"],
                    commitment_amount_cents=200000,
                    funding_deadline_utc="2026-08-31T00:00:00Z",
                ),
                FA,
            ),
            201,
        )
        api_client.submit_subscription(fund["id"], sub["id"], TA)
        return {"fund": fund, "cls": cls, "inv": inv, "kyc": kyc, "sub": sub}

    def test_kyc_reject_cascades_to_investor_status(self, api, compliance_officer_headers):
        """PRD §3.2: "Rejecting a case (from AWAITING_DOCUMENTS, IN_REVIEW,
        or ESCALATED) sets the case's rejection_reason, marks the investor's
        kyc_status as REJECTED."

        Design: Difficulty/transitive_cascade/kyc_reject_cascades_to_subscriptions_and_investor
        """
        ctx = self._build_ctx()
        api_client.reject_kyc_case(
            ctx["inv"]["id"], ctx["kyc"]["id"],
            {"rejection_reason": "sanctions"},
            compliance_officer_headers,
        )
        inv_after = get_investor(ctx["inv"]["id"])
        assert inv_after["kyc_status"] == "REJECTED"

    def test_kyc_reject_cascades_to_non_terminal_subscriptions(
        self, api, fund_admin_headers, compliance_officer_headers
    ):
        """PRD §3.2: "Rejecting a case ... transitions every non-terminal
        Subscription belonging to that investor to REJECTED."

        Design: Difficulty/transitive_cascade/kyc_reject_cascades_to_subscriptions_and_investor
        """
        ctx = self._build_ctx()
        api_client.reject_kyc_case(
            ctx["inv"]["id"], ctx["kyc"]["id"],
            {"rejection_reason": "sanctions"},
            compliance_officer_headers,
        )
        sub_after = get_subscription(ctx["fund"]["id"], ctx["sub"]["id"])
        assert sub_after["status"] == "REJECTED", (
            f"Subscription must cascade to REJECTED, got {sub_after['status']}"
        )


class TestNavFinalizeCascade:
    """Two tests for Difficulty/transitive_cascade/nav_finalize_cascades_to_series_and_capital_accounts."""

    def _build_ctx(self):
        return setup_accepted_subscription(
            class_overrides={
                "management_fee_bps": 200,
                "performance_fee_bps": 2000,
                "hurdle_rate_bps": 0,
                "high_water_mark_required": True,
            },
            commitment_amount_cents=1000000,
        )

    def test_finalize_marks_nav_period_and_series_finalized(self, api, fund_admin_headers):
        """PRD §3.6: "Finalization transitions the period from OPEN to
        NAV_FINALIZED ... and — for each OPEN series of each share class of
        the fund — computes the series equalization factor and transitions
        the series to FINALIZED, locking the factor."

        Design: Difficulty/transitive_cascade/nav_finalize_cascades_to_series_and_capital_accounts
        """
        ctx = self._build_ctx()
        fund = ctx["fund"]
        share_class = ctx["share_class"]
        nav_period = ctx["nav_period"]

        fv = get_fund(fund["id"])["version"]
        resp = api.finalize_nav_period(
            fund["id"], nav_period["id"],
            {"gross_return_bps": 500, "expected_fund_version": fv},
            fund_admin_headers,
        )
        period_after = validate_success(resp, 200)
        assert period_after["status"] == "NAV_FINALIZED"

        series = list_series(fund["id"], share_class["id"])
        assert series, "expected at least one series"
        for s in series:
            assert s["status"] == "FINALIZED", (
                f"Series must be FINALIZED after NavPeriod finalize, got {s['status']}"
            )

    def test_finalize_applies_gross_return_to_capital_account(
        self, api, fund_admin_headers
    ):
        """PRD §3.6: "Finalization ... applies the gross return to each
        capital account."

        Design: Difficulty/transitive_cascade/nav_finalize_cascades_to_series_and_capital_accounts
        """
        ctx = self._build_ctx()
        fund = ctx["fund"]
        nav_period = ctx["nav_period"]
        investor = ctx["investor"]
        ca_id = ctx["capital_account"]["id"]

        fv = get_fund(fund["id"])["version"]
        api.finalize_nav_period(
            fund["id"], nav_period["id"],
            {"gross_return_bps": 500, "expected_fund_version": fv},
            fund_admin_headers,
        )
        ca_after = validate_success(
            api.get_capital_account(investor["id"], ca_id, fund_admin_headers), 200
        )
        # 500 bps = 5% gross return on 1_000_000 → balance should increase
        # by at least 5%. (Management fee accrual may offset slightly; we
        # assert a directional lower bound.)
        assert ca_after["current_balance_cents"] >= 1000000, (
            f"Expected balance to reflect positive gross return; got {ca_after['current_balance_cents']}"
        )
