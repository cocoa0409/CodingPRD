"""Disbursement legs, segregation of duties, cascades, trust accounting (PRD §3.7, §3.8, §2.8, §2.11)."""
import pytest
from test_helpers import (
    api_client, TEST_USERS, validate_success, validate_error, get_success_data,
    ApiErrorId, create_agent_payload, create_deal_payload,
    setup_active_agent, setup_agent_on_plan, setup_agent_with_debit,
    setup_closed_deal, setup_settled_deal, setup_released_deal,
    get_settlement_legs, get_leg_by_type, authorize_leg, release_leg,
    authorize_and_release_leg, get_window_for_agent,
    make_office_manager_headers, make_transaction_coordinator_headers,
)


class TestCobrokeAndReferralFanOut:
    def test_full_fan_out_leg_composition(self, api):
        """PRD §3.6: legs are created "in a fixed creation order, each created
        only when its amount is greater than zero": CO_BROKE, REFERRAL, ROYALTY,
        COMPANY ("the sum of company_dollar_cents, eo_fee_cents,
        transaction_fee_cents, and debit_recovery_cents"), MENTOR, TEAM_LEAD,
        AGENT.

        Design: Corner/calculations/cobroke_and_referral_fan_out_leg_composition
        """
        ref = setup_active_agent(name="Ref Rita")
        agent, plan, _e = setup_agent_on_plan(agent_name="Deal Dan")
        deal = setup_closed_deal(
            agent["id"], address="20 Cobroke Ct", gross_commission_cents=3000000,
            closing_date="2026-01-15", cobroke_payout_cents=500000,
            cobroke_payee_name="Outside Realty", referral_pct=0.25,
            referral_agent_id=ref["id"])
        s = get_success_data(api.settle_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]))
        assert s["referral_fee_cents"] == 625000
        assert s["royalty_cents"] == 112500
        assert s["company_dollar_cents"] == 528750
        assert s["agent_net_cents"] == 1202750
        legs = get_settlement_legs(s["id"])
        assert len(legs) == 5
        by_type = {leg["payee_type"]: leg for leg in legs}
        assert by_type["CO_BROKE"]["amount_cents"] == 500000
        assert by_type["CO_BROKE"]["payee_name"] == "Outside Realty"
        assert by_type["REFERRAL"]["amount_cents"] == 625000
        assert by_type["REFERRAL"]["payee_agent_id"] == ref["id"]
        assert by_type["ROYALTY"]["amount_cents"] == 112500
        assert by_type["COMPANY"]["amount_cents"] == 559750
        assert by_type["AGENT"]["amount_cents"] == 1202750

    def test_leg_amounts_sum_to_gross(self, api):
        """PRD §2.11: "The disbursement legs created by a settlement always sum,
        to the cent, to the deal's gross_commission_cents."

        Design: Corner/calculations/cobroke_and_referral_fan_out_leg_composition
        """
        ref = setup_active_agent(name="Ref Rita")
        agent, plan, _e = setup_agent_on_plan(agent_name="Deal Dan")
        deal = setup_closed_deal(
            agent["id"], gross_commission_cents=3000000, closing_date="2026-01-15",
            cobroke_payout_cents=500000, cobroke_payee_name="Outside Realty",
            referral_pct=0.25, referral_agent_id=ref["id"])
        s = get_success_data(api.settle_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]))
        legs = get_settlement_legs(s["id"])
        assert sum(leg["amount_cents"] for leg in legs) == 3000000


