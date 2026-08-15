"""Margin calls, collateral conservation, release/draw waterfalls, suspension."""
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
    get_open_margin_call,
)


def _drive_to_margin_call_via_outage(api, p_id, g_id, tier, obligated_mw=10,
                                     rate=1000000, derate=100,
                                     start="2026-08-05T00:00:00Z", end="2026-08-06T00:00:00Z"):
    create_obligation(g_id, obligated_mw=obligated_mw, capacity_rate=rate)
    _, out_id = create_outage(g_id, p_id, outage_type="FULL" if derate == 100 else "PARTIAL",
                              derate_pct=derate, start_at=start, end_at=end, reason="forced")
    api.acknowledge_outage(out_id, ISO)
    api.approve_outage(out_id, ISO)
    return out_id


class TestOutageApprovalCascadeToMarginCall:
    def test_outage_approval_cascades_to_margin_call(self, api):
        """PRD §3.4: "on every transition into `AT_RISK` the participant's
        requirement is recomputed with the capacity risk adder of §2.8 (five
        hundred dollars per obligated MW) and credit posture is evaluated — an
        approval can therefore issue a margin call and move the participant to
        `MARGIN_CALL` with no further action."

        Design: Difficulty/transitive_cascade/outage_approval_cascades_to_margin_call
        """
        set_clock("2026-08-05T00:00:00Z")
        p_id, g_id, _ = setup_participant_generator(company="Casc Co",
                                                    tier="BELOW_INVESTMENT_GRADE")
        _, ob_id = create_obligation(g_id, obligated_mw=10, capacity_rate=1000000)
        ob0 = get_success_data(api.get_obligation(ob_id, ISO))
        assert ob0["status"] == "ACTIVE"
        _, out_id = create_outage(g_id, p_id, outage_type="FULL", derate_pct=100,
                                  start_at="2026-08-05T00:00:00Z", end_at="2026-08-06T00:00:00Z",
                                  reason="forced outage")
        api.acknowledge_outage(out_id, ISO)
        api.approve_outage(out_id, ISO)
        gen = get_success_data(api.get_generator(g_id, ISO))
        assert gen["availability_mw"] == 0
        assert gen["status"] == "ON_OUTAGE"
        ob = get_success_data(api.get_obligation(ob_id, ISO))
        assert ob["expected_output_mw"] == 0
        assert ob["status"] == "AT_RISK"
        p = get_success_data(api.get_participant(p_id, ISO))
        assert p["collateral_requirement_cents"] == 500000
        assert p["status"] == "MARGIN_CALL"
        mc = get_open_margin_call(p_id)
        assert mc is not None
        assert mc["required_additional_cents"] == 500000
        assert mc["status"] == "OPEN"


class TestMarginCallDefaultDeadline:
    def test_margin_call_defaults_after_cure_deadline(self, api):
        """PRD §2.8: "If an `OPEN` call's `due_at` is strictly in the past and
        posted collateral is still short of the effective requirement, that
        call becomes `DEFAULTED` and the participant moves to `SUSPENDED`; a
        cure landing at exactly `due_at` is accepted, and only a strictly later
        instant defaults."

        Design: Corner/state_machines/margin_call_defaults_after_cure_deadline
        """
        set_clock("2026-08-05T00:00:00Z")
        p_id, g_id, _ = setup_participant_generator(company="Def Co",
                                                    tier="BELOW_INVESTMENT_GRADE")
        _drive_to_margin_call_via_outage(api, p_id, g_id, "BELOW_INVESTMENT_GRADE",
                                         start="2026-08-05T00:00:00Z", end="2026-08-07T00:00:00Z")
        mc = get_open_margin_call(p_id)
        assert mc is not None
        # at exactly due_at the call is still OPEN
        set_clock("2026-08-06T00:00:00Z")
        r1 = get_success_data(api.evaluate_credit(p_id, ISO))
        assert r1["status"] == "MARGIN_CALL"
        mc1 = get_success_data(api.get_margin_call(mc["id"], ISO))
        assert mc1["status"] == "OPEN"
        # one second past
        set_clock("2026-08-06T00:00:01Z")
        r2 = get_success_data(api.evaluate_credit(p_id, ISO))
        assert r2["status"] == "SUSPENDED"
        mc2 = get_success_data(api.get_margin_call(mc["id"], ISO))
        assert mc2["status"] == "DEFAULTED"


