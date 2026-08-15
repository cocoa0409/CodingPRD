"""Settlement calculations: imbalance, congestion/loss rounding, line emission."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, make_trader_headers,
)
from test_helpers.fixtures import (
    ISO, set_clock, create_participant, create_generator, create_operating_day,
    create_offer, submit_offer, run_da_market, close_real_time,
    run_prelim_settlement, run_final_settlement, submit_telemetry,
    uniform_readings_24, setup_cleared_offer_day, setup_preliminary_settled,
    setup_final_settled, get_statement_by_day_and_type,
)
from test_helpers.assertions import assert_statement_net_invariant

DA_DECK = [{"node_name": "WEST_HUB", "da_energy_cents_per_mwh": 5000,
            "da_congestion_cents_per_mwh": 200, "da_loss_cents_per_mwh": 100}]
RT_PRELIM = [{"node_name": "WEST_HUB", "rt_prelim_energy_cents_per_mwh": 4000,
              "rt_prelim_congestion_cents_per_mwh": 50, "rt_prelim_loss_cents_per_mwh": 25}]


class TestPreliminaryVsFinalDivergence:
    def test_settlement_preliminary_variant_net(self, api):
        """PRD §2.10: "The preliminary run prices imbalance, congestion, and
        losses off each node's `rt_prelim_energy_cents_per_mwh`,
        `rt_prelim_congestion_cents_per_mwh`, and
        `rt_prelim_loss_cents_per_mwh` components, against the telemetry set as
        it stands at that run."

        Design: Difficulty/dual_variant_calc/settlement_preliminary_vs_final_divergence
        """
        set_clock("2026-08-01T00:00:00Z")
        _, p_id = create_participant(company_name="Alpha Gen Co")
        _, g_id, g_v = create_generator(p_id, unit_name="UNIT-1")
        _, d_id, d_v = create_operating_day(market_date="2026-08-03")
        _, o_id = create_offer(d_id, g_id, offered_mw=10, offer_price=5000,
                               day_version=d_v, participant_id=p_id)
        submit_offer(o_id, p_id)
        run_da_market(d_id, DA_DECK)
        submit_telemetry(g_id, d_id, uniform_readings_24(8), g_v, p_id)
        close_real_time(d_id, RT_PRELIM)
        run_prelim_settlement(d_id)
        s_pre = get_statement_by_day_and_type(d_id, p_id, "PRELIMINARY")
        # imbalance 206400 + congestion 50400 + loss 25200 - da_credit 1200000
        assert s_pre["net_amount_cents"] == -918000
        assert_statement_net_invariant(s_pre)

    def test_settlement_final_variant_diverges_and_supersedes(self, api):
        """PRD §2.10: "The final run re-prices off
        `rt_final_energy_cents_per_mwh`, `rt_final_congestion_cents_per_mwh`,
        and `rt_final_loss_cents_per_mwh` against the full corrected telemetry
        set, so an identical physical day yields different cents whenever final
        prices diverge from preliminary ones." PRD §3.5: "supersedes every
        `PRELIMINARY` statement of the day (`ISSUED` → `SUPERSEDED`)".

        Design: Difficulty/dual_variant_calc/settlement_preliminary_vs_final_divergence
        """
        set_clock("2026-08-01T00:00:00Z")
        _, p_id = create_participant(company_name="Alpha Gen Co")
        _, g_id, g_v = create_generator(p_id, unit_name="UNIT-1")
        _, d_id, d_v = create_operating_day(market_date="2026-08-03")
        _, o_id = create_offer(d_id, g_id, offered_mw=10, offer_price=5000,
                               day_version=d_v, participant_id=p_id)
        submit_offer(o_id, p_id)
        run_da_market(d_id, DA_DECK)
        submit_telemetry(g_id, d_id, uniform_readings_24(8), g_v, p_id)
        close_real_time(d_id, RT_PRELIM)
        run_prelim_settlement(d_id)
        s_pre = get_statement_by_day_and_type(d_id, p_id, "PRELIMINARY")
        run_final_settlement(d_id, [{"node_name": "WEST_HUB",
                                     "rt_final_energy_cents_per_mwh": 6000,
                                     "rt_final_congestion_cents_per_mwh": 150,
                                     "rt_final_loss_cents_per_mwh": 75}])
        s_fin = get_statement_by_day_and_type(d_id, p_id, "FINAL")
        # final variant: 309600 + 55200 + 27600 - 1200000
        assert s_fin["net_amount_cents"] == -807600
        assert_statement_net_invariant(s_fin)
        assert s_fin["net_amount_cents"] - s_pre["net_amount_cents"] == 110400
        pre_after = get_success_data(api.get_statement(s_pre["id"], ISO))
        assert pre_after["status"] == "SUPERSEDED"


class TestCongestionRoundingOrder:
    def test_congestion_per_interval_rounding_order(self, api):
        """PRD §2.6: "Real-time imbalance energy and the congestion/loss
        allocations round every per-interval, per-component amount half up to
        whole cents first, and only then sum across the day's twenty-four
        intervals. Summing first and rounding once is not permitted".

        Design: Difficulty/combinatorial_formula/congestion_per_interval_rounding_order
        """
        set_clock("2026-08-01T00:00:00Z")
        _, p_id = create_participant(company_name="Round Co")
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
        assert s["congestion_charge_cents"] == 55876
        assert s["loss_charge_cents"] == 27376
        assert s["imbalance_charge_cents"] == 985200
        assert s["net_amount_cents"] == -131548
        assert_statement_net_invariant(s)


class TestDeadbandBoundary:
    def test_deviation_deadband_exact_boundary(self, api):
        """PRD §3.5: "A deviation whose absolute size equals the deadband
        exactly carries no penalty portion — the entire deviation settles at
        the hundred-percent rate."

        Design: Difficulty/boundary_precision_check/deviation_deadband_exact_boundary
        """
        set_clock("2026-08-01T00:00:00Z")
        _, p_id = create_participant(company_name="Band Co")
        _, g_id, g_v = create_generator(p_id, unit_name="U1", capacity_mw=25)

        def settle_day(market_date, gate_close, telemetry_mw, gen_version):
            _, d_id, d_v = create_operating_day(market_date=market_date, gate_close=gate_close)
            _, o_id = create_offer(d_id, g_id, offered_mw=20, offer_price=5000,
                                   day_version=d_v, participant_id=p_id)
            submit_offer(o_id, p_id)
            run_da_market(d_id, [{"node_name": "WEST_HUB", "da_energy_cents_per_mwh": 5000,
                                  "da_congestion_cents_per_mwh": 0, "da_loss_cents_per_mwh": 0}])
            submit_telemetry(g_id, d_id, uniform_readings_24(telemetry_mw), gen_version, p_id)
            close_real_time(d_id, [{"node_name": "WEST_HUB",
                                    "rt_prelim_energy_cents_per_mwh": 4000,
                                    "rt_prelim_congestion_cents_per_mwh": 0,
                                    "rt_prelim_loss_cents_per_mwh": 0}])
            run_prelim_settlement(d_id)
            return get_statement_by_day_and_type(d_id, p_id, "PRELIMINARY")

        s1 = settle_day("2026-08-03", "2026-08-02T10:30:00Z", 19, g_v)
        g_v2 = get_success_data(api.get_generator(g_id, ISO))["version"]
        s2 = settle_day("2026-08-04", "2026-08-03T10:30:00Z", 18.9, g_v2)
        assert s1["imbalance_charge_cents"] == 96000
        assert s2["imbalance_charge_cents"] == 106560
        assert s2["imbalance_charge_cents"] - s1["imbalance_charge_cents"] == 10560


class TestTelemetryExcludedWithoutClearedOffer:
    def test_imbalance_excludes_telemetry_without_cleared_offer(self, api):
        """PRD §2.10: "Telemetry alone — a metered generator with no cleared
        offer — produces no statement and is excluded from settlement."

        Design: Corner/calculations/imbalance_excludes_telemetry_without_cleared_offer
        """
        p_id, g_id, g_v = None, None, None
        _, p_id = create_participant(company_name="Iso Co")
        _, g_id, g_v = create_generator(p_id, unit_name="U1")
        _, d_id, _ = create_operating_day()
        run_da_market(d_id, [])
        submit_telemetry(g_id, d_id,
                         [{"interval_index": 1, "actual_mw": 6},
                          {"interval_index": 2, "actual_mw": 6}], g_v, p_id)
        close_real_time(d_id, [])
        run_prelim_settlement(d_id)
        rows, _ = validate_paginated(api.list_statements(ISO, params={
            "operating_day_id": d_id, "market_participant_id": p_id}))
        assert len(rows) == 0


class TestStatementLineEmission:
    def test_statement_line_set_completeness(self, api):
        """PRD §2.10: "one SettlementLine per generator-and-`charge_type`
        combination whose amount is non-zero; zero-amount components emit no
        line, and lines are ordered by `created_at` ascending."

        Design: Corner/endpoints/statement_line_set_completeness
        """
        p_id, g_id, d_id, s = setup_preliminary_settled()
        rows, _ = validate_paginated(api.list_statement_lines(s["id"], ISO))
        assert len(rows) == 3
        by_type = {r["charge_type"]: r["amount_cents"] for r in rows}
        assert by_type["DA_ENERGY_CREDIT"] == -1200000
        assert by_type["CONGESTION"] == 48000
        assert by_type["LOSSES"] == 24000
        assert "RT_IMBALANCE" not in by_type
        assert "ANCILLARY" not in by_type
        assert "CAPACITY" not in by_type
        assert sum(by_type.values()) == s["net_amount_cents"] == -1128000


class TestAncillaryTieredRevenue:
    def test_ancillary_tiered_revenue_with_regulation_branch(self, api):
        """PRD §3.6: "a score of exactly 0.75 lands in the eighty-five-percent
        tier" and "A `REGULATION` award additionally earns a performance
        component of `awarded_mw` times `performance_price_cents` times
        `mileage_ratio` — notably not scaled by the tier multiplier — while
        other service types earn no performance component."

        Design: Difficulty/combinatorial_formula/ancillary_tiered_revenue_with_regulation_branch
        """
        set_clock("2026-08-01T00:00:00Z")
        _, p_id = create_participant(company_name="Anc Co")
        _, g_id, g_v = create_generator(p_id, unit_name="U1")
        _, d_id, _ = create_operating_day(market_date="2026-08-03")
        resp = api.create_award(d_id, {
            "generator_asset_id": g_id, "service_type": "REGULATION", "awarded_mw": 5,
            "capacity_price_cents": 1200, "performance_price_cents": 300,
            "mileage_ratio": 2.0, "start_interval": 1, "end_interval": 4}, ISO)
        aw_r = get_success_data(resp)["id"]
        resp = api.create_award(d_id, {
            "generator_asset_id": g_id, "service_type": "SYNC_RESERVE", "awarded_mw": 5,
            "capacity_price_cents": 1200, "start_interval": 5, "end_interval": 8}, ISO)
        aw_s = get_success_data(resp)["id"]
        run_da_market(d_id, [])
        readings = ([{"interval_index": i, "actual_mw": 5} for i in (1, 2, 3)]
                    + [{"interval_index": 4, "actual_mw": 0}]
                    + [{"interval_index": i, "actual_mw": 5} for i in (5, 6, 7, 8)])
        submit_telemetry(g_id, d_id, readings, g_v, p_id)
        close_real_time(d_id, [])
        run_prelim_settlement(d_id)

        aw_r_after = get_success_data(api.get_award(aw_r, ISO))
        aw_s_after = get_success_data(api.get_award(aw_s, ISO))
        assert aw_r_after["performance_score"] == pytest.approx(0.75)
        assert aw_r_after["revenue_cents"] == 8100
        assert aw_r_after["status"] == "SETTLED"
        assert aw_s_after["revenue_cents"] == 6000
        assert aw_s_after["status"] == "SETTLED"
        s = get_statement_by_day_and_type(d_id, p_id, "PRELIMINARY")
        assert s["ancillary_revenue_cents"] == 14100
