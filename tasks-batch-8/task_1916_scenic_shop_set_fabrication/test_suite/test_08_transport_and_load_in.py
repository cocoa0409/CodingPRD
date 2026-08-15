"""Transport plans and load-in: fleet capacity, confirm/cancel transitions,
load-in gate, two-day buffer."""
import pytest

from test_helpers import (
    ENGINEER,
    EST,
    FOREMAN,
    PAINT,
    TC,
    ApiErrorId,
    assert_instant_equals,
    create_transport_plan_payload,
    drive_to_built,
    drive_to_loaded_in,
    get_success_data,
    make_client_pm_headers,
    set_clock,
    setup_accepted_production,
    setup_basic_scenario,
    setup_in_build_production,
    setup_second_package,
    create_rom_bid,
    submit_bid,
    accept_bid,
    validate_error,
    validate_success,
)


class TestFleetCapacity:
    def _setup_two_productions(self, api):
        shop, client, pkg_a = setup_basic_scenario()
        pkg_b = setup_second_package(client["id"], show_title="Macbeth",
                                     load_in_at="2026-09-26T00:00:00Z",
                                     strike_at="2026-10-10T00:00:00Z")
        bid_a = create_rom_bid(client["id"], pkg_a["id"], estimated_crew_hours=100)
        submit_bid(bid_a["id"])
        accepted_a = accept_bid(bid_a["id"], client["id"])
        bid_b = create_rom_bid(client["id"], pkg_b["id"], estimated_crew_hours=100)
        submit_bid(bid_b["id"])
        accepted_b = accept_bid(bid_b["id"], client["id"])
        return shop, client, accepted_a["production_id"], accepted_b["production_id"]

    def test_overlapping_plans_sum_exceeds_fleet_rejected(self, api):
        """PRD §3.6: "the sum of `truck_count` over the shop's plans whose
        status is not `CANCELLED` and whose windows overlap the new window,
        plus the new plan's own `truck_count`, must not exceed the shop's
        `truck_fleet_size` — otherwise the plan is rejected with
        `ERR_FLEET_OVER_COMMITTED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/fleet_aggregate_capacity_overlapping_windows_rejected
        """
        _, _, prod_a, prod_b = self._setup_two_productions(api)
        get_success_data(api.create_transport_plan(
            {"production_id": prod_a, "truck_count": 4, "install_crew_hours": 16,
             "depart_at": "2026-09-10T00:00:00Z", "arrive_at": "2026-09-12T00:00:00Z"},
            TC,
        ))
        # 4 + 4 = 8 > 6
        resp = api.create_transport_plan(
            {"production_id": prod_b, "truck_count": 4, "install_crew_hours": 16,
             "depart_at": "2026-09-11T00:00:00Z", "arrive_at": "2026-09-13T00:00:00Z"},
            TC,
        )
        validate_error(resp, ApiErrorId.ERR_FLEET_OVER_COMMITTED, 409)

    def test_overlapping_plans_at_exact_capacity_passes(self, api):
        """PRD §3.6: "must not exceed the shop's `truck_fleet_size`" — sum
        exactly equal to fleet size passes (6 <= 6).

        Design: Difficulty/resource_temporal_overlap/fleet_aggregate_capacity_overlapping_windows_rejected
        """
        _, _, prod_a, prod_b = self._setup_two_productions(api)
        get_success_data(api.create_transport_plan(
            {"production_id": prod_a, "truck_count": 4, "install_crew_hours": 16,
             "depart_at": "2026-09-10T00:00:00Z", "arrive_at": "2026-09-12T00:00:00Z"},
            TC,
        ))
        # 4 + 2 = 6 == fleet_size 6 — passes
        resp = api.create_transport_plan(
            {"production_id": prod_b, "truck_count": 2, "install_crew_hours": 16,
             "depart_at": "2026-09-11T00:00:00Z", "arrive_at": "2026-09-13T00:00:00Z"},
            TC,
        )
        assert validate_success(resp, expected_status=201)["status"] == "PLANNED"