class TestOfferSubmitBlockedWhenSuspended:
    def test_offer_submit_blocked_when_participant_suspended(self, api):
        """PRD §3.8: "Suspended participants cannot submit offers
        (`ERR_PARTICIPANT_SUSPENDED`)".

        Design: Corner/state_machines/offer_submit_blocked_when_participant_suspended
        """
        set_clock("2026-08-05T00:00:00Z")
        p_id, g_id, _ = setup_participant_generator(company="Susp Co",
                                                    tier="BELOW_INVESTMENT_GRADE")
        _, d_id, d_v = create_operating_day(market_date="2026-08-08",
                                            gate_close="2026-08-07T10:30:00Z")
        _, o_id = create_offer(d_id, g_id, offered_mw=5, offer_price=5000,
                               day_version=d_v, participant_id=p_id)
        out_id = _drive_to_margin_call_via_outage(api, p_id, g_id, "BELOW_INVESTMENT_GRADE",
                                                  end="2026-08-07T00:00:00Z")
        set_clock("2026-08-06T00:00:01Z")
        api.evaluate_credit(p_id, ISO)
        # cancel the outage so the generator is AVAILABLE again
        api.cancel_outage(out_id, make_trader_headers(p_id))
        p = get_success_data(api.get_participant(p_id, ISO))
        assert p["status"] == "SUSPENDED"
        resp = api.submit_offer(o_id, make_trader_headers(p_id))
        validate_error(resp, ApiErrorId.ERR_PARTICIPANT_SUSPENDED)
        offer = get_success_data(api.get_offer(o_id, make_trader_headers(p_id)))
        assert offer["status"] == "DRAFT"


class TestCollateralConservation:
    def test_collateral_post_release_conservation(self, api):
        """PRD §2.8: "A participant's `posted_collateral_cents` is the sum of
        `amount_cents` over its own CollateralPosting rows in `POSTED` status."

        Design: Difficulty/compensating_invariant/collateral_post_release_conservation
        """
        set_clock("2026-08-01T00:00:00Z")
        _, p_id = create_participant(company_name="Inv Co")
        p0 = get_success_data(api.get_participant(p_id, ISO))
        assert p0["posted_collateral_cents"] == 0
        cp, cp_id = create_posting(p_id, amount_cents=250000, instrument_type="CASH")
        assert cp["status"] == "POSTED"
        p1 = get_success_data(api.get_participant(p_id, ISO))
        assert p1["posted_collateral_cents"] == 250000
        api.release_posting(cp_id, make_credit_headers(p_id))
        p2 = get_success_data(api.get_participant(p_id, ISO))
        assert p2["posted_collateral_cents"] == 0
        cp_after = get_success_data(api.get_posting(cp_id, ISO))
        assert cp_after["status"] == "RELEASED"


class TestImmediatePostingVisibility:
    def test_immediate_posting_visibility(self, api):
        """PRD §3.1: "The posting starts `POSTED`, the participant's
        `posted_collateral_cents` increases by `amount_cents`, and credit
        posture is re-evaluated".

        Design: Corner/consistency_model/immediate_posting_visibility
        """
        _, p_id = create_participant(company_name="Imm Co")
        resp = api.create_posting(p_id, {"amount_cents": 75000, "instrument_type": "LETTER_OF_CREDIT"},
                                  make_credit_headers(p_id))
        cp = validate_success(resp, expected_status=201)
        assert cp["status"] == "POSTED"
        p = get_success_data(api.get_participant(p_id, ISO))
        assert p["posted_collateral_cents"] == 75000
        assert p["version"] == 2


class TestReleaseBlockedByOpenCall:
    def test_posting_release_blocked_by_open_margin_call(self, api):
        """PRD §3.8: "A `CreditOfficer` may release a `POSTED` posting back to
        its participant, but only when the participant has no `OPEN` margin
        call (`ERR_OPEN_MARGIN_CALL`)".

        Design: Difficulty/cross_entity_state_dependency/posting_release_blocked_by_open_margin_call
        """
        set_clock("2026-08-05T00:00:00Z")
        _, p_id = create_participant(company_name="Dep3 Co", tier="BELOW_INVESTMENT_GRADE")
        _, cp_id = create_posting(p_id, amount_cents=100000, instrument_type="CASH")
        _, g_id, _ = create_generator(p_id, unit_name="U1")
        _drive_to_margin_call_via_outage(api, p_id, g_id, "BELOW_INVESTMENT_GRADE")
        mc = get_open_margin_call(p_id)
        assert mc is not None
        assert mc["required_additional_cents"] == 400000
        resp = api.release_posting(cp_id, make_credit_headers(p_id))
        validate_error(resp, ApiErrorId.ERR_OPEN_MARGIN_CALL)
        cp = get_success_data(api.get_posting(cp_id, ISO))
        assert cp["status"] == "POSTED"
        p = get_success_data(api.get_participant(p_id, ISO))
        assert p["posted_collateral_cents"] == 100000


