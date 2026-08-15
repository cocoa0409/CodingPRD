"""Day-ahead offer lifecycle, gate boundary, OCC, and clearing."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, make_trader_headers, make_iso_headers,
)
from test_helpers.fixtures import (
    ISO, create_participant, create_generator, create_operating_day,
    create_offer, submit_offer, withdraw_offer, run_da_market,
    setup_day_with_offer, setup_participant_generator, set_clock,
    get_generator_version,
)


class TestOfferSubmitWithdrawCycle:
    def test_offer_submit_withdraw_cycle_terminates_in_clearing(self, api):
        """PRD §3.2: "The submit-and-withdraw cycle may repeat any number of
        times while the day stays open; `CLEARED`, `NOT_CLEARED`, `EXPIRED`,
        and `SUPERSEDED` are all terminal."

        Design: Difficulty/non_linear_state_machine/offer_submit_withdraw_cycle
        """
        p_id, g_id, g_v, d_id, d_v, o_id = setup_day_with_offer()
        offer = get_success_data(api.get_offer(o_id, make_trader_headers(p_id)))
        assert offer["status"] == "DRAFT"

        submit_offer(o_id, p_id)
        offer = get_success_data(api.get_offer(o_id, make_trader_headers(p_id)))
        assert offer["status"] == "SUBMITTED"

        withdraw_offer(o_id, p_id)
        offer = get_success_data(api.get_offer(o_id, make_trader_headers(p_id)))
        assert offer["status"] == "DRAFT"

        submit_offer(o_id, p_id)
        offer = get_success_data(api.get_offer(o_id, make_trader_headers(p_id)))
        assert offer["status"] == "SUBMITTED"

        run_da_market(d_id, [{"node_name": "WEST_HUB", "da_energy_cents_per_mwh": 5000,
                              "da_congestion_cents_per_mwh": 200, "da_loss_cents_per_mwh": 100}])
        offer = get_success_data(api.get_offer(o_id, make_trader_headers(p_id)))
        assert offer["status"] == "CLEARED"
        assert offer["cleared_mw"] == 10

    def test_offer_create_initial_state_is_draft(self, api):
        """PRD §3.2: "The new offer itself starts `DRAFT`."

        Design: Difficulty/non_linear_state_machine/offer_submit_withdraw_cycle
        """
        _, _, _, _, _, o_id = setup_day_with_offer()
        # creation response is the DRAFT state
        p_id = None  # not needed for assertion below
        # re-read via any role
        resp = api.get_offer(o_id, ISO)
        assert get_success_data(resp)["status"] == "DRAFT"


class TestDaGateCloseBoundary:
    def test_da_gate_close_inclusive_boundary(self, api):
        """PRD §3.2: "The gate instant is inclusive: submissions timestamped at
        exactly `da_gate_close_at` are accepted, and only strictly later
        submissions are turned away."

        Design: Difficulty/boundary_precision_check/da_gate_close_inclusive_boundary
        """
        p_id, g_id, g_v, d_id, d_v, o_id = setup_day_with_offer(
            gate_close="2026-08-02T10:30:00Z", clock="2026-08-02T10:30:00Z")
        # submit at exactly the gate
        submit_offer(o_id, p_id)
        offer = get_success_data(api.get_offer(o_id, make_trader_headers(p_id)))
        assert offer["status"] == "SUBMITTED"
        withdraw_offer(o_id, p_id)
        # one second past
        set_clock("2026-08-02T10:30:01Z")
        resp = api.submit_offer(o_id, make_trader_headers(p_id))
        validate_error(resp, ApiErrorId.ERR_DA_GATE_CLOSED)
        offer = get_success_data(api.get_offer(o_id, make_trader_headers(p_id)))
        assert offer["status"] == "DRAFT"


class TestOfferCreateRequiresDaOpen:
    def test_offer_create_requires_day_da_open(self, api):
        """PRD §3.2: "The day must still be `DA_OPEN` (`ERR_MARKET_NOT_OPEN`)"
        for offer creation.

        Design: Difficulty/cross_entity_state_dependency/offer_create_requires_day_da_open
        """
        p_id, g_id, _ = setup_participant_generator(company="Dep Co")
        _, d_id, d_v = create_operating_day()
        run_da_market(d_id, [])  # gates the day with an empty deck
        day = get_success_data(api.get_operating_day(d_id, ISO))
        d_v2 = day["version"]
        resp = api.create_offer(d_id, {
            "generator_asset_id": g_id, "offered_mw": 5,
            "offer_price_cents_per_mwh": 5000, "expected_operating_day_version": d_v2,
        }, make_trader_headers(p_id))
        validate_error(resp, ApiErrorId.ERR_MARKET_NOT_OPEN)
        offers, _ = __import__("test_helpers").validate_paginated(
            api.list_offers(ISO, params={"generator_asset_id": g_id}))
        assert len(offers) == 0


class TestOccOfferCreate:
    def test_occ_offer_create_stale_version_then_supersede(self, api):
        """PRD §2.7: "A mismatch with the day's current `version` is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_offer_create_stale_version_then_supersede
        """
        p_id, g_id, _ = setup_participant_generator(company="Occ Co")
        set_clock("2026-08-01T00:00:00Z")
        _, d_id, d_v = create_operating_day()
        _, o1 = create_offer(d_id, g_id, offered_mw=5, offer_price=5000,
                             day_version=d_v, participant_id=p_id)
        # stale version now
        resp = api.create_offer(d_id, {
            "generator_asset_id": g_id, "offered_mw": 7, "offer_price_cents_per_mwh": 4800,
            "expected_operating_day_version": d_v,
        }, make_trader_headers(p_id))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        # refreshed version succeeds and supersedes o1
        day = get_success_data(api.get_operating_day(d_id, ISO))
        resp2 = api.create_offer(d_id, {
            "generator_asset_id": g_id, "offered_mw": 7, "offer_price_cents_per_mwh": 4800,
            "expected_operating_day_version": day["version"],
        }, make_trader_headers(p_id))
        o2 = validate_success(resp2, expected_status=201)
        assert o2["status"] == "DRAFT"
        o1_after = get_success_data(api.get_offer(o1, make_trader_headers(p_id)))
        assert o1_after["status"] == "SUPERSEDED"


class TestOfferExpireTerminal:
    def test_offer_submit_after_expire_rejected(self, api):
        """PRD §3.3: "Every offer still `DRAFT` at this point moves to
        `EXPIRED`." PRD §3.2: "`CLEARED`, `NOT_CLEARED`, `EXPIRED`, and
        `SUPERSEDED` are all terminal."

        Design: Corner/state_machines/offer_submit_after_expire_rejected
        """
        p_id, g_id, g_v, d_id, d_v, o_id = setup_day_with_offer()
        run_da_market(d_id, [])  # DRAFT expires
        resp = api.submit_offer(o_id, make_trader_headers(p_id))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        offer = get_success_data(api.get_offer(o_id, make_trader_headers(p_id)))
        assert offer["status"] == "EXPIRED"


class TestDaClearingEquality:
    def test_da_clearing_price_equality_clears(self, api):
        """PRD §3.3: "An offer whose `offer_price_cents_per_mwh` is at or below
        this price clears — equality clears — moving to `CLEARED` with
        `cleared_mw` set to the full `offered_mw` ... An offer priced strictly
        above it moves to `NOT_CLEARED` with `cleared_mw` zero."

        Design: Corner/calculations/da_clearing_price_equality_clears
        """
        _, p_id = create_participant(company_name="Eq Co")
        _, g1, _ = create_generator(p_id, unit_name="U1")
        _, g2, _ = create_generator(p_id, unit_name="U2")
        _, d_id, d_v = create_operating_day()
        _, o1 = create_offer(d_id, g1, offered_mw=5, offer_price=5300,
                             day_version=d_v, participant_id=p_id)
        submit_offer(o1, p_id)
        d_v2 = get_success_data(api.get_operating_day(d_id, ISO))["version"]
        _, o2 = create_offer(d_id, g2, offered_mw=5, offer_price=5301,
                             day_version=d_v2, participant_id=p_id)
        submit_offer(o2, p_id)
        run_da_market(d_id, [{"node_name": "WEST_HUB", "da_energy_cents_per_mwh": 5000,
                              "da_congestion_cents_per_mwh": 200, "da_loss_cents_per_mwh": 100}])
        o1_after = get_success_data(api.get_offer(o1, make_trader_headers(p_id)))
        o2_after = get_success_data(api.get_offer(o2, make_trader_headers(p_id)))
        assert o1_after["status"] == "CLEARED"
        assert o1_after["cleared_mw"] == 5
        assert o2_after["status"] == "NOT_CLEARED"
        assert o2_after["cleared_mw"] == 0


class TestPriceDeckCompleteness:
    def test_da_run_deck_incomplete_rejected(self, api):
        """PRD §3.3: "The deck must cover the `pricing_node` of every
        `SUBMITTED` offer on the day; if any submitted offer's node is missing,
        the run is rejected with `ERR_PRICE_DECK_INCOMPLETE`."

        Design: Corner/validations/da_run_deck_incomplete_rejected
        """
        p_id, g_id, _ = setup_participant_generator(company="Deck Co", node="EAST_HUB")
        _, d_id, d_v = create_operating_day()
        _, o_id = create_offer(d_id, g_id, offered_mw=10, offer_price=5000,
                               day_version=d_v, participant_id=p_id)
        submit_offer(o_id, p_id)
        resp = api.run_day_ahead_market(d_id, {"node_prices": [
            {"node_name": "WEST_HUB", "da_energy_cents_per_mwh": 5000,
             "da_congestion_cents_per_mwh": 200, "da_loss_cents_per_mwh": 100}]}, ISO)
        validate_error(resp, ApiErrorId.ERR_PRICE_DECK_INCOMPLETE)
        day = get_success_data(api.get_operating_day(d_id, ISO))
        assert day["status"] == "DA_OPEN"
        offer = get_success_data(api.get_offer(o_id, make_trader_headers(p_id)))
        assert offer["status"] == "SUBMITTED"


class TestPriceNodesListed:
    def test_price_nodes_listed_under_day(self, api):
        """PRD §3.3: "On success, one PriceNode row per deck entry is created
        under the day (each `node_name` unique within the day)".

        Design: Corner/entities/price_nodes_listed_under_day
        """
        _, d_id, _ = create_operating_day()
        run_da_market(d_id, [
            {"node_name": "WEST_HUB", "da_energy_cents_per_mwh": 5000,
             "da_congestion_cents_per_mwh": 200, "da_loss_cents_per_mwh": 100},
            {"node_name": "EAST_HUB", "da_energy_cents_per_mwh": 5100,
             "da_congestion_cents_per_mwh": 50, "da_loss_cents_per_mwh": 60},
        ])
        nodes, _ = __import__("test_helpers").validate_paginated(api.list_price_nodes(d_id, ISO))
        names = [n["node_name"] for n in nodes]
        assert "WEST_HUB" in names and "EAST_HUB" in names
        assert len(nodes) == 2