class TestCancelReleasesFleetCapacity:
    def test_cancel_drops_plan_from_fleet_sum(self, api):
        """PRD §3.6: "cancels a `PLANNED` plan into `CANCELLED`, at which
        point it stops counting toward the fleet overlap sums."

        Design: Corner/state_machines/cancel_planned_transport_releases_fleet_capacity
        """
        shop, client, pkg_a = setup_basic_scenario()
        pkg_b = setup_second_package(client["id"], show_title="Macbeth",
                                     load_in_at="2026-09-26T00:00:00Z",
                                     strike_at="2026-10-10T00:00:00Z",
                                     venue="Rialto")
        bid_a = create_rom_bid(client["id"], pkg_a["id"], estimated_crew_hours=100)
        submit_bid(bid_a["id"])
        accepted_a = accept_bid(bid_a["id"], client["id"])
        prod_a = accepted_a["production_id"]
        bid_b = create_rom_bid(client["id"], pkg_b["id"], estimated_crew_hours=100)
        submit_bid(bid_b["id"])
        accepted_b = accept_bid(bid_b["id"], client["id"])
        prod_b = accepted_b["production_id"]
        tp_a = get_success_data(api.create_transport_plan(
            {"production_id": prod_a, "truck_count": 4, "install_crew_hours": 16,
             "depart_at": "2026-09-10T00:00:00Z", "arrive_at": "2026-09-12T00:00:00Z"},
            TC,
        ))
        # B blocked while A is PLANNED
        blocked = api.create_transport_plan(
            {"production_id": prod_b, "truck_count": 4, "install_crew_hours": 16,
             "depart_at": "2026-09-11T00:00:00Z", "arrive_at": "2026-09-13T00:00:00Z"},
            TC,
        )
        validate_error(blocked, ApiErrorId.ERR_FLEET_OVER_COMMITTED, 409)
        # Cancel A, then B succeeds
        api.cancel_transport_plan(tp_a["id"], TC)
        ok = api.create_transport_plan(
            {"production_id": prod_b, "truck_count": 4, "install_crew_hours": 16,
             "depart_at": "2026-09-11T00:00:00Z", "arrive_at": "2026-09-13T00:00:00Z"},
            TC,
        )
        assert validate_success(ok, expected_status=201)["status"] == "PLANNED"
        # Second cancel on A fails (CANCELLED is terminal)
        again = api.cancel_transport_plan(tp_a["id"], TC)
        validate_error(again, ApiErrorId.ERR_INVALID_STATE, 409)