class TestReleaseEqualityBoundary:
    def test_collateral_release_exactly_at_requirement_allowed(self, api):
        """PRD §3.8: "the release leaves `posted_collateral_cents` at or above
        the effective requirement — equality is allowed, while a release that
        would leave collateral strictly short is rejected with
        `ERR_COLLATERAL_SHORTFALL`."

        Design: Corner/validations/collateral_release_exactly_at_requirement_allowed
        """
        set_clock("2026-08-01T00:00:00Z")
        _, p_id = create_participant(company_name="Rel Co")
        _, g_id, g_v = create_generator(p_id, unit_name="U1")
        create_obligation(g_id, obligated_mw=10, capacity_rate=1000000)
        _, d_id, _ = create_operating_day(market_date="2026-08-10",
                                          gate_close="2026-08-09T10:30:00Z")
        run_da_market(d_id, [])
        submit_telemetry(g_id, d_id, [{"interval_index": 1, "actual_mw": 6},
                                      {"interval_index": 2, "actual_mw": 6}], g_v, p_id)
        resp = api.create_performance_event(d_id, {"start_interval": 1, "end_interval": 2}, ISO)
        ev_id = get_success_data(resp)["id"]
        api.activate_event(ev_id, ISO)
        api.complete_event(ev_id, ISO)
        close_real_time(d_id, [])
        run_prelim_settlement(d_id)
        run_final_settlement(d_id, [])
        # margin call open: requirement 400000, effective 300000
        _, cp_x = create_posting(p_id, amount_cents=300000, instrument_type="CASH")
        _, cp_y = create_posting(p_id, amount_cents=100000, instrument_type="LETTER_OF_CREDIT")
        # release Y: leaves 300000 == effective 300000 -> allowed
        resp = api.release_posting(cp_y, make_credit_headers(p_id))
        y = validate_success(resp)
        assert y["status"] == "RELEASED"
        p = get_success_data(api.get_participant(p_id, ISO))
        assert p["posted_collateral_cents"] == 300000
        assert p["status"] == "ACTIVE"
        # release X: would leave 0 < 300000 -> shortfall
        resp = api.release_posting(cp_x, make_credit_headers(p_id))
        validate_error(resp, ApiErrorId.ERR_COLLATERAL_SHORTFALL)
        cp = get_success_data(api.get_posting(cp_x, ISO))
        assert cp["status"] == "POSTED"


class TestDrawWithoutDefault:
    def test_draw_without_defaulted_call_rejected(self, api):
        """PRD §3.8: "a draw attempted while the participant has no defaulted
        call is rejected with `ERR_POSTING_NOT_DRAWABLE`."

        Design: Corner/validations/draw_without_defaulted_call_rejected
        """
        _, p_id = create_participant(company_name="Drw Co")
        _, cp_id = create_posting(p_id, amount_cents=50000, instrument_type="CASH")
        resp = api.draw_posting(cp_id, ISO)
        validate_error(resp, ApiErrorId.ERR_POSTING_NOT_DRAWABLE)
        cp = get_success_data(api.get_posting(cp_id, ISO))
        assert cp["status"] == "POSTED"


