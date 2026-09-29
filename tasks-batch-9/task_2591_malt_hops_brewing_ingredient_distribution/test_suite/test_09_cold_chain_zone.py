"""Zone capacity as an aggregate sweep, and pallet space as a conserved ledger."""
import pytest

from test_helpers import (
    WH_HEADERS,
    add_spot_hop_line,
    approve_credit,
    confirm_order,
    create_brewer,
    create_order,
    create_variety,
    create_zone,
    get_zone,
    order_version,
    pick_order,
    pin_clock,
    stage_shipment,
    validate_error,
    validate_paginated,
    validate_success,
)

MORNING = "2026-08-01T08:00:00Z"
NOON = "2026-08-01T12:00:00Z"
EARLY_AFTERNOON = "2026-08-01T14:00:00Z"
AFTERNOON = "2026-08-01T16:00:00Z"
EVENING = "2026-08-01T20:00:00Z"
MIDNIGHT = "2026-08-02T00:00:00Z"


def stage_attempt(api, order_id, zone_id, pallet_count, stage_from, stage_until):
    """Post a staging request raw, so a refusal can be inspected."""
    payload = {
        "sales_order_id": order_id,
        "cold_storage_zone_id": zone_id,
        "expected_sales_order_version": order_version(order_id),
        "pallet_count": pallet_count,
        "stage_from": stage_from,
        "stage_until": stage_until,
        "reefer_setpoint_c": 2.00,
        "reefer_tolerance_c": 2.00,
    }
    return api.stage_shipment(payload, WH_HEADERS)