class TestMentorSplitWindow:
    def _setup_junior_with_mentor_and_lead(self, api):
        mentor = setup_active_agent(name="Mentor Meg")
        lead = setup_active_agent(name="Lead Leo")
        agent, plan, enr = setup_agent_on_plan(
            agent_name="Junior Jane",
            agent_overrides={"mentor_agent_id": mentor["id"],
                             "team_lead_agent_id": lead["id"],
                             "team_override_pct": 0.05})
        return mentor, lead, agent, plan

    def test_mentor_applies_for_first_three_deals_not_fourth(self, api):
        """PRD §3.6 step 5: "The mentor split applies only when the agent has a
        mentor_agent_id and the agent's settled_deal_count, read before this
        deal posts, is strictly below the plan's mentor_deal_count."

        Design: Corner/calculations/mentor_split_window_third_deal_boundary
        """
        mentor, lead, agent, plan = self._setup_junior_with_mentor_and_lead(api)
        deals = [
            setup_closed_deal(agent["id"], address=f"21 Mentor Mews {i}",
                              gross_commission_cents=2000000, closing_date=f"2026-01-{14+i:02d}")
            for i in range(1, 5)
        ]
        results = [get_success_data(api.settle_deal(d["id"], TEST_USERS["transaction_coordinator_headers"]))
                   for d in deals]
        assert results[0]["mentor_applied"] is True and results[0]["mentor_split_cents"] == 131600
        assert results[0]["royalty_cents"] == 120000 and results[0]["agent_net_cents"] == 1087600
        assert results[1]["mentor_split_cents"] == 131600 and results[1]["royalty_cents"] == 120000
        # deal 3: royalty clipped at cap room 60000
        assert results[2]["royalty_cents"] == 60000 and results[2]["royalty_capped"] is True
        assert results[2]["mentor_applied"] is True and results[2]["mentor_split_cents"] == 135800
        assert results[2]["agent_net_cents"] == 1123300
        # deal 4: count 3 hits the limit
        assert results[3]["mentor_applied"] is False and results[3]["mentor_split_cents"] == 0
        assert results[3]["royalty_cents"] == 0
        assert results[3]["agent_net_cents"] == 1299000

    def test_mentor_leg_present_only_when_applied(self, api):
        """PRD §3.6: "a `MENTOR` leg for `mentor_split_cents`, paying the
        settlement's mentor" — created "only when its amount is greater than
        zero — zero-amount legs are never created".

        Design: Corner/calculations/mentor_split_window_third_deal_boundary
        """
        mentor, lead, agent, plan = self._setup_junior_with_mentor_and_lead(api)
        deals = [
            setup_closed_deal(agent["id"], gross_commission_cents=2000000,
                              closing_date=f"2026-01-{14+i:02d}")
            for i in range(1, 5)
        ]
        settlements = [get_success_data(api.settle_deal(d["id"], TEST_USERS["transaction_coordinator_headers"]))
                       for d in deals]
        for i, expected in enumerate((131600, 131600, 135800)):
            leg = get_leg_by_type(settlements[i]["id"], "MENTOR")
            assert leg["amount_cents"] == expected
            assert leg["payee_agent_id"] == mentor["id"]
        legs4 = get_settlement_legs(settlements[3]["id"])
        assert all(leg["payee_type"] != "MENTOR" for leg in legs4)


class TestZeroAmountLegSuppression:
    def test_zero_agent_leg_suppressed_on_full_shortfall(self, api):
        """PRD §3.6: "each created only when its amount is greater than zero —
        zero-amount legs are never created". PRD §3.6 steps 7-8: "Whatever of
        the two flat fees could not be deducted accumulates into
        fee_shortfall_cents — ... which is accrued to the agent's debit
        balance."

        Design: Corner/calculations/zero_amount_agent_leg_suppressed_on_full_shortfall
        """
        agent, plan, _e = setup_agent_on_plan(agent_name="Tiny Tim")
        deal = setup_closed_deal(agent["id"], address="70 Tiny Ter",
                                 gross_commission_cents=5000, closing_date="2026-01-15")
        s = get_success_data(api.settle_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]))
        assert s["agent_net_cents"] == 0
        assert s["fee_shortfall_cents"] == 27710
        legs = get_settlement_legs(s["id"])
        assert len(legs) == 2
        by_type = {leg["payee_type"]: leg for leg in legs}
        assert by_type["ROYALTY"]["amount_cents"] == 300
        assert by_type["COMPANY"]["amount_cents"] == 4700
        assert "AGENT" not in by_type

    def test_shortfall_posts_fee_shortfall_accrual_ledger_entry(self, api):
        """PRD §3.6: "when `fee_shortfall_cents` is positive, a
        `FEE_SHORTFALL_ACCRUAL` ledger entry posts **first**, adding the
        shortfall to `debit_balance_cents`".

        Design: Corner/calculations/zero_amount_agent_leg_suppressed_on_full_shortfall
        """
        agent, plan, _e = setup_agent_on_plan(agent_name="Tiny Tim")
        deal = setup_closed_deal(agent["id"], gross_commission_cents=5000, closing_date="2026-01-15")
        api.settle_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"])
        entries = get_success_data(api.list_ledger_entries(
            TEST_USERS["broker_admin_headers"], params={"agent_id": agent["id"]}))
        assert entries[0]["entry_type"] == "FEE_SHORTFALL_ACCRUAL"
        assert entries[0]["amount_cents"] == 27710
        assert entries[0]["resulting_balance_cents"] == 27710