class TestDrawWaterfall:
    def test_draw_waterfall_pays_oldest_statement_first(self, api):
        """PRD §3.8: "the drawn amount waterfalls across the participant's
        `ISSUED` statements whose `net_amount_cents` exceeds their
        `paid_cents`, oldest first — ordered by `issued_at` ascending, with
        ties broken by `created_at` ascending — raising each statement's
        `paid_cents` until the draw is exhausted." and "A statement with a
        positive net whose `paid_cents` reaches its `net_amount_cents` moves
        `ISSUED` → `PAID`".

        Design: Corner/calculations/draw_waterfall_pays_oldest_statement_first
        """
        set_clock("2026-08-01T00:00:00Z")
        _, p_id = create_participant(company_name="Draw Co", tier="BELOW_INVESTMENT_GRADE")
        _, g_id, g_v = create_generator(p_id, unit_name="U1")
        create_obligation(g_id, obligated_mw=10, capacity_rate=1000000)

        # Day1: event [1,1], actual 5 -> shortfall 5 x 50000 x 1 = 250000
        _, d1, _ = create_operating_day(market_date="2026-08-10", gate_close="2026-08-09T10:30:00Z")
        run_da_market(d1, [])
        submit_telemetry(g_id, d1, [{"interval_index": 1, "actual_mw": 5}], g_v, p_id)
        ev1 = get_success_data(api.create_performance_event(d1, {"start_interval": 1, "end_interval": 1}, ISO))
        api.activate_event(ev1["id"], ISO)
        api.complete_event(ev1["id"], ISO)
        close_real_time(d1, [])
        run_prelim_settlement(d1)
        run_final_settlement(d1, [])

        # Day2: event [1,2], actual 6 -> shortfall 4 x 50000 x 2 = 400000
        _, d2, _ = create_operating_day(market_date="2026-08-11", gate_close="2026-08-10T10:30:00Z")
        run_da_market(d2, [])
        g_v2 = get_success_data(api.get_generator(g_id, ISO))["version"]
        submit_telemetry(g_id, d2, [{"interval_index": 1, "actual_mw": 6},
                                    {"interval_index": 2, "actual_mw": 6}], g_v2, p_id)
        ev2 = get_success_data(api.create_performance_event(d2, {"start_interval": 1, "end_interval": 2}, ISO))
        api.activate_event(ev2["id"], ISO)
        api.complete_event(ev2["id"], ISO)
        close_real_time(d2, [])
        run_prelim_settlement(d2)
        run_final_settlement(d2, [])

        # default the margin call
        set_clock("2026-08-03T00:00:00Z")
        api.evaluate_credit(p_id, ISO)
        rows, _ = validate_paginated(api.list_margin_calls(ISO, params={
            "market_participant_id": p_id, "status": "DEFAULTED"}))
        mc = rows[0] if rows else None
        assert mc is not None
        # advance past due_at: due = issuance + 24h; issuance happened at 2026-08-01 when the first final settled
        set_clock("2026-08-05T00:00:00Z")
        api.evaluate_credit(p_id, ISO)
        p = get_success_data(api.get_participant(p_id, ISO))
        assert p["status"] == "SUSPENDED"

        _, cp_id = create_posting(p_id, amount_cents=600000, instrument_type="CASH")
        api.draw_posting(cp_id, ISO)
        s1 = get_statement_by_day_and_type(d1, p_id, "FINAL")
        s2 = get_statement_by_day_and_type(d2, p_id, "FINAL")
        s1_after = get_success_data(api.get_statement(s1["id"], ISO))
        s2_after = get_success_data(api.get_statement(s2["id"], ISO))
        assert s1_after["status"] == "PAID"
        assert s2_after["paid_cents"] == 350000
        assert s2_after["status"] == "ISSUED"
        p_after = get_success_data(api.get_participant(p_id, ISO))
        assert p_after["posted_collateral_cents"] == 0
        cp_after = get_success_data(api.get_posting(cp_id, ISO))
        assert cp_after["status"] == "DRAWN"


class TestDisputeUpheldCascadesToCure:
    def test_dispute_upheld_cascades_to_margin_cure(self, api):
        """PRD §3.7: "Because the superseded statement leaves the collateral
        requirement input set while the resettlement statement enters it, the
        participant's requirement is recomputed and credit posture
        re-evaluated — an upheld dispute that erases a deficiency cures the
        open margin call and returns the participant from `MARGIN_CALL` to
        `ACTIVE` per §2.8."

        Design: Difficulty/transitive_cascade/dispute_upheld_cascades_to_margin_cure
        """
        set_clock("2026-08-05T00:00:00Z")
        _, p_id = create_participant(company_name="Cure Co", tier="INVESTMENT_GRADE")
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
        rows, _ = validate_paginated(api.list_lines(ISO, params={"settlement_statement_id": s_fin["id"]}))
        ln_cap = rows[0]
        mc = get_open_margin_call(p_id)
        assert mc is not None
        analyst = make_analyst_headers(p_id)
        disp = validate_success(api.create_dispute(
            s_fin["id"], {"dispute_reason": "CALCULATION_ERROR",
                          "disputed_line_ids": [ln_cap["id"]]}, analyst), expected_status=201)
        api.start_review_dispute(disp["id"], ISO)
        api.resolve_dispute(disp["id"], {"outcome": "UPHELD"}, ISO)
        s_old = get_success_data(api.get_statement(s_fin["id"], ISO))
        assert s_old["status"] == "SUPERSEDED"
        rows, _ = validate_paginated(api.list_statements(ISO, params={
            "market_participant_id": p_id, "run_type": "RESETTLEMENT"}))
        s_re = rows[0]
        assert s_re["status"] == "ISSUED"
        assert s_re["supersedes_statement_id"] == s_fin["id"]
        assert s_re["net_amount_cents"] == 0
        mc_after = get_success_data(api.get_margin_call(mc["id"], ISO))
        assert mc_after["status"] == "CURED"
        p_after = get_success_data(api.get_participant(p_id, ISO))
        assert p_after["status"] == "ACTIVE"
        assert p_after["collateral_requirement_cents"] == 0
