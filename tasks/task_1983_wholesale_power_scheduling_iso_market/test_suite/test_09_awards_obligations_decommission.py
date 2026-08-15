"""Ancillary awards, obligation recovery via outage cancel, decommission gating,
and credit-headroom / availability offer gates."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, make_trader_headers, make_credit_headers,
)
from test_helpers.fixtures import (
    ISO, set_clock, create_participant, create_generator, create_operating_day,
    create_offer, submit_offer, run_da_market, close_real_time,
    run_prelim_settlement, create_outage, create_obligation,
    setup_participant_generator, setup_day_with_offer, get_open_margin_call,
)


class TestAwardCancelledZeroRevenue:
    def test_award_cancelled_before_settlement_gets_zero_revenue(self, api):
        """PRD §3.6: "A cancelled award moves `AWARDED` → `CANCELLED`
        (terminal), keeps `revenue_cents` at zero, and is excluded from the
        settlement input set."

        Design: Corner/state_machines/award_cancelled_before_settlement_gets_zero_revenue
        """
        _, p_id = create_participant(company_name="AwC Co")
        _, g_id, _ = create_generator(p_id, unit_name="U1")
        _, d_id, _ = create_operating_day()
        resp = api.create_award(d_id, {
            "generator_asset_id": g_id, "service_type": "SYNC_RESERVE", "awarded_mw": 5,
            "capacity_price_cents": 1200, "start_interval": 1, "end_interval": 4}, ISO)
        aw_id = get_success_data(resp)["id"]
        api.cancel_award(aw_id, ISO)
        run_da_market(d_id, [])
        close_real_time(d_id, [])
        run_prelim_settlement(d_id)
        aw = get_success_data(api.get_award(aw_id, ISO))
        assert aw["status"] == "CANCELLED"
        assert aw["revenue_cents"] == 0
        rows, _ = validate_paginated(api.list_statements(ISO, params={
            "operating_day_id": d_id, "market_participant_id": p_id}))
        assert len(rows) == 0


class TestAwardRegulationMissingFields:
    def test_award_regulation_missing_performance_fields_rejected(self, api):
        """PRD §3.6: "`REGULATION` awards additionally require
        `performance_price_cents` and a `mileage_ratio`; omitting either for a
        regulation award is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/validations/award_regulation_missing_performance_fields_rejected
        """
        _, p_id = create_participant(company_name="Awr Co")
        _, g_id, _ = create_generator(p_id, unit_name="U1")
        _, d_id, _ = create_operating_day()
        resp = api.create_award(d_id, {
            "generator_asset_id": g_id, "service_type": "REGULATION", "awarded_mw": 5,
            "capacity_price_cents": 1200, "start_interval": 1, "end_interval": 4}, ISO)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestAwardOverlapsOutage:
    def test_award_overlapping_approved_outage_rejected(self, api):
        """PRD §3.6: "the award's closed window must not intersect — at
        interval granularity — any `APPROVED` outage window of the same
        generator on that day (`ERR_AWARD_OVERLAPS_OUTAGE`)."

        Design: Corner/validations/award_overlapping_approved_outage_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        p_id, g_id, _ = setup_participant_generator(company="AwO Co")
        _, out_id = create_outage(g_id, p_id, outage_type="PARTIAL", derate_pct=60,
                                  start_at="2026-08-03T00:00:00Z", end_at="2026-08-04T00:00:00Z",
                                  reason="planned")
        api.acknowledge_outage(out_id, ISO)
        api.approve_outage(out_id, ISO)
        _, d_id, _ = create_operating_day(market_date="2026-08-03")
        resp = api.create_award(d_id, {
            "generator_asset_id": g_id, "service_type": "SYNC_RESERVE", "awarded_mw": 4,
            "capacity_price_cents": 1200, "start_interval": 1, "end_interval": 4}, ISO)
        validate_error(resp, ApiErrorId.ERR_AWARD_OVERLAPS_OUTAGE)


class TestObligationRecoveryOnOutageCancel:
    def test_obligation_recovers_when_outage_cancelled(self, api):
        """PRD §3.4: "Cancelling an `APPROVED` report compensates the approval
        cascade: availability is recomputed without that outage, obligations
        whose expected output is restored to the obligated MW return from
        `AT_RISK` to `ACTIVE`, the capacity risk adder is removed from the
        requirement, and credit posture is re-evaluated — which may cure an
        open margin call."

        Design: Corner/state_machines/obligation_recovers_when_outage_cancelled
        """
        set_clock("2026-08-05T00:00:00Z")
        p_id, g_id, _ = setup_participant_generator(company="Rec Co")
        _, ob_id = create_obligation(g_id, obligated_mw=10, capacity_rate=1000000)
        _, out_id = create_outage(g_id, p_id, outage_type="PARTIAL", derate_pct=50,
                                  start_at="2026-08-05T00:00:00Z", end_at="2026-08-06T00:00:00Z",
                                  reason="derate")
        api.acknowledge_outage(out_id, ISO)
        api.approve_outage(out_id, ISO)
        ob1 = get_success_data(api.get_obligation(ob_id, ISO))
        assert ob1["status"] == "AT_RISK"
        assert ob1["expected_output_mw"] == 5
        mc = get_open_margin_call(p_id)
        assert mc is not None
        api.cancel_outage(out_id, make_trader_headers(p_id))
        gen = get_success_data(api.get_generator(g_id, ISO))
        assert gen["availability_mw"] == 10
        assert gen["status"] == "AVAILABLE"
        ob2 = get_success_data(api.get_obligation(ob_id, ISO))
        assert ob2["status"] == "ACTIVE"
        mc_after = get_success_data(api.get_margin_call(mc["id"], ISO))
        assert mc_after["status"] == "CURED"
        p = get_success_data(api.get_participant(p_id, ISO))
        assert p["status"] == "ACTIVE"
        assert p["collateral_requirement_cents"] == 0


