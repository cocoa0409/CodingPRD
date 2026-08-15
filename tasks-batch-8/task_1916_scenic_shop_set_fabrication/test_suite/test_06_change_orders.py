"""Change orders: pricing with posture/rush/rework, approval cascade,
rejection conservation, withdrawal."""
import pytest

from test_helpers import (
    ADMIN,
    EST,
    FOREMAN,
    ApiErrorId,
    assert_change_order,
    assert_instant_equals,
    create_change_order_on_production,
    create_rom_bid,
    get_success_data,
    make_client_pm_headers,
    setup_accepted_production,
    setup_basic_scenario,
    setup_design_package,
    submit_bid,
    accept_bid,
    supersede_package_to_revision_2,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestChangeOrderPricing:
    def test_pricing_with_tight_posture_and_rush(self, api):
        """PRD §3.5: "The labor multiplier is the shop's
        `overtime_multiplier_bp` when the posture at creation is `TIGHT` or
        `SATURATED`, and 10000 otherwise. ... The rush component applies only
        when `delta_load_in_days` is negative and the labor component is
        positive: the rush rate is 500 bp per day of deadline compression,
        capped at 3000 bp."

        Design: Difficulty/combinatorial_formula/change_order_price_posture_branch_with_rush_cap
        """
        # Setup: production with committed 320 -> posture TIGHT
        shop, client, pkg, bid, production = setup_accepted_production(
            estimated_crew_hours=320,
        )
        supersede_package_to_revision_2(client["id"])
        co = create_change_order_on_production(
            production["id"], new_drawing_revision=2,
            delta_materials_cents=100000, delta_labor_hours=40,
            delta_load_in_days=-3,
        )
        assert_change_order(co)
        assert co["priced_posture"] == "TIGHT"
        # materials round(100000*1.10)=110000; labor 40*8000*1.5=480000;
        # rush min(3000, 500*3)=1500bp -> round(480000*0.15)=72000
        # delta 110000+480000+72000 = 662000
        assert co["delta_price_cents"] == 662000
        assert co["status"] == "PROPOSED"

    def test_rush_cap_binds_at_six_days(self, api):
        """PRD §3.5: "the rush rate is 500 bp per day of deadline compression,
        capped at 3000 bp — the cap binds once the compression reaches six
        days."

        Design: Corner/calculations/rush_cap_binds_at_six_days_of_schedule_compression
        """
        shop, client, pkg, bid, production = setup_accepted_production(
            estimated_crew_hours=320,
        )
        # CO-1: dd -6 (cap binds exactly at 6)
        setup_design_package(client["id"], show_title="Hamlet")  # -> rev 2
        co_1 = create_change_order_on_production(
            production["id"], new_drawing_revision=2,
            delta_materials_cents=0, delta_labor_hours=10, delta_load_in_days=-6,
        )
        # CO-2: dd -7 (cap binds; same rush_bp)
        setup_design_package(client["id"], show_title="Hamlet")  # -> rev 3
        co_2 = create_change_order_on_production(
            production["id"], new_drawing_revision=3,
            delta_materials_cents=0, delta_labor_hours=10, delta_load_in_days=-7,
        )
        # labor 10*8000*1.5=120000; rush min(3000,500*6)=3000 -> 36000; total 156000
        assert co_1["delta_price_cents"] == 156000
        assert co_2["delta_price_cents"] == 156000
        assert co_1["co_no"] == 1
        assert co_2["co_no"] == 2


class TestChangeOrderApprovalCascade:
    def test_approval_applies_cascade_and_releases_late_bays(self, api):
        """PRD §3.5: "**Approval** runs the full cascade: the production's
        `current_price_cents` increases by the pinned `delta_price_cents`;
        `load_in_deadline_at` shifts by `delta_load_in_days` whole days;
        `committed_crew_hours` becomes the greater of 1 and the prior
        committed hours plus `delta_labor_hours` — the floor at 1 means hours
        may shrink but never below one; and `applied_drawing_revision`
        advances to the order's `new_drawing_revision`. The deadline mutation
        cascades to the bays: every `ACTIVE` bay reservation of the production
        whose `window_end` lies after the new `load_in_deadline_at`
        transitions to `RELEASED`."

        Design: Difficulty/transitive_cascade/change_order_approval_cascade_releases_bays_and_recomputes_posture
        """
        shop, client, pkg, bid, production = setup_accepted_production(
            estimated_crew_hours=320,
        )
        res = get_success_data(api.create_bay_reservation(
            {"production_id": production["id"], "bay_slot": 1,
             "window_start": "2026-09-01T00:00:00Z",
             "window_end": "2026-09-26T00:00:00Z"},
            FOREMAN,
        ))
        supersede_package_to_revision_2(client["id"])
        co = create_change_order_on_production(
            production["id"], new_drawing_revision=2,
            delta_materials_cents=0, delta_labor_hours=-40, delta_load_in_days=-3,
        )
        # Approve the CO
        approved = validate_success(api.approve_change_order(
            co["id"], make_client_pm_headers(client["id"]),
        ))
        assert approved["status"] == "APPROVED"
        # Hop 1: production mutated
        prod = get_success_data(api.get_production(production["id"], EST))
        assert prod["current_price_cents"] == 420000   # 900000 + (-480000)
        assert_instant_equals(prod["load_in_deadline_at"], "2026-09-23T00:00:00Z")
        assert prod["committed_crew_hours"] == 280
        assert prod["applied_drawing_revision"] == 2
        # Hop 2: bay released (window_end 2026-09-26 > new deadline 2026-09-23)
        res_after = get_success_data(api.get_bay_reservation(res["id"], FOREMAN))
        assert res_after["status"] == "RELEASED"
        # Hop 3+4: shop recomputed
        shop_after = get_success_data(api.get_shop(shop["id"], ADMIN))
        assert shop_after["committed_crew_hours"] == 280
        assert shop_after["capacity_ratio_bp"] == 7000
        assert shop_after["posture"] == "OPEN"

    def test_approval_recomputes_shop_and_client_aggregates(self, api):
        """PRD §3.5: "The hours mutation cascades to the shop:
        `committed_crew_hours`, `capacity_ratio_bp`, and `posture` are all
        recomputed. The price mutation cascades to the client:
        `outstanding_cents` is recomputed."

        Design: Difficulty/transitive_cascade/change_order_approval_cascade_releases_bays_and_recomputes_posture
        """
        shop, client, pkg, bid, production = setup_accepted_production(
            estimated_crew_hours=320,
        )
        client_before = get_success_data(api.get_client(client["id"], ADMIN))
        assert client_before["outstanding_cents"] == 900000
        supersede_package_to_revision_2(client["id"])
        co = create_change_order_on_production(
            production["id"], new_drawing_revision=2,
            delta_materials_cents=0, delta_labor_hours=-40, delta_load_in_days=-3,
        )
        api.approve_change_order(co["id"], make_client_pm_headers(client["id"]))
        client_after = get_success_data(api.get_client(client["id"], ADMIN))
        # price 420000 now
        assert client_after["outstanding_cents"] == 420000


class TestChangeOrderRejectConservation:
    def test_reject_conserves_production_price_and_hours(self, api):
        """PRD §3.5: "**Rejection** is the compensating-invariant anchor: the
        order moves to `REJECTED` and production fields, bay reservations, and
        shop aggregates are explicitly untouched."

        Design: Difficulty/compensating_invariant/change_order_reject_conserves_production_price
        """
        shop, client, pkg, bid, production = setup_accepted_production(
            estimated_crew_hours=100,
        )
        supersede_package_to_revision_2(client["id"])
        co = create_change_order_on_production(
            production["id"], new_drawing_revision=2,
            delta_materials_cents=50000, delta_labor_hours=10, delta_load_in_days=2,
        )
        # delta_price_cents pinned at creation (OPEN posture, no rush):
        # labor 10*8000=80000; materials round(50000*1.10)=55000; total 135000
        assert co["delta_price_cents"] == 135000
        rejected = validate_success(api.reject_change_order(
            co["id"], make_client_pm_headers(client["id"]),
        ))
        assert rejected["status"] == "REJECTED"
        # Production untouched
        prod = get_success_data(api.get_production(production["id"], EST))
        assert prod["current_price_cents"] == 900000
        assert_instant_equals(prod["load_in_deadline_at"], "2026-09-26T00:00:00Z")
        assert prod["committed_crew_hours"] == 100
        assert prod["applied_drawing_revision"] == 1

    def test_rejected_co_does_not_mutate_shop_aggregates(self, api):
        """PRD §3.5: "**Rejection** is the compensating-invariant anchor: the
        order moves to `REJECTED` and production fields, bay reservations, and
        shop aggregates are explicitly untouched."

        Design: Difficulty/compensating_invariant/change_order_reject_conserves_production_price
        """
        shop, client, pkg, bid, production = setup_accepted_production(
            estimated_crew_hours=100,
        )
        shop_before = get_success_data(api.get_shop(shop["id"], ADMIN))
        supersede_package_to_revision_2(client["id"])
        co = create_change_order_on_production(
            production["id"], new_drawing_revision=2,
            delta_materials_cents=50000, delta_labor_hours=10,
            delta_load_in_days=2,
        )
        api.reject_change_order(co["id"], make_client_pm_headers(client["id"]))
        shop_after = get_success_data(api.get_shop(shop["id"], ADMIN))
        assert shop_after["committed_crew_hours"] == shop_before["committed_crew_hours"]
        assert shop_after["capacity_ratio_bp"] == shop_before["capacity_ratio_bp"]
        assert shop_after["posture"] == shop_before["posture"]


class TestChangeOrderWithdraw:
    def test_withdraw_proposed_co_leaves_production_untouched(self, api):
        """PRD §3.5: "An `Estimator` may instead withdraw a `PROPOSED` order
        into `WITHDRAWN` with no other effects. Any decision on an order no
        longer `PROPOSED` is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/withdraw_proposed_change_order_leaves_production_untouched
        """
        shop, client, pkg, bid, production = setup_accepted_production(
            estimated_crew_hours=100,
        )
        supersede_package_to_revision_2(client["id"])
        co = create_change_order_on_production(
            production["id"], new_drawing_revision=2,
            delta_materials_cents=1000, delta_labor_hours=1, delta_load_in_days=0,
        )
        withdrawn = validate_success(api.withdraw_change_order(co["id"], EST))
        assert withdrawn["status"] == "WITHDRAWN"
        # Approve after withdraw fails
        resp = api.approve_change_order(co["id"], make_client_pm_headers(client["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        # Production untouched
        prod = get_success_data(api.get_production(production["id"], EST))
        assert prod["current_price_cents"] == 900000
        assert_instant_equals(prod["load_in_deadline_at"], "2026-09-26T00:00:00Z")
        assert prod["committed_crew_hours"] == 100


class TestChangeOrderValidation:
    def test_co_with_non_current_revision_returns_409(self, api):
        """PRD §3.5: "The `new_drawing_revision` must equal the design
        package's current revision and must be strictly greater than the
        production's `applied_drawing_revision`; otherwise the create is
        rejected with `ERR_REVISION_NOT_CURRENT` (HTTP 409)."

        Design: Corner/validations/change_order_with_non_current_revision_returns_409
        """
        shop, client, pkg, bid, production = setup_accepted_production()
        # Package still at revision 1; production applied_revision 1.
        # Asking for revision 2 fails (not current).
        prod_now = get_success_data(api.get_production(production["id"], EST))
        resp = api.create_change_order(
            {"production_id": production["id"],
             "expected_production_version": prod_now["version"],
             "new_drawing_revision": 2, "delta_materials_cents": 0,
             "delta_labor_hours": 5, "delta_load_in_days": 0},
            EST,
        )
        validate_error(resp, ApiErrorId.ERR_REVISION_NOT_CURRENT, 409)
        data, meta = validate_paginated(api.list_change_orders(
            EST, params={"production_id": production["id"]},
        ))
        assert meta["total_count"] == 0
