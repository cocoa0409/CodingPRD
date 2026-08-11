"""The weekly catch allocation, its surplus routing, and the split into consignments."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    allocate,
    arrive_sub_lot,
    assert_allocation_partition,
    assert_split_mass_invariant,
    delivery_of_week,
    get_success_data,
    hub_destination,
    new_hub,
    new_zone,
    pause_subscription,
    read_delivery,
    read_lot,
    read_sub_lot,
    route_destination,
    setup_fleet,
    setup_landed_lot,
    setup_member_subscription,
    setup_open_season,
    setup_three_share_week1,
    split_lot,
    sub_lots_of,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_short_fill_pays_the_floors_in_weight_order_then_spreads_the_rest(api):
    """PRD 3.4: "**The short-fill branch** runs when at least one delivery's exact proportional
    share falls below its plan's `min_floor_pounds`. Here floors come first. Walking the fixed
    order, each delivery whose `min_floor_pounds` is less than or equal to the pounds still
    unassigned receives exactly its `min_floor_pounds`; each delivery for which it is not
    receives 0.00 pounds and is left empty."
    PRD 3.4: "A pool of 5.99 pounds takes the short branch and yields 2.39, 3.60 and 0.00."
    PRD 3.4: "On the fill axis it moves `PENDING → FULL_FILL` when its `allocated_pounds` has
    reached or passed its plan's `target_pounds_per_delivery`, and `PENDING → UNDER_FILLED`
    when it has not."

    Design: Corner/calculations/short_fill_satisfies_floors_in_weight_order_then_spreads_the_rest
    """
    ctx = setup_three_share_week1(5.99)
    lot = allocate(ctx["lot_id"], 1, ctx["lot"]["version"])

    assert lot["allocation_variant"] == "SHORT_FILL"
    assert float(read_delivery(ctx["delivery_lrg"]["id"])["allocated_pounds"]) == pytest.approx(3.60)
    assert float(read_delivery(ctx["delivery_med"]["id"])["allocated_pounds"]) == pytest.approx(2.39)
    assert float(read_delivery(ctx["delivery_sml"]["id"])["allocated_pounds"]) == pytest.approx(0.00)
    assert read_delivery(ctx["delivery_sml"]["id"])["fill_status"] == "UNDER_FILLED"
    assert read_delivery(ctx["delivery_med"]["id"])["fill_status"] == "UNDER_FILLED"

    assert float(lot["allocated_pounds_total"]) == pytest.approx(5.99)
    assert float(lot["surplus_secondary_pounds"]) == pytest.approx(0.00)
    assert float(lot["surplus_donated_pounds"]) == pytest.approx(0.00)
    assert_allocation_partition(lot)


def test_normal_fill_hands_the_residue_cent_pound_to_the_heaviest_share(api):
    """PRD 3.4: "Each delivery is allocated its exact share truncated downward to two decimal
    places, capped at its plan's `target_pounds_per_delivery` so that no box is overfilled.
    Truncation and capping together leave a residue — the pool less the sum of what was
    allocated — and that residue is handed out one hundredth of a pound at a time, walking the
    fixed order repeatedly, to deliveries still strictly below their target."
    PRD 3.4: "A pool of 8.00 pounds takes the normal branch and yields 2.66, 4.01 and 1.33, the
    single hundredth of residue landing on d2 because it comes first in the order."

    Design: Corner/calculations/normal_fill_residue_cent_pound_goes_to_the_heaviest_share
    """
    ctx = setup_three_share_week1(8.00)
    lot = allocate(ctx["lot_id"], 1, ctx["lot"]["version"])

    assert lot["allocation_variant"] == "NORMAL_FILL"
    assert float(read_delivery(ctx["delivery_med"]["id"])["allocated_pounds"]) == pytest.approx(2.66)
    assert float(read_delivery(ctx["delivery_lrg"]["id"])["allocated_pounds"]) == pytest.approx(4.01)
    assert float(read_delivery(ctx["delivery_sml"]["id"])["allocated_pounds"]) == pytest.approx(1.33)

    assert float(lot["allocated_pounds_total"]) == pytest.approx(8.00)
    assert float(lot["surplus_secondary_pounds"]) == pytest.approx(0.00)
    assert float(lot["surplus_donated_pounds"]) == pytest.approx(0.00)
    assert_allocation_partition(lot)


def test_surplus_above_the_targets_routes_sixty_forty_to_secondary_and_donation(api):
    """PRD 3.4: "`SURPLUS_SECONDARY_MAX_PCT` is 0.60, so `surplus_secondary_pounds` is 60
    percent of that surplus truncated downward to two decimals, and `surplus_donated_pounds` is
    everything left after that — the donation bucket deliberately absorbs the truncation
    residue so that allocated, secondary and donated pounds sum exactly back to
    `landed_pounds_net`."
    PRD 3.4: "A surplus of 3.00 pounds routes 1.80 to the secondary market and 1.20 to
    donation; a surplus of 1.00 pound routes 0.60 and 0.40."

    Design: Corner/calculations/surplus_over_targets_splits_sixty_forty_between_secondary_and_donation
    """
    ctx = setup_three_share_week1(18.00)
    lot = allocate(ctx["lot_id"], 1, ctx["lot"]["version"])

    assert float(read_delivery(ctx["delivery_med"]["id"])["allocated_pounds"]) == pytest.approx(5.00)
    assert float(read_delivery(ctx["delivery_lrg"]["id"])["allocated_pounds"]) == pytest.approx(7.50)
    assert float(read_delivery(ctx["delivery_sml"]["id"])["allocated_pounds"]) == pytest.approx(2.50)
    assert read_delivery(ctx["delivery_med"]["id"])["fill_status"] == "FULL_FILL"

    assert float(lot["allocated_pounds_total"]) == pytest.approx(15.00)
    assert float(lot["surplus_secondary_pounds"]) == pytest.approx(1.80)
    assert float(lot["surplus_donated_pounds"]) == pytest.approx(1.20)
    assert float(lot["landed_pounds_net"]) == pytest.approx(18.00)
    assert_allocation_partition(lot)


def _paused_and_active_week1_boxes():
    """Two identical MEDIUM week-1 boxes, one of them on a subscription that has been paused."""
    ctx = setup_open_season(offered_species=("SALMON",))
    hub = new_hub()
    active = setup_member_subscription(
        ctx["season_id"],
        ctx["plan"]["id"],
        full_name="Mara One",
        email="m1@csf.test",
        join_week_index=1,
        fulfillment_mode="HUB_PICKUP",
        pickup_hub_id=hub["id"],
    )
    paused = setup_member_subscription(
        ctx["season_id"],
        ctx["plan"]["id"],
        full_name="Nils Two",
        email="m2@csf.test",
        join_week_index=1,
        fulfillment_mode="HUB_PICKUP",
        pickup_hub_id=hub["id"],
    )
    pause_subscription(paused["subscription_id"])

    fleet = setup_fleet(ctx["season_id"], species="SALMON")
    landing = setup_landed_lot(ctx["season_id"], fleet, "SALMON", 5.00)
    ctx.update(fleet)
    ctx.update(landing)
    ctx["active"] = active
    ctx["paused"] = paused
    ctx["delivery_active"] = delivery_of_week(active["subscription_id"], 1)
    ctx["delivery_paused"] = delivery_of_week(paused["subscription_id"], 1)
    return ctx


def test_a_paused_subscriptions_box_is_excluded_from_the_eligible_set(api):
    """PRD 3.4: "A share delivery participates only if its `season_id` matches the season of the
    lot's trip; its `week_index` equals the week supplied on the call; its `fulfillment_status`
    is `SCHEDULED`; its subscription's `lifecycle_status` is `ACTIVE`; and its subscription's
    plan has a `species_tier` exactly equal to the commercial tier of the lot's species under
    the `SPECIES_TIER_MAP`."
    PRD 3.4: "Everything else is out: paused, past-due, cancelled and transferred subscriptions
    do not receive fish, and neither does a whitefish plan when a shellfish lot lands."

    Design: Difficulty/cross_entity_state_dependency/allocation_eligibility_depends_on_subscription_lifecycle
    """
    ctx = _paused_and_active_week1_boxes()
    allocate(ctx["lot_id"], 1, ctx["lot"]["version"])

    active_box = read_delivery(ctx["delivery_active"]["id"])
    assert float(active_box["allocated_pounds"]) == pytest.approx(5.00)
    assert active_box["fulfillment_status"] == "ALLOCATED"
    assert active_box["fill_status"] == "FULL_FILL"

    paused_box = read_delivery(ctx["delivery_paused"]["id"])
    assert float(paused_box["allocated_pounds"]) == pytest.approx(0.00)
    assert paused_box["fulfillment_status"] == "SCHEDULED"
    assert paused_box["fill_status"] == "PENDING"


def test_the_whole_pool_goes_to_the_single_eligible_box_and_leaves_no_surplus(api):
    """PRD 3.4: "The lot records `allocated_pounds_total` as the sum of what it handed out,
    records the `allocation_week_index` it was run for, moves `RECORDED → ALLOCATED`, and
    increments its `version` by 1."
    PRD 3.4: "Whatever the allocation did not hand out is **surplus**, and it is routed
    immediately in the same request. Take the lot's `landed_pounds_net` less its
    `allocated_pounds_total`."

    Design: Difficulty/cross_entity_state_dependency/allocation_eligibility_depends_on_subscription_lifecycle
    """
    ctx = _paused_and_active_week1_boxes()
    before_version = ctx["lot"]["version"]
    lot = allocate(ctx["lot_id"], 1, before_version)

    assert float(lot["allocated_pounds_total"]) == pytest.approx(5.00)
    assert float(lot["surplus_secondary_pounds"]) == pytest.approx(0.00)
    assert float(lot["surplus_donated_pounds"]) == pytest.approx(0.00)
    assert lot["allocation_variant"] == "NORMAL_FILL"
    assert lot["status"] == "ALLOCATED"
    assert lot["allocation_week_index"] == 1
    assert lot["version"] == before_version + 1
    assert_allocation_partition(lot)


def test_a_second_allocation_carrying_the_pre_allocation_version_is_refused(api):
    """PRD 2.7: "The first is the catch allocation. A request that runs the weekly allocation
    against a landing lot must carry `expected_landing_lot_version` equal to that lot's current
    `version`."
    PRD 2.7: "If the value supplied does not equal the parent's current `version`, the request
    is rejected with `ERR_STALE_VERSION` at HTTP 412 and nothing is written."
    PRD 2.7: "A successful allocation run increments the lot's `version` by 1, which means a
    client that wants to run the allocation twice must re-read the lot in between."

    Design: Corner/cross_cutting_complexity_layers/stale_landing_lot_version_on_re_allocation_returns_412
    """
    ctx = setup_open_season(offered_species=("SALMON",))
    hub = new_hub()
    part = setup_member_subscription(
        ctx["season_id"],
        ctx["plan"]["id"],
        join_week_index=1,
        fulfillment_mode="HUB_PICKUP",
        pickup_hub_id=hub["id"],
    )
    fleet = setup_fleet(ctx["season_id"], species="SALMON")
    landing = setup_landed_lot(ctx["season_id"], fleet, "SALMON", 5.00)
    stale_version = landing["lot"]["version"]
    allocated = allocate(landing["lot_id"], 1, stale_version)

    response = api.run_allocation(
        landing["lot_id"],
        {"week_index": 1, "expected_landing_lot_version": allocated["version"] - 1},
        ADMIN,
    )
    assert response.status_code == 412
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)

    lot = read_lot(landing["lot_id"])
    assert lot["status"] == "ALLOCATED"
    assert float(lot["allocated_pounds_total"]) == pytest.approx(5.00)

    delivery = delivery_of_week(part["subscription_id"], 1)
    assert float(delivery["allocated_pounds"]) == pytest.approx(5.00)
    assert delivery["fulfillment_status"] == "ALLOCATED"


def test_a_split_whose_destination_pounds_do_not_reconcile_is_refused(api):
    """PRD 3.4: "First, the sum of the requested destination pounds must equal the lot's
    `allocated_pounds_total` exactly to two decimals."
    PRD 3.4: "Any disagreement, in either test, is refused with
    `ERR_MASS_CONSERVATION_VIOLATION`; a lot with 9.00 allocated pounds split as 4.50 to one
    hub and 4.50 to one zone is accepted only when the deliveries actually routed to that hub
    were allocated 4.50 pounds between them, and 4.49 or 4.51 is refused."

    Design: Corner/validations/split_pounds_that_do_not_reconcile_are_rejected
    """
    ctx = setup_open_season(offered_species=("SALMON",))
    hub = new_hub()
    setup_member_subscription(
        ctx["season_id"],
        ctx["plan"]["id"],
        join_week_index=1,
        fulfillment_mode="HUB_PICKUP",
        pickup_hub_id=hub["id"],
    )
    fleet = setup_fleet(ctx["season_id"], species="SALMON")
    landing = setup_landed_lot(ctx["season_id"], fleet, "SALMON", 5.00)
    allocate(landing["lot_id"], 1, landing["lot"]["version"])

    response = api.split_lot(
        landing["lot_id"], {"destinations": [hub_destination(hub["id"], 4.99)]}, ADMIN
    )
    assert response.status_code == 422
    validate_error(response, ApiErrorId.ERR_MASS_CONSERVATION_VIOLATION.value)

    lot = read_lot(landing["lot_id"])
    assert lot["status"] == "ALLOCATED"
    assert float(lot["split_pounds_total"]) == pytest.approx(0.00)

    _, meta = validate_paginated(api.list_sub_lots(ADMIN, {"landing_lot_id": landing["lot_id"]}))
    assert meta["total_count"] == 0


def test_a_split_across_two_pipelines_creates_one_sub_lot_per_destination(api):
    """PRD 3.4: "On success one sub-lot is created per destination in `IN_TRANSIT`, each
    carrying its `landing_lot_id`, its `destination_type`, its `pounds` and either a
    `pickup_hub_id` or a `delivery_zone_id` according to its type; every routed delivery is
    stamped with its `sub_lot_id`; `split_pounds_total` is set to the requested total; and the
    lot moves `ALLOCATED → SPLIT`."
    PRD 3.4: "Sub-lots are readable individually and listable with `landing_lot_id`,
    `pickup_hub_id` and `delivery_zone_id` filters."

    Design: Corner/endpoints/sub_lot_filtered_list_finds_the_children_of_a_lot
    """
    ctx = setup_open_season(offered_species=("SALMON",))
    hub = new_hub()
    zone = new_zone()
    setup_member_subscription(
        ctx["season_id"],
        ctx["plan"]["id"],
        full_name="Mara One",
        email="m1@csf.test",
        join_week_index=1,
        fulfillment_mode="HUB_PICKUP",
        pickup_hub_id=hub["id"],
    )
    setup_member_subscription(
        ctx["season_id"],
        ctx["plan"]["id"],
        full_name="Nils Two",
        email="m2@csf.test",
        join_week_index=1,
        fulfillment_mode="HOME_DELIVERY",
        delivery_zone_id=zone["id"],
    )
    fleet = setup_fleet(ctx["season_id"], species="SALMON")
    landing = setup_landed_lot(ctx["season_id"], fleet, "SALMON", 5.00)
    allocate(landing["lot_id"], 1, landing["lot"]["version"])

    # PRD 4 fixes only the generic rule "Creating a new resource returns HTTP 201; every
    # other successful operation returns HTTP 200" and never says which side this route
    # falls on: it creates sub-lot rows but its data payload is the *updated* lot moving
    # `ALLOCATED -> SPLIT` (cf. `activate`, which likewise materialises new delivery rows
    # while returning the updated subscription). The 2xx + envelope contract of PRD 2.2 is
    # asserted; the contested exact code is not.
    get_success_data(
        api.split_lot(
            landing["lot_id"],
            {
                "destinations": [
                    hub_destination(hub["id"], 2.50),
                    route_destination(zone["id"], 2.50),
                ]
            },
            ADMIN,
        )
    )

    rows, meta = validate_paginated(api.list_sub_lots(ADMIN, {"landing_lot_id": landing["lot_id"]}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False

    by_type = {row["destination_type"]: row for row in rows}
    assert by_type["HUB"]["pickup_hub_id"] == hub["id"]
    assert float(by_type["HUB"]["pounds"]) == pytest.approx(2.50)
    assert by_type["ROUTE"]["delivery_zone_id"] == zone["id"]
    assert float(by_type["ROUTE"]["pounds"]) == pytest.approx(2.50)
    for row in rows:
        assert row["status"] == "IN_TRANSIT"
        assert row["landing_lot_id"] == landing["lot_id"]

    lot = read_lot(landing["lot_id"])
    assert float(lot["split_pounds_total"]) == pytest.approx(5.00)
    assert lot["status"] == "SPLIT"
    assert_split_mass_invariant(lot, rows)


def test_the_last_sub_lot_arriving_bubbles_the_lot_to_dispatched(api):
    """PRD 3.4: "Hub staff record a consignment's arrival, moving that sub-lot `IN_TRANSIT →
    ARRIVED`; the move is refused while the parent lot's `quality_status` is `DISCARDED`. When
    no sub-lot of a lot remains `IN_TRANSIT`, the lot itself moves `SPLIT → DISPATCHED`."

    Design: Corner/state_machines/sub_lot_arrival_bubbles_the_lot_to_dispatched
    """
    ctx = setup_open_season(offered_species=("SALMON",))
    hub = new_hub()
    setup_member_subscription(
        ctx["season_id"],
        ctx["plan"]["id"],
        join_week_index=1,
        fulfillment_mode="HUB_PICKUP",
        pickup_hub_id=hub["id"],
    )
    fleet = setup_fleet(ctx["season_id"], species="SALMON")
    landing = setup_landed_lot(ctx["season_id"], fleet, "SALMON", 5.00)
    allocate(landing["lot_id"], 1, landing["lot"]["version"])
    split_lot(landing["lot_id"], [hub_destination(hub["id"], 5.00)])
    sub_lot = sub_lots_of(landing["lot_id"])[0]

    arrived = arrive_sub_lot(sub_lot["id"])
    assert arrived["status"] == "ARRIVED"
    assert float(read_sub_lot(sub_lot["id"])["pounds"]) == pytest.approx(5.00)

    lot = read_lot(landing["lot_id"])
    assert lot["status"] == "DISPATCHED"
    assert float(lot["split_pounds_total"]) == pytest.approx(5.00)