class TestGeneratorDecommission:
    def test_generator_decommission_blocked_then_succeeds(self, api):
        """PRD §3.1: "A `Trader` may retire a generator by decommissioning it,
        but only while the unit is `AVAILABLE` and carries no open commitments:
        no day-ahead offer in `DRAFT` or `SUBMITTED` ... Any one of these
        rejects the decommission with `ERR_GENERATOR_HAS_OPEN_COMMITMENTS`."

        Design: Corner/state_machines/generator_decommission_blocked_then_succeeds
        """
        p_id, g_id, g_v, d_id, d_v, o_id = setup_day_with_offer(
            offered_mw=5, clock="2026-08-01T00:00:00Z")
        # blocked while DRAFT offer exists
        resp = api.decommission_generator(g_id, make_trader_headers(p_id))
        validate_error(resp, ApiErrorId.ERR_GENERATOR_HAS_OPEN_COMMITMENTS)
        # DA run expires the DRAFT offer
        run_da_market(d_id, [])
        resp = api.decommission_generator(g_id, make_trader_headers(p_id))
        g = validate_success(resp)
        assert g["status"] == "DECOMMISSIONED"
        # offer create on DECOMMISSIONED generator fails the state gate
        _, d2, d2_v = create_operating_day(market_date="2026-08-04",
                                           gate_close="2026-08-03T10:30:00Z")
        resp = api.create_offer(d2, {
            "generator_asset_id": g_id, "offered_mw": 5, "offer_price_cents_per_mwh": 5000,
            "expected_operating_day_version": d2_v}, make_trader_headers(p_id))
        validate_error(resp, ApiErrorId.ERR_GENERATOR_NOT_AVAILABLE)


class TestPriorityStateBeatsFiscal:
    def test_generator_outage_state_beats_credit_headroom(self, api):
        """PRD §2.11: item 8 "Cross-entity state preconditions: market epoch,
        generator availability, participant suspension ..." is evaluated
        before item 12 "Fiscal credit gates — `ERR_CREDIT_HEADROOM_EXCEEDED`
        and `ERR_COLLATERAL_SHORTFALL`."

        Design: Difficulty/priority_pair_validation_conflict/generator_outage_state_beats_credit_headroom
        """
        set_clock("2026-08-01T00:00:00Z")
        p_id, g_id, _, d_id, d_v, o_id = setup_day_with_offer(
            tier="BELOW_INVESTMENT_GRADE")
        _, out_id = create_outage(g_id, p_id, outage_type="FULL", derate_pct=100,
                                  start_at="2026-08-01T00:00:00Z", end_at="2026-08-02T00:00:00Z",
                                  reason="forced")
        api.acknowledge_outage(out_id, ISO)
        api.approve_outage(out_id, ISO)
        resp = api.submit_offer(o_id, make_trader_headers(p_id))
        validate_error(resp, ApiErrorId.ERR_GENERATOR_NOT_AVAILABLE)
        offer = get_success_data(api.get_offer(o_id, make_trader_headers(p_id)))
        assert offer["status"] == "DRAFT"


class TestCreditHeadroomPure:
    def test_credit_headroom_pure_rejected(self, api):
        """PRD §3.2: "the participant's effective requirement including this
        offer's own risk stays within `posted_collateral_cents`
        (`ERR_CREDIT_HEADROOM_EXCEEDED`)"."

        Design: Corner/validations/credit_headroom_pure_rejected
        """
        p_id, g_id, _, d_id, d_v, o_id = setup_day_with_offer(
            tier="BELOW_INVESTMENT_GRADE", clock="2026-08-01T00:00:00Z")
        resp = api.submit_offer(o_id, make_trader_headers(p_id))
        validate_error(resp, ApiErrorId.ERR_CREDIT_HEADROOM_EXCEEDED)
        offer = get_success_data(api.get_offer(o_id, make_trader_headers(p_id)))
        assert offer["status"] == "DRAFT"


class TestOfferExceedsDeratedAvailability:
    def test_offer_exceeds_derated_availability_rejected(self, api):
        """PRD §3.2: "the `offered_mw` does not exceed the generator's current
        `availability_mw` (`ERR_OFFER_MW_EXCEEDS_AVAILABILITY`)"."

        Design: Corner/validations/offer_exceeds_derated_availability_rejected
        """
        set_clock("2026-08-05T00:00:00Z")
        p_id, g_id, _ = setup_participant_generator(company="Der Co")
        _, d_id, d_v = create_operating_day(market_date="2026-08-08",
                                            gate_close="2026-08-07T10:30:00Z")
        _, o_id = create_offer(d_id, g_id, offered_mw=10, offer_price=5000,
                               day_version=d_v, participant_id=p_id)
        _, out_id = create_outage(g_id, p_id, outage_type="PARTIAL", derate_pct=50,
                                  start_at="2026-08-05T00:00:00Z", end_at="2026-08-06T00:00:00Z",
                                  reason="derate")
        api.acknowledge_outage(out_id, ISO)
        api.approve_outage(out_id, ISO)
        resp = api.submit_offer(o_id, make_trader_headers(p_id))
        validate_error(resp, ApiErrorId.ERR_OFFER_MW_EXCEEDS_AVAILABILITY)
        gen = get_success_data(api.get_generator(g_id, ISO))
        assert gen["status"] == "AVAILABLE"
        assert gen["availability_mw"] == 5