class TestTransitiveShortfallCascade:
    def test_shortfall_cascades_into_later_deal_recovery(self, api):
        """PRD §3.6 step 9: "debit_recovery_cents is the lesser of the agent
        share remaining after the fees and the agent's debit_balance_cents read
        before this deal posts; it is swept to the company."

        Design: Difficulty/transitive_cascade/settle_shortfall_cascades_into_later_deal_recovery
        """
        mentor = setup_active_agent(name="Mentor Mike")
        lead = setup_active_agent(name="Lead Laura")
        agent, plan, _e = setup_agent_on_plan(
            agent_name="Cascade Carl",
            agent_overrides={"mentor_agent_id": mentor["id"],
                             "team_lead_agent_id": lead["id"],
                             "team_override_pct": 0.05})
        tiny = setup_closed_deal(agent["id"], address="41 Tiny Ter",
                                 gross_commission_cents=5000, closing_date="2026-01-15")
        tiny_s = get_success_data(api.settle_deal(tiny["id"], TEST_USERS["transaction_coordinator_headers"]))
        # Waterfall on gross=5000 with mentor+team:
        #   royalty = 300, after_royalty = 4700
        #   company = 0.30*4700 = 1410, agent_gross = 3290
        #   mentor = 0.10*3290 = 329, team = 0.05*3290 = 165 (rounded half up)
        #   remaining = 3290-329-165 = 2796; eo = min(6000, 2796) = 2796
        #   txn = min(25000, 0) = 0
        #   fee_shortfall = (6000-2796) + (25000-0) = 3204 + 25000 = 28204
        assert tiny_s["fee_shortfall_cents"] == 28204
        assert tiny_s["agent_net_cents"] == 0
        mid = get_success_data(api.get_agent(agent["id"], TEST_USERS["broker_admin_headers"]))
        assert mid["debit_balance_cents"] == 28204
        big = setup_closed_deal(agent["id"], address="42 Big Bear Blvd",
                                gross_commission_cents=2000000, closing_date="2026-01-20")
        big_s = get_success_data(api.settle_deal(big["id"], TEST_USERS["transaction_coordinator_headers"]))
        assert big_s["mentor_split_cents"] == 131600
        assert big_s["team_override_cents"] == 65800
        assert big_s["eo_fee_cents"] == 6000
        assert big_s["transaction_fee_cents"] == 25000
        assert big_s["debit_recovery_cents"] == 28204
        assert big_s["agent_net_cents"] == 1059396
        after = get_success_data(api.get_agent(agent["id"], TEST_USERS["broker_admin_headers"]))
        assert after["debit_balance_cents"] == 0

    def test_ledger_order_accrual_precedes_recovery(self, api):
        """PRD §3.6: "when fee_shortfall_cents is positive, a
        FEE_SHORTFALL_ACCRUAL ledger entry posts first, adding the shortfall to
        debit_balance_cents, and when debit_recovery_cents is positive, a
        DEBIT_RECOVERY entry posts after it, subtracting the recovery from
        debit_balance_cents. Recovery therefore sweeps only the pre-existing
        balance, never this deal's own fresh shortfall."

        Design: Difficulty/transitive_cascade/settle_shortfall_cascades_into_later_deal_recovery
        """
        agent, plan, _e = setup_agent_on_plan(agent_name="Cascade Carl")
        tiny = setup_closed_deal(agent["id"], gross_commission_cents=5000, closing_date="2026-01-15")
        api.settle_deal(tiny["id"], TEST_USERS["transaction_coordinator_headers"])
        big = setup_closed_deal(agent["id"], gross_commission_cents=2000000, closing_date="2026-01-20")
        api.settle_deal(big["id"], TEST_USERS["transaction_coordinator_headers"])
        entries = get_success_data(api.list_ledger_entries(
            TEST_USERS["broker_admin_headers"], params={"agent_id": agent["id"]}))
        types = [e["entry_type"] for e in entries]
        assert types == ["FEE_SHORTFALL_ACCRUAL", "DEBIT_RECOVERY"]
        assert entries[0]["amount_cents"] == 27710
        assert entries[0]["resulting_balance_cents"] == 27710
        assert entries[1]["amount_cents"] == -27710
        assert entries[1]["resulting_balance_cents"] == 0


