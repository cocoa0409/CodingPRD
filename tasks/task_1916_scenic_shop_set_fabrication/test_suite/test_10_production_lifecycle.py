"""Production lifecycle: start-build, complete-build, strike, close gates,
capacity restoration."""
import pytest

from test_helpers import (
    ADMIN,
    ENGINEER,
    EST,
    FOREMAN,
    PAINT,
    TC,
    ApiErrorId,
    assert_production,
    create_rom_bid,
    drive_to_built,
    drive_to_loaded_in,
    drive_to_struck,
    get_success_data,
    make_client_pm_headers,
    set_clock,
    setup_accepted_production,
    setup_basic_scenario,
    setup_in_build_production,
    submit_bid,
    accept_bid,
    supersede_package_to_revision_2,
    create_change_order_on_production,
    validate_error,
    validate_success,
)


class TestCompleteBuildInvalidState:
    def test_complete_build_from_scheduled_returns_invalid_state(self, api):
        """PRD §2.6 priority 4: "the target entity must be in a state from
        which the requested transition exists; terminal entities reject all
        further actions."  PRD §3.4: "marks a production complete only when
        it is `IN_BUILD` (else `ERR_INVALID_STATE`)."

        Design: Corner/state_machines/complete_build_from_scheduled_returns_invalid_state
        """
        _, _, _, _, production = setup_accepted_production()
        resp = api.complete_build(production["id"], FOREMAN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        after = get_success_data(api.get_production(production["id"], EST))
        assert after["status"] == "SCHEDULED"


class TestStartBuildBayCoverage:
    def test_start_build_with_under_reserved_bays_fails(self, api):
        """PRD §3.4: "the count of `ACTIVE` bay reservations belonging to the
        production must be at least the production's `bays_required` —
        otherwise the start is rejected with `ERR_BAY_UNDER_RESERVED`
        (HTTP 409)."

        Design: Corner/validations/start_build_with_under_reserved_bays_returns_409
        """
        _, _, _, _, production = setup_accepted_production(bays_required=2)
        # Approve structural review so only bay gate can fail
        rev = get_success_data(api.create_engineering_review(
            {"production_id": production["id"], "scope": "STRUCTURAL",
             "design_load_lb": 4000, "member_capacity_lb": 6000},
            FOREMAN,
        ))
        api.approve_engineering_review(rev["id"], ENGINEER)
        # Only 1 of 2 bays reserved
        get_success_data(api.create_bay_reservation(
            {"production_id": production["id"], "bay_slot": 1,
             "window_start": "2026-09-01T00:00:00Z",
             "window_end": "2026-09-26T00:00:00Z"},
            FOREMAN,
        ))
        resp = api.start_build(production["id"], FOREMAN)
        validate_error(resp, ApiErrorId.ERR_BAY_UNDER_RESERVED, 409)

    def test_start_build_succeeds_after_second_bay_reserved(self, api):
        """PRD §3.4: "On success the production moves `SCHEDULED →
        IN_BUILD`."

        Design: Corner/validations/start_build_with_under_reserved_bays_returns_409
        """
        _, _, _, _, production = setup_accepted_production(bays_required=2)
        rev = get_success_data(api.create_engineering_review(
            {"production_id": production["id"], "scope": "STRUCTURAL",
             "design_load_lb": 4000, "member_capacity_lb": 6000},
            FOREMAN,
        ))
        api.approve_engineering_review(rev["id"], ENGINEER)
        get_success_data(api.create_bay_reservation(
            {"production_id": production["id"], "bay_slot": 1,
             "window_start": "2026-09-01T00:00:00Z",
             "window_end": "2026-09-26T00:00:00Z"},
            FOREMAN,
        ))
        get_success_data(api.create_bay_reservation(
            {"production_id": production["id"], "bay_slot": 2,
             "window_start": "2026-09-01T00:00:00Z",
             "window_end": "2026-09-26T00:00:00Z"},
            FOREMAN,
        ))
        resp = api.start_build(production["id"], FOREMAN)
        assert validate_success(resp)["status"] == "IN_BUILD"


class TestPostureInputSet:
    def test_built_production_drops_out_of_committed_set(self, api):
        """PRD §2.7: "The shop's `committed_crew_hours` is the sum of
        `committed_crew_hours` over its productions whose status is
        `SCHEDULED`, `IN_BUILD`, or `ON_HOLD` — productions that are `BUILT`,
        `LOADED_IN`, `STRUCK`, or `CLOSED` are excluded from the sum."

        Design: Corner/calculations/posture_input_set_excludes_built_productions
        """
        shop, client, _, _, production, _rev, _res = setup_in_build_production(
            estimated_crew_hours=100,
        )
        # While IN_BUILD the 100 hours count
        shop_inbuild = get_success_data(api.get_shop(shop["id"], ADMIN))
        assert shop_inbuild["committed_crew_hours"] == 100
        # Drive to BUILT
        production = drive_to_built(shop, client, production, add_finish_sample=True)
        assert production["status"] == "BUILT"
        shop_after = get_success_data(api.get_shop(shop["id"], ADMIN))
        assert shop_after["committed_crew_hours"] == 0
        assert shop_after["posture"] == "OPEN"


class TestCloseBarriers:
    def test_close_blocked_by_proposed_change_order_first(self, api):
        """PRD §3.7: "Closing a production is a `ShopForeman` action against
        a production in `STRUCK`, guarded by two barriers checked in this
        order: first, no change order of the production may remain
        `PROPOSED` — otherwise `ERR_CHANGE_ORDERS_PENDING` (HTTP 409); second,
        no bay reservation of the production may remain `ACTIVE` — otherwise
        `ERR_RESERVATIONS_OPEN` (HTTP 409)."

        Design: Corner/validations/close_with_proposed_change_order_returns_409
        """
        shop, client, _, _, production, _rev, res = setup_in_build_production()
        production, _plan = drive_to_loaded_in(shop, client, production)
        # Create a PROPOSED CO (allowed while LOADED_IN)
        supersede_package_to_revision_2(client["id"])
        co = create_change_order_on_production(
            production["id"], new_drawing_revision=2,
            delta_materials_cents=1000, delta_labor_hours=1, delta_load_in_days=0,
        )
        # Strike and attempt close
        api.strike(production["id"], {"reclaim_lines": []}, FOREMAN)
        resp = api.close_production(production["id"], FOREMAN)
        validate_error(resp, ApiErrorId.ERR_CHANGE_ORDERS_PENDING, 409)
        # Reject CO + release reservation, close succeeds
        api.reject_change_order(co["id"], make_client_pm_headers(client["id"]))
        api.delete_bay_reservation(res["id"], FOREMAN)
        ok = api.close_production(production["id"], FOREMAN)
        assert validate_success(ok)["status"] == "CLOSED"


class TestCloseRestoresCapacity:
    def test_close_restores_committed_capacity(self, api):
        """PRD §3.7: "Closing moves the production to `CLOSED`, subtracts its
        `committed_crew_hours` from the shop's committed hours with
        `capacity_ratio_bp` and `posture` recomputed, and recomputes the
        client's `outstanding_cents` now that the closed production has
        dropped out of the outstanding set."

        Design: Difficulty/compensating_invariant/production_close_restores_committed_capacity
        """
        shop, client, _, _, production, _rev, res = setup_in_build_production(
            estimated_crew_hours=320,
        )
        # In build: shop committed = 320, posture TIGHT (8000bp)
        shop_mid = get_success_data(api.get_shop(shop["id"], ADMIN))
        assert shop_mid["committed_crew_hours"] == 320
        assert shop_mid["posture"] == "TIGHT"
        # Drive to STRUCK, release bay, close
        production = drive_to_struck(shop, client, production)
        api.delete_bay_reservation(res["id"], FOREMAN)
        ok = api.close_production(production["id"], FOREMAN)
        assert validate_success(ok)["status"] == "CLOSED"
        shop_after = get_success_data(api.get_shop(shop["id"], ADMIN))
        assert shop_after["committed_crew_hours"] == 0
        assert shop_after["capacity_ratio_bp"] == 0
        assert shop_after["posture"] == "OPEN"

    def test_close_recomputes_client_outstanding(self, api):
        """PRD §3.7: "recomputes the client's `outstanding_cents` now that
        the closed production has dropped out of the outstanding set."

        Design: Difficulty/compensating_invariant/production_close_restores_committed_capacity
        """
        shop, client, _, _, production, _rev, res = setup_in_build_production(
            estimated_crew_hours=100,
        )
        production = drive_to_struck(shop, client, production)
        api.delete_bay_reservation(res["id"], FOREMAN)
        api.close_production(production["id"], FOREMAN)
        client_after = get_success_data(api.get_client(client["id"], ADMIN))
        assert client_after["outstanding_cents"] == 0

    def test_close_blocked_by_active_reservation(self, api):
        """PRD §3.7: "no bay reservation of the production may remain
        `ACTIVE` — otherwise `ERR_RESERVATIONS_OPEN` (HTTP 409)."

        Design: Difficulty/compensating_invariant/production_close_restores_committed_capacity
        """
        shop, client, _, _, production, _rev, res = setup_in_build_production()
        production = drive_to_struck(shop, client, production)
        # Reservation still ACTIVE -> close fails
        resp = api.close_production(production["id"], FOREMAN)
        validate_error(resp, ApiErrorId.ERR_RESERVATIONS_OPEN, 409)