@pytest.fixture
def zone_with_four_draft_orders():
    """One 10-pallet zone and four separate one-line reefer orders A, B, C, D.

    Each order carries a single 880 lb SPOT Citra line, so each is a cold-chain
    order that may be staged; the orders are left in DRAFT because only departure
    reads the fulfillment dimension.
    """
    pin_clock()
    brewer = create_brewer(name="Pallet Tetris Brewing", credit_limit_cents=5000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    variety = create_variety()
    zone = create_zone(zone_code="Z1", temp_setpoint_c=2.0, capacity_pallets=10,
                       tolerance_c=2.0)
    orders = {}
    for tag in ("a", "b", "c", "d"):
        order = create_order(brewer["id"],
                            requested_ship_date="2026-09-20T00:00:00Z",
                            purchase_order_ref=f"PO-TETRIS-{tag.upper()}")
        add_spot_hop_line(order["id"], brewer["id"], variety["id"], 880)
        orders[tag] = order
    return {"brewer": brewer, "variety": variety, "zone": zone, "orders": orders}


def test_a_sub_interval_sum_above_capacity_refuses_the_candidate_load(
        api, zone_with_four_draft_orders):
    """6 pallets over 08:00-16:00 admit; 5 more over 12:00-20:00 would sum to 11.

    PRD §3.9: "collect the boundary instants of the candidate plus every `STAGED`
    load in the zone; for each resulting sub-interval, sum `pallet_count` over
    every load whose half-open interval covers it; and refuse with
    `ERR_ZONE_CAPACITY_EXCEEDED` when any sub-interval's sum exceeds
    `capacity_pallets`"

    Design: Difficulty/resource_temporal_overlap/zone_capacity_swept_over_half_open_staging_intervals
    """
    world = zone_with_four_draft_orders
    zone_id = world["zone"]["id"]
    first = stage_shipment(world["orders"]["a"]["id"], zone_id, pallet_count=6,
                           stage_from=MORNING, stage_until=AFTERNOON,
                           reefer_tolerance_c=2.00)
    assert first["status"] == "STAGED", (
        f"6 of 10 pallets is admissible, got {first['status']}")

    refused = stage_attempt(api, world["orders"]["b"]["id"], zone_id, 5,
                            NOON, EVENING)
    validate_error(refused, "ERR_ZONE_CAPACITY_EXCEEDED", expected_status=409)

    data, meta = validate_paginated(api.list_shipments(
        WH_HEADERS, params={"sales_order_id": world["orders"]["b"]["id"]}))
    assert meta["total_count"] == 0, (
        f"a refused staging must persist no load, got {meta['total_count']}")
    assert data == [], f"order B owns no reefer load, got {data}"

    still = validate_success(api.get_shipment(first["id"], WH_HEADERS))
    assert still["status"] == "STAGED", (
        f"the admitted load is untouched by the refusal, got {still['status']}")
    assert still["pallet_count"] == 6, (
        f"its pallet count is unchanged, got {still['pallet_count']}")
    assert get_zone(zone_id)["capacity_pallets"] == 10, (
        "capacity is never mutated to model occupancy, got "
        f"{get_zone(zone_id)['capacity_pallets']}")


def test_a_load_starting_at_the_instant_another_ends_does_not_overlap_it(
        api, zone_with_four_draft_orders):
    """08:00-16:00 and 16:00-24:00 share an endpoint, so 6 + 5 never coexist.

    PRD §3.9: "Each `STAGED` load occupies its `pallet_count` over the
    **half-open** interval from `stage_from` inclusive to `stage_until`
    exclusive, so a load that vacates at exactly the instant another arrives does
    not overlap it and back-to-back staging with a zero gap is always permitted
    regardless of capacity."

    Design: Difficulty/resource_temporal_overlap/zone_capacity_swept_over_half_open_staging_intervals
    """
    world = zone_with_four_draft_orders
    zone_id = world["zone"]["id"]
    first = stage_shipment(world["orders"]["a"]["id"], zone_id, pallet_count=6,
                           stage_from=MORNING, stage_until=AFTERNOON,
                           reefer_tolerance_c=2.00)

    back_to_back = validate_success(stage_attempt(
        api, world["orders"]["c"]["id"], zone_id, 5, AFTERNOON, MIDNIGHT),
        expected_status=201)
    assert back_to_back["status"] == "STAGED", (
        f"the abutting window is admitted, got {back_to_back['status']}")
    assert back_to_back["excursion_minutes"] == 0, (
        f"a fresh load starts clean, got {back_to_back['excursion_minutes']}")
    assert back_to_back["reading_count"] == 0, (
        f"no telemetry has arrived yet, got {back_to_back['reading_count']}")

    earlier = validate_success(api.get_shipment(first["id"], WH_HEADERS))
    assert earlier["status"] == "STAGED", (
        "loads on different orders never supersede each other, got "
        f"{earlier['status']}")


def test_a_sub_interval_sum_exactly_at_capacity_is_admitted(
        api, zone_with_four_draft_orders):
    """6 + 4 over 12:00-14:00 is exactly 10 against a capacity of 10.

    PRD §3.9: "A sum exactly equal to `capacity_pallets` is accepted; only a
    strict excess is refused."

    Design: Difficulty/resource_temporal_overlap/zone_capacity_swept_over_half_open_staging_intervals
    """
    world = zone_with_four_draft_orders
    zone_id = world["zone"]["id"]
    stage_shipment(world["orders"]["a"]["id"], zone_id, pallet_count=6,
                   stage_from=MORNING, stage_until=AFTERNOON,
                   reefer_tolerance_c=2.00)

    exact = validate_success(stage_attempt(
        api, world["orders"]["d"]["id"], zone_id, 4, NOON, EARLY_AFTERNOON),
        expected_status=201)
    assert exact["status"] == "STAGED", (
        f"equality is accepted, not refused, got {exact['status']}")
    assert exact["pallet_count"] == 4, (
        f"the load records its own 4 pallets, got {exact['pallet_count']}")
    assert get_zone(zone_id)["capacity_pallets"] == 10, (
        "the 6 + 4 sum touches capacity without changing it, got "
        f"{get_zone(zone_id)['capacity_pallets']}")


def test_reported_occupancy_covers_only_the_window_holding_the_clock(
        api, zone_with_four_draft_orders):
    """Three admitted loads, none of whose windows contains 2026-08-01T00:00:00Z.

    PRD §3.9: "A zone's `occupied_pallets` is the sum of `pallet_count` over
    `STAGED` loads in the zone whose interval covers the **current logical
    clock**, meaning `stage_from` at or before the clock and `stage_until`
    strictly after it; it is recomputed whenever a zone is fetched."

    Design: Difficulty/resource_temporal_overlap/zone_capacity_swept_over_half_open_staging_intervals
    """
    world = zone_with_four_draft_orders
    zone_id = world["zone"]["id"]
    stage_shipment(world["orders"]["a"]["id"], zone_id, pallet_count=6,
                   stage_from=MORNING, stage_until=AFTERNOON,
                   reefer_tolerance_c=2.00)
    validate_success(stage_attempt(api, world["orders"]["c"]["id"], zone_id, 5,
                                   AFTERNOON, MIDNIGHT), expected_status=201)
    validate_success(stage_attempt(api, world["orders"]["d"]["id"], zone_id, 4,
                                   NOON, EARLY_AFTERNOON), expected_status=201)

    zone = get_zone(zone_id)
    assert zone["occupied_pallets"] == 0, (
        "no staging window contains the midnight clock, so the reported figure "
        f"is 0 rather than 15, got {zone['occupied_pallets']}")
    assert zone["capacity_pallets"] == 10, (
        f"capacity is unchanged by three admissions, got {zone['capacity_pallets']}")

    _, meta = validate_paginated(api.list_shipments(
        WH_HEADERS, params={"cold_storage_zone_id": zone_id}))
    assert meta["total_count"] == 3, (
        "three loads were admitted even though occupancy reads 0, got "
        f"{meta['total_count']}")


@pytest.fixture
def picked_reefer_order_in_a_live_window():
    """A PICKED 880 lb reefer order and an empty 10-pallet zone.

    The staging window runs from the pinned clock to the next midnight, so every
    accepted load contributes to the reported occupancy immediately and the
    pallet ledger is observable at each step.
    """
    pin_clock()
    brewer = create_brewer(name="Pallet Ledger Brewing", credit_limit_cents=5000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    variety = create_variety()
    zone = create_zone(zone_code="Z1", temp_setpoint_c=2.0, capacity_pallets=10,
                       tolerance_c=2.0)
    order = create_order(brewer["id"],
                         requested_ship_date="2026-09-10T00:00:00Z",
                         purchase_order_ref="PO-CONS-3")
    add_spot_hop_line(order["id"], brewer["id"], variety["id"], 880)
    order = confirm_order(order["id"], brewer["id"])
    approve_credit(order["id"], note="spot hops within limit")
    order = pick_order(order["id"])
    return {"brewer": brewer, "variety": variety, "zone": zone, "order": order}


def test_a_supersede_returns_the_old_loads_pallets_and_takes_the_new_count(
        api, picked_reefer_order_in_a_live_window):
    """4 out, then 4 back and 3 out: the zone ledger reads 3, never 7, 4 or 1.

    PRD §3.9: "Staging a new load moves any prior load on the same order in
    `STAGED` or `HELD` to `SUPERSEDED`, releasing its pallets"

    Design: Difficulty/compensating_invariant/zone_pallet_space_conserved_across_supersede_and_depart
    """
    world = picked_reefer_order_in_a_live_window
    zone_id = world["zone"]["id"]
    baseline = get_zone(zone_id)
    assert baseline["occupied_pallets"] == 0, (
        f"the zone starts empty, got {baseline['occupied_pallets']}")
    assert baseline["capacity_pallets"] == 10, (
        f"the zone holds ten pallets, got {baseline['capacity_pallets']}")

    first = stage_shipment(world["order"]["id"], zone_id, pallet_count=4,
                           stage_from="2026-08-01T00:00:00Z",
                           stage_until=MIDNIGHT, reefer_tolerance_c=2.00)
    assert first["status"] == "STAGED", (
        f"the first load is staged, got {first['status']}")
    assert get_zone(zone_id)["occupied_pallets"] == 4, (
        "the first load lends out four pallets, got "
        f"{get_zone(zone_id)['occupied_pallets']}")

    second = stage_shipment(world["order"]["id"], zone_id, pallet_count=3,
                            stage_from="2026-08-01T00:00:00Z",
                            stage_until=MIDNIGHT, reefer_tolerance_c=2.00)
    assert second["status"] == "STAGED", (
        f"the re-stage is admitted, got {second['status']}")

    superseded = validate_success(api.get_shipment(first["id"], WH_HEADERS))
    assert superseded["status"] == "SUPERSEDED", (
        f"the prior load on the same order is superseded, got {superseded['status']}")
    assert superseded["pallet_count"] == 4, (
        "superseding must not rewrite the older row's pallet count, got "
        f"{superseded['pallet_count']}")
    assert second["pallet_count"] == 3, (
        f"the newer load carries its own three pallets, got {second['pallet_count']}")

    zone = get_zone(zone_id)
    assert zone["occupied_pallets"] == 3, (
        "the released 4 and the newly taken 3 both post, so occupancy is 3 and "
        f"not 7, 4 or 1, got {zone['occupied_pallets']}")
    assert zone["capacity_pallets"] == 10, (
        f"capacity is never mutated to model occupancy, got {zone['capacity_pallets']}")


def test_departure_drains_the_pallet_ledger_back_to_its_starting_value(
        api, picked_reefer_order_in_a_live_window):
    """After the supersede and the departure the zone is exactly as it began.

    PRD §3.9: "The warehouse sends a `STAGED` load onto the road, moving it
    `STAGED → IN_TRANSIT` and releasing its `pallet_count` from the zone."

    Design: Difficulty/compensating_invariant/zone_pallet_space_conserved_across_supersede_and_depart
    """
    world = picked_reefer_order_in_a_live_window
    zone_id = world["zone"]["id"]
    first = stage_shipment(world["order"]["id"], zone_id, pallet_count=4,
                           stage_from="2026-08-01T00:00:00Z",
                           stage_until=MIDNIGHT, reefer_tolerance_c=2.00)
    second = stage_shipment(world["order"]["id"], zone_id, pallet_count=3,
                            stage_from="2026-08-01T00:00:00Z",
                            stage_until=MIDNIGHT, reefer_tolerance_c=2.00)
    assert get_zone(zone_id)["occupied_pallets"] == 3, (
        "only the surviving load occupies space before departure, got "
        f"{get_zone(zone_id)['occupied_pallets']}")

    departed = validate_success(api.depart_shipment(second["id"], WH_HEADERS))
    assert departed["status"] == "IN_TRANSIT", (
        f"the surviving load takes the road, got {departed['status']}")

    zone = get_zone(zone_id)
    assert zone["occupied_pallets"] == 0, (
        f"the space is fully returned, got {zone['occupied_pallets']}")
    assert zone["capacity_pallets"] == 10, (
        f"capacity is unchanged at every observation, got {zone['capacity_pallets']}")

    order = validate_success(api.get_sales_order(world["order"]["id"], WH_HEADERS))
    assert order["fulfillment_status"] == "PICKED", (
        "the shipment churn does not move the order, got "
        f"{order['fulfillment_status']}")
    assert order["total_cents"] == 95380, (
        f"44880 + 43000 freight + 7500 surcharge = 95380, got {order['total_cents']}")

    _, meta = validate_paginated(api.list_shipments(
        WH_HEADERS, params={"cold_storage_zone_id": zone_id}))
    assert meta["total_count"] == 2, (
        "the superseded row is retained as an audit record, got "
        f"{meta['total_count']}")
    assert validate_success(api.get_shipment(first["id"], WH_HEADERS))["status"] \
        == "SUPERSEDED", "the superseded load is still readable"