class TestUnsettleBlockedByLegs:
    def test_unsettle_blocked_by_authorized_leg(self, api):
        """PRD §3.8: "every leg of the settlement must be in SCHEDULED or VOIDED,
        and a leg standing AUTHORIZED or RELEASED blocks the reversal with
        ERR_LEGS_OUTSTANDING (HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/unsettle_blocked_by_authorized_leg
        """
        agent, plan, _e = setup_agent_on_plan(agent_name="Block Bob")
        settlement, deal = setup_settled_deal(agent["id"], poster_user_id="tc-1")
        leg = get_settlement_legs(settlement["id"])[0]
        authorize_leg(leg["id"], user_id="om-1")
        resp = api.unsettle_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"])
        validate_error(resp, ApiErrorId.ERR_LEGS_OUTSTANDING, expected_status=409)

    def test_blocked_unsettle_leaves_state_untouched(self, api):
        """PRD §3.8: "every leg of the settlement must be in `SCHEDULED` or
        `VOIDED`, and a leg standing `AUTHORIZED` or `RELEASED` blocks the
        reversal with `ERR_LEGS_OUTSTANDING` (HTTP 409)" — the rejected unsettle
        leaves the deal `SETTLED`, the settlement `POSTED`, and the leg
        untouched.

        Design: Difficulty/cross_entity_state_dependency/unsettle_blocked_by_authorized_leg
        """
        agent, plan, _e = setup_agent_on_plan(agent_name="Block Bob")
        settlement, deal = setup_settled_deal(agent["id"], poster_user_id="tc-1")
        leg = get_settlement_legs(settlement["id"])[0]
        authorize_leg(leg["id"], user_id="om-1")
        api.unsettle_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"])
        deal_after = get_success_data(api.get_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]))
        assert deal_after["status"] == "SETTLED"
        s_after = get_success_data(api.get_settlement(settlement["id"], TEST_USERS["transaction_coordinator_headers"]))
        assert s_after["status"] == "POSTED"
        leg_after = get_success_data(api.get_leg(leg["id"], TEST_USERS["office_manager_headers"]))
        assert leg_after["status"] == "AUTHORIZED"
        assert leg_after["authorized_by_user_id"] == "om-1"


