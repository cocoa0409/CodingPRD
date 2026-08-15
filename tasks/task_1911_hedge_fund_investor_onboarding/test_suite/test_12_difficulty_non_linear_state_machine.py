"""Queue A — non_linear_state_machine: cyclic/branching state transitions.

Instances:
  - side_letter_cyclic_mfn_reelection
  - redemption_request_parallel_gate_branching
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
    create_mfn_clause,
    get_fund,
    list_capital_accounts,
    make_investor_headers,
    setup_accepted_subscription,
    setup_executed_side_letter,
    validate_success,
)

FA = TEST_USERS["fund_admin_headers"]
CO = TEST_USERS["compliance_officer_headers"]
TA = TEST_USERS["transfer_agent_headers"]


class TestSideLetterCyclicMfnReelection:
    """Two tests for Difficulty/non_linear_state_machine/side_letter_cyclic_mfn_reelection."""

    def _build_ctx(self):
        ctx = setup_accepted_subscription(commitment_amount_cents=200000)
        c1 = create_mfn_clause(
            ctx["fund"]["id"], clause_tag="FEE_REBATE", clause_text="r1",
            capacity_threshold_cents=0, fee_rebate_bps=100, notice_days_reduction=0,
        )
        c2 = create_mfn_clause(
            ctx["fund"]["id"], clause_tag="LIQUIDITY", clause_text="l1",
            capacity_threshold_cents=0, fee_rebate_bps=0, notice_days_reduction=5,
        )
        ctx["c1"] = c1
        ctx["c2"] = c2
        ctx = setup_executed_side_letter(ctx)
        return ctx

    def test_cyclic_election_keeps_letter_executed(self, api, fund_admin_headers):
        """PRD §3.5: "subsequent elections amend the existing election by
        appending to elected_clause_ids" — i.e., re-election is an
        EXECUTED→EXECUTED self-loop with no state change.

        Design: Difficulty/non_linear_state_machine/side_letter_cyclic_mfn_reelection
        """
        ctx = self._build_ctx()
        fund = ctx["fund"]
        side_letter = ctx["side_letter"]
        investor = ctx["investor"]
        investor_headers = make_investor_headers(investor["id"])

        api.elect_mfn(fund["id"], side_letter["id"],
                      {"mfn_clause_id": ctx["c1"]["id"]}, investor_headers)
        resp = api.elect_mfn(fund["id"], side_letter["id"],
                             {"mfn_clause_id": ctx["c2"]["id"]}, investor_headers)
        letter = validate_success(resp, 200)
        assert letter["status"] == "EXECUTED", (
            f"Cyclic election must leave letter EXECUTED, got {letter['status']}"
        )

    def test_cyclic_election_appends_and_flips_mfn_active(self, api, fund_admin_headers):
        """PRD §3.5: "The first election flips mfn_election_active to true;
        subsequent elections amend the existing election by appending to
        elected_clause_ids."

        Design: Difficulty/non_linear_state_machine/side_letter_cyclic_mfn_reelection
        """
        ctx = self._build_ctx()
        fund = ctx["fund"]
        side_letter = ctx["side_letter"]
        investor = ctx["investor"]
        investor_headers = make_investor_headers(investor["id"])

        api.elect_mfn(fund["id"], side_letter["id"],
                      {"mfn_clause_id": ctx["c1"]["id"]}, investor_headers)
        api.elect_mfn(fund["id"], side_letter["id"],
                      {"mfn_clause_id": ctx["c2"]["id"]}, investor_headers)

        letter = validate_success(
            api.get_side_letter(fund["id"], side_letter["id"], fund_admin_headers), 200
        )
        assert len(letter["elected_clause_ids"]) == 2
        assert letter["mfn_election_active"] is True


class TestRedemptionGateBranching:
    """Two tests for Difficulty/non_linear_state_machine/redemption_request_parallel_gate_branching."""

    def _build_gated_redemptions_ctx(self):
        """Fund with gate_threshold_pct=0.10, total net assets 1_000_000c,
        three approved redemption requests totalling 300_000c (> 100_000 pool).

        Note: the design yaml uses two redemptions totalling 300_000 — same
        binding geometry (total > pool). We follow the yaml setup chain.
        """
        fund = validate_success(
            api_client.create_fund(
                create_fund_payload(gate_threshold_pct=0.10), FA
            ),
            201,
        )
        cls = validate_success(
            api_client.create_share_class(fund["id"], create_share_class_payload(), FA), 201
        )
        period = validate_success(
            api_client.create_nav_period(fund["id"], create_nav_period_payload(), FA), 201
        )
        inv1 = validate_success(
            api_client.create_investor(create_investor_payload(legal_name="Inv 1"), FA), 201
        )
        inv2 = validate_success(
            api_client.create_investor(create_investor_payload(legal_name="Inv 2"), FA), 201
        )

        def _fund_and_accept(inv, amount):
            sub = validate_success(
                api_client.create_subscription(
                    fund["id"],
                    create_subscription_payload(
                        investor_id=inv["id"], share_class_id=cls["id"],
                        commitment_amount_cents=amount,
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
                create_funding_payload(amount_cents=amount, received_at_utc="2026-08-04T00:00:00Z"),
                TA,
            )
            fv = get_fund(fund["id"])["version"]
            api_client.accept_subscription(
                fund["id"], sub["id"], {"expected_fund_version": fv}, FA
            )
            return sub

        _fund_and_accept(inv1, 600000)
        sub2 = _fund_and_accept(inv2, 400000)

        ca1 = list_capital_accounts(inv1["id"])[0]
        ca2 = list_capital_accounts(inv2["id"])[0]

        red1 = validate_success(
            api_client.create_redemption(
                fund["id"],
                create_redemption_payload(
                    capital_account_id=ca1["id"],
                    requested_amount_cents=200000,
                    requested_effective_period_id=period["id"],
                ),
                TA,
            ),
            201,
        )
        red2 = validate_success(
            api_client.create_redemption(
                fund["id"],
                create_redemption_payload(
                    capital_account_id=ca2["id"],
                    requested_amount_cents=100000,
                    requested_effective_period_id=period["id"],
                ),
                TA,
            ),
            201,
        )
        api_client.approve_redemption(fund["id"], red1["id"], FA)
        api_client.approve_redemption(fund["id"], red2["id"], FA)
        fv2 = get_fund(fund["id"])["version"]
        api_client.finalize_nav_period(
            fund["id"], period["id"],
            {"gross_return_bps": 0, "expected_fund_version": fv2}, FA,
        )
        return {
            "fund": fund, "period": period, "red1": red1, "red2": red2,
        }

    def test_gate_binds_and_requests_settle_with_gate_applied(self, api, fund_admin_headers):
        """PRD §3.7: "At period close, if the sum of approved redemption
        amounts for the fund exceeds the fund-level gate ... the gate binds
        and each approved request transitions from APPROVED to
        PARTIALLY_APPROVED."

        Design: Difficulty/non_linear_state_machine/redemption_request_parallel_gate_branching
        """
        ctx = self._build_gated_redemptions_ctx()
        resp = api.close_nav_period(ctx["fund"]["id"], ctx["period"]["id"], fund_admin_headers)
        validate_success(resp, 200)

        r1 = validate_success(
            api.get_redemption(ctx["fund"]["id"], ctx["red1"]["id"], fund_admin_headers), 200
        )
        r2 = validate_success(
            api.get_redemption(ctx["fund"]["id"], ctx["red2"]["id"], fund_admin_headers), 200
        )
        # Both requests must reach SETTLED after close (the PARTIALLY_APPROVED
        # intermediate is consumed by close, which settles the gated portion).
        assert r1["status"] == "SETTLED"
        assert r2["status"] == "SETTLED"
        # Gate bound: gate_applied_pct > 0 on at least one.
        assert (r1["gate_applied_pct"] > 0) or (r2["gate_applied_pct"] > 0)

    def test_gate_settled_amounts_sum_to_pool(self, api, fund_admin_headers):
        """PRD §3.7: "The gate pool in cents is the floor of the threshold
        times the net assets." With threshold 0.10 and net assets 1_000_000,
        the pool is exactly 100_000 and the settled amounts must sum to it.

        Design: Difficulty/non_linear_state_machine/redemption_request_parallel_gate_branching
        """
        ctx = self._build_gated_redemptions_ctx()
        api.close_nav_period(ctx["fund"]["id"], ctx["period"]["id"], fund_admin_headers)

        r1 = validate_success(
            api.get_redemption(ctx["fund"]["id"], ctx["red1"]["id"], fund_admin_headers), 200
        )
        r2 = validate_success(
            api.get_redemption(ctx["fund"]["id"], ctx["red2"]["id"], fund_admin_headers), 200
        )
        total_settled = r1["settled_amount_cents"] + r2["settled_amount_cents"]
        # Gate pool = floor(0.10 * 1_000_000) = 100_000.
        assert total_settled == 100000, (
            f"Gated settled amounts must sum to gate pool 100000, got {total_settled}"
        )
