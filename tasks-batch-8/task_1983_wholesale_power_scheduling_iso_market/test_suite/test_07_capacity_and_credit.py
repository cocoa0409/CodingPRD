"""Capacity obligations, performance events, stop-loss close, and credit posture."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, make_trader_headers, make_credit_headers, make_analyst_headers,
)
from test_helpers.fixtures import (
    ISO, set_clock, create_participant, create_generator, create_operating_day,
    create_offer, submit_offer, run_da_market, close_real_time,
    run_prelim_settlement, run_final_settlement, submit_telemetry,
    create_outage, create_obligation, create_posting,
    setup_participant_generator, get_statement_by_day_and_type,
    get_open_margin_call, uniform_readings_24,
)


def _complete_event(api, day_id, start_interval, end_interval):
    resp = api.create_performance_event(day_id, {
        "start_interval": start_interval, "end_interval": end_interval}, ISO)
    ev = get_success_data(resp)
    api.activate_event(ev["id"], ISO)
    api.complete_event(ev["id"], ISO)
    return get_success_data(api.get_event(ev["id"], ISO))


class TestStopLossEvaluationOrder:
    def test_capacity_stop_loss_evaluation_order(self, api):
        """PRD §3.6: "First, `gross_revenue_cents` is computed as
        `obligated_mw` times `capacity_rate_cents_per_mw`, rounded half up to
        whole cents; this happens before any penalty offset and serves as the
        cap basis. Second, the stop-loss cap is one and a half times the gross
        revenue... Third, `charged_penalty_cents` is the smaller of
        `accrued_penalty_cents` and the cap... Fourth, `forgiven_penalty_cents`
        is the accrual minus the charged amount."

        Design: Difficulty/combinatorial_formula/capacity_stop_loss_evaluation_order
        """
        set_clock("2026-08-01T00:00:00Z")
        p_id, g_id, g_v = setup_participant_generator(company="Cap Co")
        _, ob_id = create_obligation(g_id, obligated_mw=10, capacity_rate=1000)
        _, d_id, _ = create_operating_day(market_date="2026-08-10",
                                          gate_close="2026-08-09T10:30:00Z")
        run_da_market(d_id, [])
        submit_telemetry(g_id, d_id, [{"interval_index": 1, "actual_mw": 6},
                                      {"interval_index": 2, "actual_mw": 6}], g_v, p_id)
        _complete_event(api, d_id, 1, 2)
        ob = get_success_data(api.get_obligation(ob_id, ISO))
        assert ob["accrued_penalty_cents"] == 400000
        api.close_obligation(ob_id, ISO)
        ob = get_success_data(api.get_obligation(ob_id, ISO))
        assert ob["gross_revenue_cents"] == 10000
        assert ob["charged_penalty_cents"] == 15000
        assert ob["forgiven_penalty_cents"] == 385000
        assert ob["status"] == "CLOSED"


class TestStopLossCapInclusive:
    def test_capacity_stop_loss_cap_inclusive_boundary(self, api):
        """PRD §3.6: "`charged_penalty_cents` is the smaller of
        `accrued_penalty_cents` and the cap — an accrual exactly equal to the
        cap is charged in full."

        Design: Corner/calculations/capacity_stop_loss_cap_inclusive_boundary
        """
        set_clock("2026-08-01T00:00:00Z")
        p_id, g_id, g_v = setup_participant_generator(company="CapB Co")
        _, ob_id = create_obligation(g_id, obligated_mw=10, capacity_rate=10000)
        _, d_id, _ = create_operating_day(market_date="2026-08-10",
                                          gate_close="2026-08-09T10:30:00Z")
        run_da_market(d_id, [])
        submit_telemetry(g_id, d_id, [{"interval_index": 1, "actual_mw": 7}], g_v, p_id)
        _complete_event(api, d_id, 1, 1)
        api.close_obligation(ob_id, ISO)
        ob = get_success_data(api.get_obligation(ob_id, ISO))
        assert ob["charged_penalty_cents"] == 150000
        assert ob["forgiven_penalty_cents"] == 0


class TestPenaltyPoolZeroSum:
    def test_penalty_pool_zero_sum_conservation(self, api):
        """PRD §3.6: "The pool is then redistributed to over-performers,
        revenue-neutral." and "otherwise `bonuses_paid_cents` is the sum of
        the bonuses and equals the pool."

        Design: Difficulty/compensating_invariant/penalty_pool_zero_sum_conservation
        """
        set_clock("2026-08-01T00:00:00Z")
        _, p1 = create_participant(company_name="Under Co")
        _, p2 = create_participant(company_name="Over Co")
        _, ga, ga_v = create_generator(p1, unit_name="A1")
        _, gb, gb_v = create_generator(p2, unit_name="B1")
        _, oba = create_obligation(ga, obligated_mw=10, capacity_rate=1000000)
        _, obb = create_obligation(gb, obligated_mw=5, capacity_rate=1000000)
        _, d_id, _ = create_operating_day(market_date="2026-08-10",
                                          gate_close="2026-08-09T10:30:00Z")
        run_da_market(d_id, [])
        submit_telemetry(ga, d_id, [{"interval_index": 1, "actual_mw": 6},
                                    {"interval_index": 2, "actual_mw": 6}], ga_v, p1)
        submit_telemetry(gb, d_id, [{"interval_index": 1, "actual_mw": 8},
                                    {"interval_index": 2, "actual_mw": 8}], gb_v, p2)
        ev = _complete_event(api, d_id, 1, 2)
        assert ev["penalties_collected_cents"] == 400000
        assert ev["bonuses_paid_cents"] == 400000
        assert ev["penalties_collected_cents"] - ev["bonuses_paid_cents"] == 0
        assert ev["status"] == "COMPLETED"
        oba_after = get_success_data(api.get_obligation(oba, ISO))
        obb_after = get_success_data(api.get_obligation(obb, ISO))
        assert oba_after["accrued_penalty_cents"] == 400000
        assert oba_after["accrued_bonus_cents"] == 0
        assert obb_after["accrued_penalty_cents"] == 0
        assert obb_after["accrued_bonus_cents"] == 400000


class TestCollateralRequirementTiers:
    def test_collateral_requirement_gross_vs_net_tiers(self, api):
        """PRD §2.8: "A `BELOW_INVESTMENT_GRADE` participant is charged on gross
        exposure: the requirement is the sum of the absolute values of the
        per-statement remainders... An `INVESTMENT_GRADE` participant is charged
        on net exposure: the signed statement remainders are summed across days
        and floored at zero, then offer and capacity risk are added".

        Design: Difficulty/dual_variant_calc/collateral_requirement_gross_vs_net_tiers
        """
        set_clock("2026-08-01T00:00:00Z")
        _, p1 = create_participant(company_name="Ig Co", tier="INVESTMENT_GRADE")
        _, p2 = create_participant(company_name="Big Co", tier="BELOW_INVESTMENT_GRADE")
        _, ga, ga_v = create_generator(p1, unit_name="A1")
        _, gb, gb_v = create_generator(p2, unit_name="B1")
        create_obligation(ga, obligated_mw=10, capacity_rate=1000000)
        create_obligation(gb, obligated_mw=10, capacity_rate=1000000)

        # Day 1: capacity event penalties (+400000 each)
        _, d1, _ = create_operating_day(market_date="2026-08-10", gate_close="2026-08-09T10:30:00Z")
        run_da_market(d1, [])
        submit_telemetry(ga, d1, [{"interval_index": 1, "actual_mw": 6},
                                  {"interval_index": 2, "actual_mw": 6}], ga_v, p1)
        submit_telemetry(gb, d1, [{"interval_index": 1, "actual_mw": 6},
                                  {"interval_index": 2, "actual_mw": 6}], gb_v, p2)
        _complete_event(api, d1, 1, 2)
        close_real_time(d1, [])
        run_prelim_settlement(d1)
        run_final_settlement(d1, [])

        # Day 2: REGULATION award fully delivered (-9000 each)
        _, d2, _ = create_operating_day(market_date="2026-08-11", gate_close="2026-08-10T10:30:00Z")
        for g in (ga, gb):
            api.create_award(d2, {
                "generator_asset_id": g, "service_type": "REGULATION", "awarded_mw": 5,
                "capacity_price_cents": 1200, "performance_price_cents": 300,
                "mileage_ratio": 2.0, "start_interval": 1, "end_interval": 4}, ISO)
        run_da_market(d2, [])
        ga_v2 = get_success_data(api.get_generator(ga, ISO))["version"]
        gb_v2 = get_success_data(api.get_generator(gb, ISO))["version"]
        submit_telemetry(ga, d2, [{"interval_index": i, "actual_mw": 5} for i in range(1, 5)], ga_v2, p1)
        submit_telemetry(gb, d2, [{"interval_index": i, "actual_mw": 5} for i in range(1, 5)], gb_v2, p2)
        close_real_time(d2, [])
        run_prelim_settlement(d2)
        run_final_settlement(d2, [])

        r1 = get_success_data(api.evaluate_credit(p1, ISO))
        r2 = get_success_data(api.evaluate_credit(p2, ISO))
        assert r1["collateral_requirement_cents"] == 391000
        assert r2["collateral_requirement_cents"] == 409000
        assert r1["unsecured_allowance_cents"] == 100000
        assert r2["unsecured_allowance_cents"] == 0


class TestObligationDuplicatePeriod:
    def test_obligation_duplicate_period_rejected(self, api):
        """PRD §3.1: "At most one obligation in `ACTIVE` or `AT_RISK` may exist
        for a given generator and delivery period; a second open obligation for
        the same pair is rejected with `ERR_OBLIGATION_DUPLICATE_PERIOD`."

        Design: Corner/validations/obligation_duplicate_period_rejected
        """
        p_id, g_id, _ = setup_participant_generator(company="Dup Co")
        create_obligation(g_id, obligated_mw=10, capacity_rate=1000000)
        resp = api.create_obligation({
            "generator_asset_id": g_id, "delivery_period": "2026-08",
            "obligated_mw": 5, "capacity_rate_cents_per_mw": 900000}, ISO)
        validate_error(resp, ApiErrorId.ERR_OBLIGATION_DUPLICATE_PERIOD)


class TestEventBufferGap:
    def test_performance_event_buffer_gap_semantics(self, api):
        """PRD §3.6: "the new event's first interval must be at least two
        greater than the sibling's last interval, or the sibling's first
        interval at least two greater than the new event's last interval — one
        full gap hour is mandatory, and direct adjacency (one event ending at
        hour h, the next beginning at hour h+1) is a violation rejected with
        `ERR_EVENT_BUFFER_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/performance_event_buffer_gap_semantics
        """
        _, d_id, _ = create_operating_day(market_date="2026-08-10",
                                          gate_close="2026-08-09T10:30:00Z")
        resp = api.create_performance_event(d_id, {"start_interval": 1, "end_interval": 4}, ISO)
        ev1 = get_success_data(resp)["id"]
        # adjacent [5,6] rejected
        resp = api.create_performance_event(d_id, {"start_interval": 5, "end_interval": 6}, ISO)
        validate_error(resp, ApiErrorId.ERR_EVENT_BUFFER_VIOLATION)
        # [6,8] accepted
        resp = api.create_performance_event(d_id, {"start_interval": 6, "end_interval": 8}, ISO)
        ev3 = validate_success(resp, expected_status=201)
        assert ev3["status"] == "DECLARED"
        rows, _ = validate_paginated(api.list_events(ISO, params={"operating_day_id": d_id}))
        assert [r["id"] for r in rows] == [ev1, ev3["id"]]