class TestSegregationOfDuties:
    def test_poster_cannot_authorize_own_settlement_leg(self, api):
        """PRD §2.8: "authorizing a disbursement leg requires the caller's
        `X-User-ID` to differ from the settlement's `posted_by_user_id` ...
        Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES`
        (HTTP 403)."

        Design: Corner/state_machines/sod_poster_cannot_authorize_own_settlement_leg
        """
        agent, plan, _e = setup_agent_on_plan(agent_name="Sod Sara")
        settlement, deal = setup_settled_deal(agent["id"], poster_user_id="tc-1")
        assert settlement["posted_by_user_id"] == "tc-1"
        leg = get_leg_by_type(settlement["id"], "AGENT")
        resp = api.authorize_leg(leg["id"], make_office_manager_headers("tc-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)
        ok = get_success_data(api.authorize_leg(leg["id"], make_office_manager_headers("om-9")))
        assert ok["status"] == "AUTHORIZED"
        assert ok["authorized_by_user_id"] == "om-9"

    def test_authorizer_cannot_release_own_authorization(self, api):
        """PRD §2.8: "releasing a leg requires the caller's `X-User-ID` to
        differ from that leg's `authorized_by_user_id`. Either violation is
        rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/state_machines/sod_authorizer_cannot_release_own_authorization
        """
        agent, plan, _e = setup_agent_on_plan(agent_name="Sod Steve")
        settlement, deal = setup_settled_deal(agent["id"], poster_user_id="tc-1")
        leg = get_leg_by_type(settlement["id"], "AGENT")
        authorize_leg(leg["id"], user_id="om-1")
        resp = api.release_leg(leg["id"], make_office_manager_headers("om-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)
        released = get_success_data(api.release_leg(leg["id"], make_office_manager_headers("om-2")))
        assert released["status"] == "RELEASED"
        assert released["released_by_user_id"] == "om-2"
        assert released["released_at"]


class TestLegStateBeatsSoD:
    def test_state_error_beats_segregation_of_duties(self, api):
        """PRD §2.9: "the first failing guard determines the error returned — a
        request that would fail several checks always reports the earliest one.
        The order is: ... 8. State validity ... 9. Segregation of duties".

        Design: Difficulty/priority_pair_validation_conflict/leg_state_error_beats_segregation_of_duties
        """
        agent, plan, _e = setup_agent_on_plan(agent_name="Sod Sandy")
        settlement, deal = setup_settled_deal(agent["id"], poster_user_id="tc-99")
        leg = get_settlement_legs(settlement["id"])[0]
        authorize_leg(leg["id"], user_id="om-1")
        # caller IS the poster (SoD fails) AND leg is AUTHORIZED (state fails);
        # state (priority 8) wins
        resp = api.authorize_leg(leg["id"], make_office_manager_headers("tc-99"))
        validate_error(resp, ApiErrorId.ERR_LEG_INVALID_STATE, expected_status=409)

    def test_leg_remains_authorized_after_blocked_reauthorize(self, api):
        """PRD §3.7: "the leg must be `SCHEDULED`, else `ERR_LEG_INVALID_STATE`
        (HTTP 409)" — the rejected re-authorize leaves the leg untouched.

        Design: Difficulty/priority_pair_validation_conflict/leg_state_error_beats_segregation_of_duties
        """
        agent, plan, _e = setup_agent_on_plan(agent_name="Sod Sandy")
        settlement, deal = setup_settled_deal(agent["id"], poster_user_id="tc-99")
        leg = get_settlement_legs(settlement["id"])[0]
        authorize_leg(leg["id"], user_id="om-1")
        api.authorize_leg(leg["id"], make_office_manager_headers("tc-99"))
        leg_after = get_success_data(api.get_leg(leg["id"], TEST_USERS["office_manager_headers"]))
        assert leg_after["status"] == "AUTHORIZED"
        assert leg_after["authorized_by_user_id"] == "om-1"


class TestTrustConservation:
    def test_trust_conservation_across_release(self, api):
        """PRD §2.11: "The global trust balance — the sum of amount_cents across
        every trust transaction ever recorded — is never negative... once the
        deal reaches DISBURSED, its RELEASE transactions sum to the gross and the
        deal's net trust position returns to zero."

        Design: Difficulty/compensating_invariant/trust_conservation_across_release_and_void
        """
        agent, plan, _e = setup_agent_on_plan(agent_name="Trust Tess")
        settlement, deal, legs = setup_released_deal(agent["id"], gross_commission_cents=1000000)
        assert len(legs) == 3
        ledger = get_success_data(api.get_trust_ledger(TEST_USERS["auditor_headers"]))
        assert ledger["received_cents"] == 1000000
        assert ledger["released_cents"] == 1000000
        assert ledger["held_cents"] == 0

    def test_deal_bubbles_to_disbursed_and_final_balance_zero(self, api):
        """PRD §3.7: "it fires the bubble-up — when every leg of the settlement
        stands RELEASED, the deal transitions from SETTLED to DISBURSED."
        PRD §2.11: "once the deal reaches DISBURSED, its RELEASE transactions sum
        to the gross and the deal's net trust position returns to zero."

        Design: Difficulty/compensating_invariant/trust_conservation_across_release_and_void
        """
        agent, plan, _e = setup_agent_on_plan(agent_name="Trust Tess")
        settlement, deal = setup_settled_deal(agent["id"], gross_commission_cents=1000000,
                                              poster_user_id="tc-1")
        legs = get_settlement_legs(settlement["id"])
        for leg in legs:
            authorize_and_release_leg(leg["id"], authorizer="om-1", releaser="om-2")
        deal_after = get_success_data(api.get_deal(deal["id"], TEST_USERS["auditor_headers"]))
        assert deal_after["status"] == "DISBURSED"
        txns = get_success_data(api.list_trust_transactions(
            TEST_USERS["auditor_headers"], params={"deal_id": deal["id"]}))
        releases = [t for t in txns if t["kind"] == "RELEASE"]
        assert releases[-1]["trust_balance_after_cents"] == 0
        assert all(t["trust_balance_after_cents"] >= 0 for t in txns)