class TestConfirmTwice:
    def test_second_confirm_returns_invalid_state(self, api):
        """PRD §3.6: "A coordinator confirms a `PLANNED` plan, moving it to
        `CONFIRMED`" — confirm from CONFIRMED does not exist (state gate).
        PRD §2.6 priority 4: "the target entity must be in a state from which
        the requested transition exists ... (failures: `ERR_INVALID_STATE`)."

        Design: Corner/state_machines/transport_confirm_twice_returns_invalid_state
        """
        _, _, _, _, production = setup_accepted_production()
        tp = get_success_data(api.create_transport_plan(
            {"production_id": production["id"], "truck_count": 2,
             "install_crew_hours": 16,
             "depart_at": "2026-09-11T00:00:00Z", "arrive_at": "2026-09-12T00:00:00Z"},
            TC,
        ))
        api.confirm_transport_plan(tp["id"], TC)
        resp = api.confirm_transport_plan(tp["id"], TC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        after = get_success_data(api.get_transport_plan(tp["id"], TC))
        assert after["status"] == "CONFIRMED"


class TestLoadInGate:
    def test_load_in_fails_with_planned_plan(self, api):
        """PRD §3.6: "it requires at least one `CONFIRMED` transport plan for
        the production (else `ERR_TRANSPORT_NOT_CONFIRMED`, HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/load_in_requires_transport_confirmed
        """
        shop, client, _, _, production, _rev, _res = setup_in_build_production()
        production = drive_to_built(shop, client, production)
        # Plan still PLANNED
        tp = get_success_data(api.create_transport_plan(
            {"production_id": production["id"], "truck_count": 2,
             "install_crew_hours": 16,
             "depart_at": "2026-09-11T00:00:00Z", "arrive_at": "2026-09-12T00:00:00Z"},
            TC,
        ))
        resp = api.load_in(production["id"], TC)
        validate_error(resp, ApiErrorId.ERR_TRANSPORT_NOT_CONFIRMED, 409)

    def test_load_in_succeeds_after_confirm_and_executes_plan(self, api):
        """PRD §3.6: "Load-in itself is executed by a `TransportCoordinator`
        against a production in `BUILT`: it requires at least one `CONFIRMED`
        transport plan for the production (else `ERR_TRANSPORT_NOT_CONFIRMED`,
        HTTP 409), moves the production `BUILT → LOADED_IN`, and as a side
        effect every `CONFIRMED` plan of that production transitions to
        `EXECUTED`."

        Design: Difficulty/cross_entity_state_dependency/load_in_requires_transport_confirmed
        """
        shop, client, _, _, production, _rev, _res = setup_in_build_production()
        production = drive_to_built(shop, client, production)
        tp = get_success_data(api.create_transport_plan(
            {"production_id": production["id"], "truck_count": 2,
             "install_crew_hours": 16,
             "depart_at": "2026-09-11T00:00:00Z", "arrive_at": "2026-09-12T00:00:00Z"},
            TC,
        ))
        api.confirm_transport_plan(tp["id"], TC)
        resp = api.load_in(production["id"], TC)
        assert validate_success(resp)["status"] == "LOADED_IN"
        plan = get_success_data(api.get_transport_plan(tp["id"], TC))
        assert plan["status"] == "EXECUTED"


class TestLoadInBuffer:
    def _setup_built_with_pending(self, api):
        """IN_BUILD with review approved and sample approved (ready to complete)."""
        shop, client, pkg, bid, production, rev, res = setup_in_build_production(
            validity_days=90 if False else 30,  # not used here; just clarity
        ) if False else setup_in_build_production()
        sample = get_success_data(api.create_finish_sample(
            {"production_id": production["id"],
             "finish_code": "SCUFF_BRICK_RED", "texture_ref": "tex_v1"},
            PAINT,
        ))
        api.approve_finish_sample(sample["id"], make_client_pm_headers(client["id"]))
        return shop, client, production

    def test_gap_one_day_rejected(self, api):
        """PRD §3.4: "the gap between the production's `load_in_deadline_at`
        and the logical clock is at least two full days — a gap of exactly
        two days passes, anything shorter is rejected with
        `ERR_LOAD_IN_TOO_SOON` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/load_in_buffer_minimum_gap_enforced
        """
        _, _, production = self._setup_built_with_pending(api)
        # Default clock 2026-08-01; advance to 2026-09-25 -> gap 1 day
        set_clock("2026-09-25T00:00:00Z")
        resp = api.complete_build(production["id"], FOREMAN)
        validate_error(resp, ApiErrorId.ERR_LOAD_IN_TOO_SOON, 409)

    def test_gap_exactly_two_days_passes(self, api):
        """PRD §3.4: "a gap of exactly two days passes".

        Design: Difficulty/resource_temporal_overlap/load_in_buffer_minimum_gap_enforced
        """
        _, _, production = self._setup_built_with_pending(api)
        set_clock("2026-09-24T00:00:00Z")
        resp = api.complete_build(production["id"], FOREMAN)
        built = validate_success(resp)
        assert built["status"] == "BUILT"
        assert_instant_equals(built["built_at"], "2026-09-24T00:00:00Z")
