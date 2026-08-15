"""Second-angle tests for §1.8 difficulty instances (each instance needs >=2).

Each test in this file exercises the same rule as its primary counterpart but
from a distinct observable angle (a different field, a different hop, or a
different boundary direction), reusing the shared composite fixtures.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, make_trader_headers, make_analyst_headers, make_credit_headers,
)
from test_helpers.fixtures import (
    ISO, set_clock, create_participant, create_generator, create_operating_day,
    create_offer, submit_offer, withdraw_offer, run_da_market, close_real_time,
    run_prelim_settlement, run_final_settlement, submit_telemetry,
    create_outage, create_obligation, create_posting,
    setup_participant_generator, setup_day_with_offer, setup_final_settled,
    setup_preliminary_settled, get_statement_by_day_and_type,
    get_open_margin_call, uniform_readings_24,
)
from test_helpers.assertions import assert_statement_net_invariant

DA_DECK = [{"node_name": "WEST_HUB", "da_energy_cents_per_mwh": 5000,
            "da_congestion_cents_per_mwh": 200, "da_loss_cents_per_mwh": 100}]
RT_PRELIM = [{"node_name": "WEST_HUB", "rt_prelim_energy_cents_per_mwh": 4000,
              "rt_prelim_congestion_cents_per_mwh": 50, "rt_prelim_loss_cents_per_mwh": 25}]


def _first_line(api, statement_id, charge_type=None):
    params = {"settlement_statement_id": statement_id}
    if charge_type:
        params["charge_type"] = charge_type
    rows, _ = validate_paginated(api.list_lines(ISO, params=params))
    return rows[0] if rows else None


class TestDualVariantSecondAngle:
    def test_preliminary_statement_superseded_leaves_requirement_input_set(self, api):
        """PRD §2.8: "Statements in any other run type or status —
        `PRELIMINARY`, `SUPERSEDED`, `CLOSED`, `PAID` — are excluded from the
        input set." and §3.5 final settlement "supersedes every `PRELIMINARY`
        statement of the day (`ISSUED` → `SUPERSEDED`)".

        Design: Difficulty/dual_variant_calc/settlement_preliminary_vs_final_divergence
        """
        p_id, g_id, d_id, s_fin = setup_final_settled(rt_final=[
            {"node_name": "WEST_HUB", "rt_final_energy_cents_per_mwh": 4000,
             "rt_final_congestion_cents_per_mwh": 50, "rt_final_loss_cents_per_mwh": 25}])
        s_pre = get_statement_by_day_and_type(d_id, p_id, "PRELIMINARY")
        assert s_pre["status"] == "SUPERSEDED"
        assert s_fin["run_type"] == "FINAL"
        assert s_fin["status"] == "ISSUED"

    def test_collateral_net_variant_floors_at_zero(self, api):
        """PRD §2.8: "An `INVESTMENT_GRADE` participant is charged on net
        exposure: the signed statement remainders are summed across days and
        floored at zero, then offer and capacity risk are added".

        Design: Difficulty/dual_variant_calc/collateral_requirement_gross_vs_net_tiers
        """
        set_clock("2026-08-01T00:00:00Z")
        _, p_id = create_participant(company_name="Net Co", tier="INVESTMENT_GRADE")
        _, g_id, _ = create_generator(p_id, unit_name="A1")
        _, d2, _ = create_operating_day(market_date="2026-08-11", gate_close="2026-08-10T10:30:00Z")
        api.create_award(d2, {
            "generator_asset_id": g_id, "service_type": "REGULATION", "awarded_mw": 5,
            "capacity_price_cents": 1200, "performance_price_cents": 300,
            "mileage_ratio": 2.0, "start_interval": 1, "end_interval": 4}, ISO)
        run_da_market(d2, [])
        g_v = get_success_data(api.get_generator(g_id, ISO))["version"]
        submit_telemetry(g_id, d2, [{"interval_index": i, "actual_mw": 5} for i in range(1, 5)], g_v, p_id)
        close_real_time(d2, [])
        run_prelim_settlement(d2)
        run_final_settlement(d2, [])
        r = get_success_data(api.evaluate_credit(p_id, ISO))
        # single credit statement -9000 nets below zero -> floored to 0
        assert r["collateral_requirement_cents"] == 0


class TestCombinatorialSecondAngle:
    def test_ancillary_sync_reserve_has_no_performance_branch(self, api):
        """PRD §3.6: "while other service types earn no performance component."
        and "The capacity component is `awarded_mw` times `capacity_price_cents`
        times the tier multiplier."

        Design: Difficulty/combinatorial_formula/ancillary_tiered_revenue_with_regulation_branch
        """
        set_clock("2026-08-01T00:00:00Z")
        _, p_id = create_participant(company_name="Anc2 Co")
        _, g_id, g_v = create_generator(p_id, unit_name="U1")
        _, d_id, _ = create_operating_day(market_date="2026-08-03")
        resp = api.create_award(d_id, {
            "generator_asset_id": g_id, "service_type": "SYNC_RESERVE", "awarded_mw": 5,
            "capacity_price_cents": 1200, "start_interval": 5, "end_interval": 8}, ISO)
        aw_s = get_success_data(resp)["id"]
        run_da_market(d_id, [])
        submit_telemetry(g_id, d_id, [{"interval_index": i, "actual_mw": 5} for i in (5, 6, 7, 8)], g_v, p_id)
        close_real_time(d_id, [])
        run_prelim_settlement(d_id)
        aw = get_success_data(api.get_award(aw_s, ISO))
        # score 1.00 -> tier 1.00; capacity only: 5*1200*1.00 = 6000
        assert aw["revenue_cents"] == 6000
        assert aw["status"] == "SETTLED"

    def test_congestion_rt_component_uses_signed_deviation(self, api):
        """PRD §3.5: "the negated deviation times the node's real-time
        congestion component, and the negated deviation times the real-time
        loss component, so a short interval pays real-time congestion and
        losses on its shortfall while a long interval is credited."

        Design: Difficulty/combinatorial_formula/congestion_per_interval_rounding_order
        """
        set_clock("2026-08-01T00:00:00Z")
        _, p_id = create_participant(company_name="Round2 Co")
        _, g_id, g_v = create_generator(p_id, unit_name="U1")
        _, d_id, d_v = create_operating_day(market_date="2026-08-03")
        _, o_id = create_offer(d_id, g_id, offered_mw=10, offer_price=5000,
                               day_version=d_v, participant_id=p_id)
        submit_offer(o_id, p_id)
        run_da_market(d_id, DA_DECK)
        submit_telemetry(g_id, d_id,
                         [{"interval_index": 1, "actual_mw": 7.5},
                          {"interval_index": 2, "actual_mw": 7.5}], g_v, p_id)
        close_real_time(d_id, [{"node_name": "WEST_HUB",
                                "rt_prelim_energy_cents_per_mwh": 4000,
                                "rt_prelim_congestion_cents_per_mwh": 35,
                                "rt_prelim_loss_cents_per_mwh": 15}])
        run_prelim_settlement(d_id)
        s = get_statement_by_day_and_type(d_id, p_id, "PRELIMINARY")
        # per-interval pinned order: congestion 55876, loss 27376
        assert s["congestion_charge_cents"] == 55876
        assert s["loss_charge_cents"] == 27376
        assert_statement_net_invariant(s)

    def test_capacity_stop_loss_charged_is_min_of_accrued_and_cap(self, api):
        """PRD §3.6: "Third, `charged_penalty_cents` is the smaller of
        `accrued_penalty_cents` and the cap".

        Design: Difficulty/combinatorial_formula/capacity_stop_loss_evaluation_order
        """
        set_clock("2026-08-01T00:00:00Z")
        p_id, g_id, g_v = setup_participant_generator(company="Cap2 Co")
        _, ob_id = create_obligation(g_id, obligated_mw=10, capacity_rate=1000)
        _, d_id, _ = create_operating_day(market_date="2026-08-10",
                                          gate_close="2026-08-09T10:30:00Z")
        run_da_market(d_id, [])
        submit_telemetry(g_id, d_id, [{"interval_index": 1, "actual_mw": 6},
                                      {"interval_index": 2, "actual_mw": 6}], g_v, p_id)
        ev = get_success_data(api.create_performance_event(d_id, {"start_interval": 1, "end_interval": 2}, ISO))
        api.activate_event(ev["id"], ISO)
        api.complete_event(ev["id"], ISO)
        api.close_obligation(ob_id, ISO)
        ob = get_success_data(api.get_obligation(ob_id, ISO))
        # accrued 400000, cap 15000 -> charged min = 15000, forgiven 385000
        assert ob["charged_penalty_cents"] == min(400000, 15000)
        assert ob["forgiven_penalty_cents"] == 400000 - 15000


class TestNonLinearSecondAngle:
    def test_offer_withdraw_requires_da_open(self, api):
        """PRD §3.2: "withdrawing moves `SUBMITTED` → `DRAFT` while the day
        remains `DA_OPEN` (`ERR_MARKET_NOT_OPEN`)".

        Design: Difficulty/non_linear_state_machine/offer_submit_withdraw_cycle
        """
        p_id, g_id, g_v, d_id, d_v, o_id = setup_day_with_offer()
        submit_offer(o_id, p_id)
        withdraw_offer(o_id, p_id)
        offer = get_success_data(api.get_offer(o_id, make_trader_headers(p_id)))
        assert offer["status"] == "DRAFT"

    def test_dispute_withdraw_returns_statement_to_issued(self, api):
        """PRD §3.7: "The filer may also withdraw a dispute while it is still
        `FILED`, moving it to `WITHDRAWN` and returning the statement from
        `UNDER_DISPUTE` to `ISSUED`."

        Design: Difficulty/non_linear_state_machine/statement_dispute_reinstatement_cycle
        """
        p_id, g_id, d_id, s = setup_final_settled()
        analyst = make_analyst_headers(p_id)
        ln = _first_line(api, s["id"])
        disp = validate_success(api.create_dispute(
            s["id"], {"dispute_reason": "PRICE_ERROR", "disputed_line_ids": [ln["id"]]},
            analyst), expected_status=201)
        api.withdraw_dispute(disp["id"], analyst)
        st = get_success_data(api.get_statement(s["id"], analyst))
        assert st["status"] == "ISSUED"

    def test_outage_resubmit_rechecks_overlap(self, api):
        """PRD §3.4: "The overlap rule is re-evaluated against the generator's
        live reports at resubmission (`ERR_OUTAGE_OVERLAP`)".

        Design: Difficulty/non_linear_state_machine/outage_denied_resubmission_cycle
        """
        set_clock("2026-08-01T00:00:00Z")
        p_id, g_id, _ = setup_participant_generator(company="Out2 Co")
        # blocker outage in APPROVED window
        _, blocker = create_outage(g_id, p_id, outage_type="PARTIAL", derate_pct=10,
                                   start_at="2026-08-05T00:00:00Z", end_at="2026-08-06T00:00:00Z",
                                   reason="blocker")
        api.acknowledge_outage(blocker, ISO)
        api.approve_outage(blocker, ISO)
        # denied report on a separate day
        _, out_id = create_outage(g_id, p_id, outage_type="PARTIAL", derate_pct=40,
                                  start_at="2026-08-07T00:00:00Z", end_at="2026-08-08T00:00:00Z",
                                  reason="to deny")
        api.acknowledge_outage(out_id, ISO)
        api.deny_outage(out_id, {"denial_reason": "x"}, ISO)
        # resubmit moved INTO the blocker's window -> overlap
        resp = api.resubmit_outage(out_id, {
            "start_at": "2026-08-05T12:00:00Z", "end_at": "2026-08-05T18:00:00Z"},
            make_trader_headers(p_id))
        validate_error(resp, ApiErrorId.ERR_OUTAGE_OVERLAP)


class TestTransitiveCascadeSecondAngle:
    def test_outage_approval_sets_availability_zero_for_full(self, api):
        """PRD §2.9: "If any `APPROVED` report of type `FULL` covers the
        current instant, availability is zero and the generator is
        `ON_OUTAGE`."

        Design: Difficulty/transitive_cascade/outage_approval_cascades_to_margin_call
        """
        set_clock("2026-08-05T00:00:00Z")
        p_id, g_id, _ = setup_participant_generator(company="Casc2 Co",
                                                    tier="BELOW_INVESTMENT_GRADE")
        create_obligation(g_id, obligated_mw=10, capacity_rate=1000000)
        _, out_id = create_outage(g_id, p_id, outage_type="FULL", derate_pct=100,
                                  start_at="2026-08-05T00:00:00Z", end_at="2026-08-06T00:00:00Z",
                                  reason="forced")
        api.acknowledge_outage(out_id, ISO)
        api.approve_outage(out_id, ISO)
        gen = get_success_data(api.get_generator(g_id, ISO))
        assert gen["availability_mw"] == 0
        assert gen["status"] == "ON_OUTAGE"

    def test_resettlement_net_reduced_by_disputed_line(self, api):
        """PRD §3.7: "`net_amount_cents` becomes the disputed statement's net
        minus the sum of the disputed lines' amounts".

        Design: Difficulty/transitive_cascade/dispute_upheld_cascades_to_margin_cure
        """
        set_clock("2026-08-05T00:00:00Z")
        _, p_id = create_participant(company_name="Cure2 Co", tier="INVESTMENT_GRADE")
        _, g_id, g_v = create_generator(p_id, unit_name="U1")
        create_obligation(g_id, obligated_mw=10, capacity_rate=1000000)
        _, d_id, _ = create_operating_day(market_date="2026-08-10",
                                          gate_close="2026-08-09T10:30:00Z")
        run_da_market(d_id, [])
        submit_telemetry(g_id, d_id, [{"interval_index": 1, "actual_mw": 6},
                                      {"interval_index": 2, "actual_mw": 6}], g_v, p_id)
        ev = get_success_data(api.create_performance_event(d_id, {"start_interval": 1, "end_interval": 2}, ISO))
        api.activate_event(ev["id"], ISO)
        api.complete_event(ev["id"], ISO)
        close_real_time(d_id, [])
        run_prelim_settlement(d_id)
        run_final_settlement(d_id, [])
        s_fin = get_statement_by_day_and_type(d_id, p_id, "FINAL")
        ln_cap = _first_line(api, s_fin["id"])
        analyst = make_analyst_headers(p_id)
        disp = validate_success(api.create_dispute(
            s_fin["id"], {"dispute_reason": "CALCULATION_ERROR",
                          "disputed_line_ids": [ln_cap["id"]]}, analyst), expected_status=201)
        api.start_review_dispute(disp["id"], ISO)
        api.resolve_dispute(disp["id"], {"outcome": "UPHELD"}, ISO)
        rows, _ = validate_paginated(api.list_statements(ISO, params={
            "market_participant_id": p_id, "run_type": "RESETTLEMENT"}))
        # net reduced by exactly the disputed line amount (400000 -> 0)
        assert rows[0]["net_amount_cents"] == s_fin["net_amount_cents"] - ln_cap["amount_cents"]


class TestPriorityPairSecondAngle:
    def test_generator_not_available_blocks_submit_even_with_headroom(self, api):
        """PRD §3.2: submit requires "the generator is `AVAILABLE`
        (`ERR_GENERATOR_NOT_AVAILABLE`)".

        Design: Difficulty/priority_pair_validation_conflict/generator_outage_state_beats_credit_headroom
        """
        set_clock("2026-08-01T00:00:00Z")
        # INVESTMENT_GRADE with ample collateral: headroom fine, only state fails
        p_id, g_id, _, d_id, d_v, o_id = setup_day_with_offer(tier="INVESTMENT_GRADE")
        create_posting(p_id, amount_cents=10000000, instrument_type="CASH")
        _, out_id = create_outage(g_id, p_id, outage_type="FULL", derate_pct=100,
                                  start_at="2026-08-01T00:00:00Z", end_at="2026-08-02T00:00:00Z",
                                  reason="forced")
        api.acknowledge_outage(out_id, ISO)
        api.approve_outage(out_id, ISO)
        resp = api.submit_offer(o_id, make_trader_headers(p_id))
        validate_error(resp, ApiErrorId.ERR_GENERATOR_NOT_AVAILABLE)

    def test_dispute_foreign_line_rejected_inside_window(self, api):
        """PRD §3.7: "every element must be a line belonging to the disputed
        statement — a line from any other statement is rejected with
        `ERR_LINE_NOT_IN_STATEMENT`."

        Design: Difficulty/priority_pair_validation_conflict/dispute_foreign_line_beats_window_closed
        """
        p_id, g_id, d_id, s_fin = setup_final_settled()
        s_pre = get_statement_by_day_and_type(d_id, p_id, "PRELIMINARY")
        ln_foreign = _first_line(api, s_pre["id"])
        # inside window (clock not advanced)
        resp = api.create_dispute(s_fin["id"], {"dispute_reason": "PRICE_ERROR",
                                                "disputed_line_ids": [ln_foreign["id"]]},
                                  make_analyst_headers(p_id))
        validate_error(resp, ApiErrorId.ERR_LINE_NOT_IN_STATEMENT)


class TestBoundarySecondAngle:
    def test_gate_close_one_second_past_rejected(self, api):
        """PRD §3.2: "only strictly later submissions are turned away."

        Design: Difficulty/boundary_precision_check/da_gate_close_inclusive_boundary
        """
        p_id, g_id, g_v, d_id, d_v, o_id = setup_day_with_offer(
            gate_close="2026-08-02T10:30:00Z", clock="2026-08-02T10:30:01Z")
        resp = api.submit_offer(o_id, make_trader_headers(p_id))
        validate_error(resp, ApiErrorId.ERR_DA_GATE_CLOSED)

    def test_deadband_exact_no_penalty(self, api):
        """PRD §3.5: "A deviation whose absolute size equals the deadband
        exactly carries no penalty portion — the entire deviation settles at
        the hundred-percent rate."

        Design: Difficulty/boundary_precision_check/deviation_deadband_exact_boundary
        """
        set_clock("2026-08-01T00:00:00Z")
        _, p_id = create_participant(company_name="Band2 Co")
        _, g_id, g_v = create_generator(p_id, unit_name="U1", capacity_mw=25)
        _, d_id, d_v = create_operating_day(market_date="2026-08-03")
        _, o_id = create_offer(d_id, g_id, offered_mw=20, offer_price=5000,
                               day_version=d_v, participant_id=p_id)
        submit_offer(o_id, p_id)
        run_da_market(d_id, [{"node_name": "WEST_HUB", "da_energy_cents_per_mwh": 5000,
                              "da_congestion_cents_per_mwh": 0, "da_loss_cents_per_mwh": 0}])
        submit_telemetry(g_id, d_id, uniform_readings_24(19), g_v, p_id)
        close_real_time(d_id, [{"node_name": "WEST_HUB",
                                "rt_prelim_energy_cents_per_mwh": 4000,
                                "rt_prelim_congestion_cents_per_mwh": 0,
                                "rt_prelim_loss_cents_per_mwh": 0}])
        run_prelim_settlement(d_id)
        s = get_statement_by_day_and_type(d_id, p_id, "PRELIMINARY")
        # 24 * 1.0 * 4000 with no penalty multiplier
        assert s["imbalance_charge_cents"] == 96000


class TestCrossEntitySecondAngle:
    def test_offer_create_blocked_after_day_gated(self, api):
        """PRD §3.2: "The day must still be `DA_OPEN` (`ERR_MARKET_NOT_OPEN`)".

        Design: Difficulty/cross_entity_state_dependency/offer_create_requires_day_da_open
        """
        p_id, g_id, _ = setup_participant_generator(company="Dep2b Co")
        _, d_id, d_v = create_operating_day()
        run_da_market(d_id, [])
        day = get_success_data(api.get_operating_day(d_id, ISO))
        assert day["status"] == "DA_GATED"
        resp = api.create_offer(d_id, {
            "generator_asset_id": g_id, "offered_mw": 5, "offer_price_cents_per_mwh": 5000,
            "expected_operating_day_version": day["version"]}, make_trader_headers(p_id))
        validate_error(resp, ApiErrorId.ERR_MARKET_NOT_OPEN)

    def test_dispute_on_preliminary_rejected_even_with_valid_line(self, api):
        """PRD §3.7: "filing against a `PRELIMINARY` statement is rejected with
        `ERR_STATEMENT_NOT_FINAL`."

        Design: Difficulty/cross_entity_state_dependency/dispute_requires_final_run_type
        """
        p_id, g_id, d_id, s_pre = setup_preliminary_settled()
        ln = _first_line(api, s_pre["id"])
        resp = api.create_dispute(s_pre["id"], {"dispute_reason": "PRICE_ERROR",
                                                "disputed_line_ids": [ln["id"]]},
                                  make_analyst_headers(p_id))
        validate_error(resp, ApiErrorId.ERR_STATEMENT_NOT_FINAL)

    def test_posting_release_blocked_regardless_of_amount(self, api):
        """PRD §3.8: "only when the participant has no `OPEN` margin call
        (`ERR_OPEN_MARGIN_CALL`)".

        Design: Difficulty/cross_entity_state_dependency/posting_release_blocked_by_open_margin_call
        """
        set_clock("2026-08-05T00:00:00Z")
        _, p_id = create_participant(company_name="Dep3b Co", tier="BELOW_INVESTMENT_GRADE")
        _, cp_id = create_posting(p_id, amount_cents=100000, instrument_type="CASH")
        _, g_id, _ = create_generator(p_id, unit_name="U1")
        create_obligation(g_id, obligated_mw=10, capacity_rate=1000000)
        _, out_id = create_outage(g_id, p_id, outage_type="FULL", derate_pct=100,
                                  start_at="2026-08-05T00:00:00Z", end_at="2026-08-06T00:00:00Z",
                                  reason="forced")
        api.acknowledge_outage(out_id, ISO)
        api.approve_outage(out_id, ISO)
        assert get_open_margin_call(p_id) is not None
        resp = api.release_posting(cp_id, make_credit_headers(p_id))
        validate_error(resp, ApiErrorId.ERR_OPEN_MARGIN_CALL)


class TestResourceTemporalSecondAngle:
    def test_outage_adjacent_at_start_boundary_accepted(self, api):
        """PRD §2.9: "a report that begins exactly when another ends does not
        overlap it."

        Design: Difficulty/resource_temporal_overlap/outage_half_open_interval_adjacency
        """
        p_id, g_id, _ = setup_participant_generator(company="Ovl2 Co")
        create_outage(g_id, p_id, derate_pct=50,
                      start_at="2026-08-05T10:00:00Z", end_at="2026-08-05T12:00:00Z",
                      reason="first")
        resp = api.create_outage(g_id, {
            "outage_type": "PARTIAL", "derate_pct": 30,
            "start_at": "2026-08-05T12:00:00Z", "end_at": "2026-08-05T14:00:00Z",
            "reason": "adjacent"}, make_trader_headers(p_id))
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "SUBMITTED"

    def test_event_with_two_interval_gap_accepted(self, api):
        """PRD §3.6: "the new event's first interval must be at least two
        greater than the sibling's last interval".

        Design: Difficulty/resource_temporal_overlap/performance_event_buffer_gap_semantics
        """
        _, d_id, _ = create_operating_day(market_date="2026-08-10",
                                          gate_close="2026-08-09T10:30:00Z")
        api.create_performance_event(d_id, {"start_interval": 1, "end_interval": 4}, ISO)
        resp = api.create_performance_event(d_id, {"start_interval": 6, "end_interval": 8}, ISO)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "DECLARED"


class TestCompensatingInvariantSecondAngle:
    def test_post_then_release_restores_zero(self, api):
        """PRD §3.1: "the participant's `posted_collateral_cents` increases by
        `amount_cents`". §3.8: release "reduces the participant's
        `posted_collateral_cents` by the posting's `amount_cents`".

        Design: Difficulty/compensating_invariant/collateral_post_release_conservation
        """
        set_clock("2026-08-01T00:00:00Z")
        _, p_id = create_participant(company_name="Inv2 Co")
        _, cp_id = create_posting(p_id, amount_cents=250000, instrument_type="CASH")
        assert get_success_data(api.get_participant(p_id, ISO))["posted_collateral_cents"] == 250000
        api.release_posting(cp_id, make_credit_headers(p_id))
        assert get_success_data(api.get_participant(p_id, ISO))["posted_collateral_cents"] == 0

    def test_event_with_no_surplus_retains_pool(self, api):
        """PRD §3.6: "If no obligation over-performed, the market operator
        retains the pool and `bonuses_paid_cents` is zero".

        Design: Difficulty/compensating_invariant/penalty_pool_zero_sum_conservation
        """
        set_clock("2026-08-01T00:00:00Z")
        _, p1 = create_participant(company_name="UnderOnly Co")
        _, ga, ga_v = create_generator(p1, unit_name="A1")
        create_obligation(ga, obligated_mw=10, capacity_rate=1000000)
        _, d_id, _ = create_operating_day(market_date="2026-08-10",
                                          gate_close="2026-08-09T10:30:00Z")
        run_da_market(d_id, [])
        submit_telemetry(ga, d_id, [{"interval_index": 1, "actual_mw": 6},
                                    {"interval_index": 2, "actual_mw": 6}], ga_v, p1)
        ev = get_success_data(api.create_performance_event(d_id, {"start_interval": 1, "end_interval": 2}, ISO))
        api.activate_event(ev["id"], ISO)
        api.complete_event(ev["id"], ISO)
        ev_after = get_success_data(api.get_event(ev["id"], ISO))
        assert ev_after["penalties_collected_cents"] == 400000
        assert ev_after["bonuses_paid_cents"] == 0
