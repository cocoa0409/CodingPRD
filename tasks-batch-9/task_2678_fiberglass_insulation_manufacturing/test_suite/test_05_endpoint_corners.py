"""Endpoint corners: the reference-data create/read/list/update surface, and the action
endpoints whose real effect lands on an entity other than the one addressed.

Queue B / endpoints.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    is_valid_uuid,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import InsulationApiClient
from test_helpers.api_errors import ApiErrors
from test_helpers.assertions import assert_close, assert_field_equals, ids_of
from test_helpers.constants import SKU_PL_A, SKU_PL_B, ZONES_470
from test_helpers.test_users import (
    channel_manager_headers,
    corporate_ops_headers,
    environmental_compliance_headers,
    plant_operator_headers,
)

# A phenolic chemistry whose cure envelope (420 F / 150 s) is reachable by the 470 F /
# 40 fpm line settings below, so a run can cure and still book formaldehyde mass.
PHENOLIC_420 = {
    "formaldehyde_free": False,
    "formaldehyde_ppm": 250,
    "voc_g_per_kg": 4.1,
    "min_cure_temp_f": 420.0,
    "min_dwell_s": 150.0,
    "loi_target_pct": 5.0,
}

CURE_470 = {
    "avg_zone_temp_f": 470.0,
    "line_speed_fpm": 40.0,
    "binder_applied_kg": 900.0,
}


def test_a_registered_plant_reads_back_and_lists_exactly_as_posted(
    client: InsulationApiClient,
) -> None:
    """PRD 3.1: "A newly registered plant begins with `melt_posture` `OPEN`,
    `posture_reason` null, `emissions_status` `COMPLIANT`, `version` 1, and every cullet
    and charge counter at zero."

    Design: Corner/endpoints/plant_and_sku_reference_data_supports_create_read_list_and_update
    """
    fx.reset_clock(client)
    payload = f.plant_payload()

    created = get_success_data(
        client.create_plant(payload, corporate_ops_headers()), 201
    )
    assert is_valid_uuid(created["id"]), created

    read = fx.get_plant(client, created["id"])
    for field, value in payload.items():
        if isinstance(value, float):
            assert_close(read[field], value, 4, field)
        else:
            assert_field_equals(read, field, value)

    assert_field_equals(read, "melt_posture", "OPEN")
    assert read["posture_reason"] is None, read
    assert_field_equals(read, "emissions_status", "COMPLIANT")
    assert_field_equals(read, "version", 1)
    for counter in (
        "cullet_received_kg_ytd",
        "cullet_charged_kg_ytd",
        "cullet_rejected_kg_ytd",
        "cullet_on_hand_kg",
        "total_charge_kg_ytd",
    ):
        assert_close(read[counter], 0.00, 2, counter)
    assert_close(read["cullet_fraction_ytd"], 0.0000, 4, "cullet_fraction_ytd")

    data, meta = validate_paginated(
        client.list_plants(corporate_ops_headers(), {"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 1, meta
    assert meta["has_more"] is False, meta
    assert ids_of(data) == [created["id"]], data


def test_the_packaging_patch_replaces_only_what_it_names_and_recomputes_the_block(
    client: InsulationApiClient,
) -> None:
    """PRD 3.3: "The caller may supply any subset of `compression_ratio`,
    `bale_volume_ft3`, `bale_mass_kg` and `bag_sqft`; the supplied fields replace their
    stored values and all six derived figures - `recovered_thickness_pct`,
    `compressed_bale_volume_ft3`, `bales_per_truck`, `freight_cost_per_sqft`,
    `recovery_penalty_per_sqft` and `net_landed_cost_per_sqft` - are recomputed from
    scratch by the five steps above."

    Design: Corner/endpoints/plant_and_sku_reference_data_supports_create_read_list_and_update
    """
    ctx = fx.base_setup(client, sku_overrides=dict(SKU_PL_A))
    sku = ctx["sku"]

    # Compression 6.0 is 2.0 points past the free ratio of 4.0, so 100 - 2 * 5 = 90.00,
    # and UNFACED carries no further 2-point facing penalty.
    assert_close(sku["recovered_thickness_pct"], 90.00, 2, "recovered_thickness_pct")
    assert_close(sku["compressed_bale_volume_ft3"], 3.500, 3, "compressed_bale_volume")
    # Volume bound floor(3800 / 3.5) = 1085 beats the payload bound floor(19500 / 12.5).
    assert_field_equals(sku, "bales_per_truck", 1085)
    assert_close(sku["freight_cost_per_sqft"], 0.025660, 6, "freight_cost_per_sqft")
    assert_close(sku["recovery_penalty_per_sqft"], 0.006000, 6, "recovery_penalty")
    assert_close(sku["net_landed_cost_per_sqft"], 0.031660, 6, "net_landed_cost")

    patched = get_success_data(
        client.patch_packaging(
            ctx["sku_id"],
            f.packaging_patch_payload(bale_mass_kg=13.0),
            corporate_ops_headers(),
        )
    )

    assert_close(patched["bale_mass_kg"], 13.0, 2, "bale_mass_kg")
    # The three packaging fields the PATCH did not name are left alone.
    assert_close(patched["compression_ratio"], 6.0, 1, "compression_ratio")
    assert_close(patched["bale_volume_ft3"], 21.0, 3, "bale_volume_ft3")
    assert_close(patched["bag_sqft"], 88.0, 2, "bag_sqft")

    # Recomputed from the new mass: the payload bound is now floor(19500 / 13.0) = 1500,
    # which still loses to the volume bound, so the whole derived block is unmoved.
    assert_close(patched["recovered_thickness_pct"], 90.00, 2, "recovered_thickness_pct")
    assert_close(patched["compressed_bale_volume_ft3"], 3.500, 3, "compressed_bale_vol")
    assert_field_equals(patched, "bales_per_truck", 1085)
    assert_close(patched["freight_cost_per_sqft"], 0.025660, 6, "freight_cost_per_sqft")
    assert_close(patched["recovery_penalty_per_sqft"], 0.006000, 6, "recovery_penalty")
    assert_close(patched["net_landed_cost_per_sqft"], 0.031660, 6, "net_landed_cost")
    assert_field_equals(patched, "certification_status", "DRAFT")


def _order_fully_backed_by_one_lot(client: InsulationApiClient) -> Dict[str, Any]:
    """One CERTIFIED SKU, one 120-bag lot, and one order holding all of its coverage."""
    ctx = fx.certified_sku_with_lot(client)
    order = fx.place_order(client, ctx["sku_id"], 10560.0)
    cycle = fx.open_cycle(client, ctx["plant_id"], ctx["sku_id"])
    line = fx.manual_line(client, cycle["id"], order["id"], ctx["lot_id"], 10560.0)
    ctx.update(
        {"order_id": order["id"], "cycle_id": cycle["id"], "line_id": line["id"]}
    )
    return ctx


def test_shipping_the_order_consumes_the_only_lot_standing_behind_it(
    client: InsulationApiClient,
) -> None:
    """PRD 3.7: "When an order ships, every lot backing it moves `ALLOCATED -> CONSUMED`
    with `available_sqft` forced to 0.00, but only for a lot on which every `ALLOCATED`
    allocation line belongs to the shipping order - a lot shared between two orders is not
    consumed by the first of them to ship."

    Design: Corner/endpoints/shipping_an_allocated_order_consumes_the_lot_behind_it
    """
    ctx = _order_fully_backed_by_one_lot(client)

    booked = fx.get_order(client, ctx["order_id"])
    assert_field_equals(booked, "status", "ALLOCATED")
    assert_close(booked["allocated_sqft"], 10560.00, 2, "allocated_sqft")
    assert_close(booked["fill_rate_pct"], 100.00, 2, "fill_rate_pct")
    drawn = fx.get_lot(client, ctx["lot_id"])
    assert_field_equals(drawn, "status", "ALLOCATED")
    assert_close(drawn["available_sqft"], 0.00, 2, "available_sqft")

    shipped = get_success_data(
        client.ship_order(
            ctx["order_id"],
            channel_manager_headers(),
            {"shipped_at": "2026-08-05T09:00:00Z"},
        )
    )

    assert_field_equals(shipped, "status", "SHIPPED")
    assert_close(shipped["allocated_sqft"], 10560.00, 2, "allocated_sqft")

    consumed = fx.get_lot(client, ctx["lot_id"])
    assert_field_equals(consumed, "status", "CONSUMED")
    assert_close(consumed["available_sqft"], 0.00, 2, "available_sqft")
    # produced_sqft is never mutated, so the coverage is still on the row.
    assert_close(consumed["produced_sqft"], 10560.00, 2, "produced_sqft")

    # Shipping does not revoke the line it shipped against.
    line = fx.get_line(client, ctx["line_id"])
    assert_field_equals(line, "status", "ALLOCATED")
    assert_close(line["allocated_sqft"], 10560.00, 2, "allocated_sqft")


def test_a_second_shipment_of_the_same_order_is_refused_as_a_terminal_repeat(
    client: InsulationApiClient,
) -> None:
    """PRD 2.8: "It equally covers every repeat of an already-applied trigger and every
    trigger aimed at a row already in a terminal state."

    Design: Corner/endpoints/shipping_an_allocated_order_consumes_the_lot_behind_it
    """
    ctx = _order_fully_backed_by_one_lot(client)
    get_success_data(client.ship_order(ctx["order_id"], channel_manager_headers()))

    replay = client.ship_order(ctx["order_id"], channel_manager_headers())
    validate_error(replay, ApiErrors.INVALID_STATE, 409)

    order = fx.get_order(client, ctx["order_id"])
    assert_field_equals(order, "status", "SHIPPED")
    lot = fx.get_lot(client, ctx["lot_id"])
    assert_field_equals(lot, "status", "CONSUMED")


def test_a_split_that_does_not_reproduce_the_parents_bags_creates_no_child(
    client: InsulationApiClient,
) -> None:
    """PRD 3.7: "The payload carries `child_bags`, an array of at least two elements, every
    element a positive whole number, and the elements summing to **exactly** the parent's
    `bags` so that the children's coverage reproduces the parent's `produced_sqft` to the
    square foot; a violation is refused with `ERR_BAG_MULTIPLE_MISMATCH`."

    Design: Corner/endpoints/repacking_splits_one_lot_into_children_whose_coverage_sums_to_the_parent
    """
    ctx = fx.certified_sku_with_lot(client)
    operator = plant_operator_headers(ctx["plant_id"])

    # 70 + 40 = 110 bags falls short of the parent's 120.
    validate_error(
        client.repack_lot(ctx["lot_id"], [70, 40], operator),
        ApiErrors.BAG_MULTIPLE_MISMATCH,
        422,
    )
    # 70 + 60 = 130 bags overshoots it by the same rule.
    validate_error(
        client.repack_lot(ctx["lot_id"], [70, 60], operator),
        ApiErrors.BAG_MULTIPLE_MISMATCH,
        422,
    )

    # A rejected split is all-or-nothing: not one child survives either attempt.
    assert fx.child_lots(client, ctx["lot_id"]) == [], "no child may be created"

    parent = fx.get_lot(client, ctx["lot_id"])
    assert_field_equals(parent, "status", "AVAILABLE")
    assert_field_equals(parent, "bags", 120)
    assert_close(parent["available_sqft"], 10560.00, 2, "available_sqft")


def test_the_accepted_split_conserves_every_square_foot_of_the_parent(
    client: InsulationApiClient,
) -> None:
    """PRD 3.7: "On success the parent moves `AVAILABLE -> REPACKED`, a terminal state, with
    `available_sqft` forced to 0.00, and one child lot is created per element with
    `parent_lot_id` pointing at the parent, status `AVAILABLE`, `bags` equal to that element
    and `produced_sqft` equal to the element multiplied by the SKU's `bag_sqft`."

    Design: Corner/endpoints/repacking_splits_one_lot_into_children_whose_coverage_sums_to_the_parent
    """
    ctx = fx.certified_sku_with_lot(client)
    operator = plant_operator_headers(ctx["plant_id"])

    get_success_data(client.repack_lot(ctx["lot_id"], [70, 50], operator))

    parent = fx.get_lot(client, ctx["lot_id"])
    assert_field_equals(parent, "status", "REPACKED")
    assert_close(parent["available_sqft"], 0.00, 2, "available_sqft")
    assert_close(parent["produced_sqft"], 10560.00, 2, "produced_sqft")

    children = fx.child_lots(client, ctx["lot_id"])
    assert len(children) == 2, children
    for child in children:
        assert_field_equals(child, "parent_lot_id", ctx["lot_id"])
        assert_field_equals(child, "status", "AVAILABLE")
        assert_close(child["allocated_sqft"], 0.00, 2, "allocated_sqft")
    assert sorted(child["bags"] for child in children) == [50, 70], children
    coverage = sorted(round(child["produced_sqft"], 2) for child in children)
    # 50 * 88.0 and 70 * 88.0, and the two together are the parent to the square foot.
    assert_close(coverage[0], 4400.00, 2, "smaller child produced_sqft")
    assert_close(coverage[1], 6160.00, 2, "larger child produced_sqft")
    assert_close(coverage[0] + coverage[1], 10560.00, 2, "conserved coverage")

    replay = client.repack_lot(ctx["lot_id"], [60, 60], operator)
    validate_error(replay, ApiErrors.INVALID_STATE, 409)


def _cycle_order_and_lot(client: InsulationApiClient) -> Dict[str, Any]:
    """An OPEN cycle, one 8800.00 sqft retail order and one 120-bag lot to draw from."""
    ctx = fx.certified_sku_with_lot(client)
    order = fx.place_order(client, ctx["sku_id"], 8800.0, channel_type="RETAIL")
    cycle = fx.open_cycle(client, ctx["plant_id"], ctx["sku_id"])
    ctx.update({"order_id": order["id"], "cycle_id": cycle["id"]})
    return ctx


def test_each_row_a_manual_line_references_is_resolved_on_its_own_account(
    client: InsulationApiClient,
) -> None:
    """PRD 2.9: "Body foreign keys are resolved only after the request shape has been
    accepted, and they are resolved in the order the endpoint declares them."

    Design: Corner/endpoints/a_manual_allocation_line_requires_all_three_referenced_rows_to_exist
    """
    ctx = _cycle_order_and_lot(client)
    version = int(fx.get_cycle(client, ctx["cycle_id"])["version"])
    manager = channel_manager_headers()

    # The declared order is allocation_cycle_id, then channel_order_id, then
    # inventory_lot_id, and each unresolved identifier carries its own 404.
    missing_cycle = client.create_allocation_line(
        f.allocation_line_payload(
            NON_EXISTENT_UUID, ctx["order_id"], ctx["lot_id"], 8800.0, version
        ),
        manager,
    )
    validate_error(missing_cycle, ApiErrors.ALLOCATION_CYCLE_NOT_FOUND, 404)

    missing_order = client.create_allocation_line(
        f.allocation_line_payload(
            ctx["cycle_id"], NON_EXISTENT_UUID, ctx["lot_id"], 8800.0, version
        ),
        manager,
    )
    validate_error(missing_order, ApiErrors.CHANNEL_ORDER_NOT_FOUND, 404)

    missing_lot = client.create_allocation_line(
        f.allocation_line_payload(
            ctx["cycle_id"], ctx["order_id"], NON_EXISTENT_UUID, 8800.0, version
        ),
        manager,
    )
    validate_error(missing_lot, ApiErrors.INVENTORY_LOT_NOT_FOUND, 404)

    assert fx.lines_for_cycle(client, ctx["cycle_id"]) == [], "no line may exist yet"
    order = fx.get_order(client, ctx["order_id"])
    assert_field_equals(order, "status", "SUBMITTED")
    assert_close(order["allocated_sqft"], 0.00, 2, "allocated_sqft")


def test_the_resolved_line_books_both_ledgers_without_proposing_the_cycle(
    client: InsulationApiClient,
) -> None:
    """PRD 3.8: "Because a manual line is booked immediately rather than reserved, it can
    flip an order to `ALLOCATED` and a lot to `ALLOCATED` without any commit."

    Design: Corner/endpoints/a_manual_allocation_line_requires_all_three_referenced_rows_to_exist
    """
    ctx = _cycle_order_and_lot(client)
    version = int(fx.get_cycle(client, ctx["cycle_id"])["version"])

    line = fx.manual_line(
        client,
        ctx["cycle_id"],
        ctx["order_id"],
        ctx["lot_id"],
        8800.0,
        expected_version=version,
    )

    assert_field_equals(line, "status", "ALLOCATED")
    # 8800.00 / 88.0 is a whole 100 bags.
    assert_field_equals(line, "bags", 100)
    assert_close(line["allocated_sqft"], 8800.00, 2, "allocated_sqft")

    order = fx.get_order(client, ctx["order_id"])
    assert_field_equals(order, "status", "ALLOCATED")
    assert_close(order["allocated_sqft"], 8800.00, 2, "allocated_sqft")
    assert_close(order["fill_rate_pct"], 100.00, 2, "fill_rate_pct")

    lot = fx.get_lot(client, ctx["lot_id"])
    # 10560.00 produced less 8800.00 booked leaves the lot live with 1760.00 to give.
    assert_close(lot["allocated_sqft"], 8800.00, 2, "allocated_sqft")
    assert_close(lot["available_sqft"], 1760.00, 2, "available_sqft")
    assert_field_equals(lot, "status", "AVAILABLE")

    cycle = fx.get_cycle(client, ctx["cycle_id"])
    assert_field_equals(cycle, "status", "OPEN")
    assert int(cycle["version"]) > version, cycle
    assert_close(cycle["allocated_sqft"], 8800.00, 2, "allocated_sqft")


def _proposed_october_cycle(client: InsulationApiClient) -> Dict[str, Any]:
    """A PROPOSED cycle over October - an off-peak month - fed by one 10560.00 sqft lot."""
    ctx = fx.certified_sku_with_lot(client)
    order = fx.place_order(
        client, ctx["sku_id"], 8800.0, required_by="2026-10-20T00:00:00Z"
    )
    cycle = fx.open_cycle(
        client,
        ctx["plant_id"],
        ctx["sku_id"],
        period_start="2026-10-01T00:00:00Z",
        period_end="2026-11-01T00:00:00Z",
    )
    ctx.update({"order_id": order["id"], "cycle_id": cycle["id"]})
    ctx["proposed"] = fx.propose_cycle(client, cycle["id"])
    return ctx


def test_an_october_cycle_reads_back_the_off_peak_reserve_arithmetic(
    client: InsulationApiClient,
) -> None:
    """PRD 3.8: "`seasonal_reserve_sqft` is `total_available_sqft` multiplied by 0.15 in peak
    season and by 0.05 off peak, quantized to two decimal places, and `allocatable_sqft` is
    `total_available_sqft` less that reserve, quantized to two decimal places."

    PRD 3.8: "`shortage_ratio` measures how much of the ask can be met: it is
    `allocatable_sqft` divided by `total_requested_sqft`, quantized to four decimal places,
    and then **capped at 1.0000** so that an abundant cycle reports exactly 1.0000 rather
    than a number above one."

    Design: Corner/endpoints/reading_a_proposed_cycle_returns_the_off_peak_reserve_arithmetic
    """
    ctx = _proposed_october_cycle(client)

    cycle = fx.get_cycle(client, ctx["cycle_id"])
    assert_field_equals(cycle, "status", "PROPOSED")
    # October is none of March through September.
    assert_field_equals(cycle, "peak_season", False)
    assert_close(cycle["total_available_sqft"], 10560.00, 2, "total_available_sqft")
    # 10560.00 * 0.05 off peak, where the peak figure would have been 1584.00.
    assert_close(cycle["seasonal_reserve_sqft"], 528.00, 2, "seasonal_reserve_sqft")
    assert_close(cycle["allocatable_sqft"], 10032.00, 2, "allocatable_sqft")
    assert_close(cycle["total_requested_sqft"], 8800.00, 2, "total_requested_sqft")
    # The raw 10032.00 / 8800.00 is 1.14, clamped rather than stored as 1.1400.
    assert_close(cycle["shortage_ratio"], 1.0000, 4, "shortage_ratio")
    # CONTRACT_FIRST grants floor(8800.00 / 88.0) = 100 whole bags out of the pool.
    assert_close(cycle["allocated_sqft"], 8800.00, 2, "allocated_sqft")
    assert_close(cycle["unallocated_sqft"], 1232.00, 2, "unallocated_sqft")


def test_the_proposal_reserves_coverage_without_moving_the_lot_or_the_order(
    client: InsulationApiClient,
) -> None:
    """PRD 3.7: "Lines in `PROPOSED` are reservations only and are **excluded** from the sum,
    as are `REVOKED` lines - so a proposed-but-uncommitted cycle leaves inventory fully
    available."

    Design: Corner/endpoints/reading_a_proposed_cycle_returns_the_off_peak_reserve_arithmetic
    """
    ctx = _proposed_october_cycle(client)

    lines = fx.lines_for_cycle(client, ctx["cycle_id"])
    assert len(lines) == 1, lines
    line = lines[0]
    assert_field_equals(line, "status", "PROPOSED")
    assert_field_equals(line, "channel_order_id", ctx["order_id"])
    assert_field_equals(line, "inventory_lot_id", ctx["lot_id"])
    assert_close(line["allocated_sqft"], 8800.00, 2, "allocated_sqft")
    assert_field_equals(line, "bags", 100)

    lot = fx.get_lot(client, ctx["lot_id"])
    assert_field_equals(lot, "status", "AVAILABLE")
    assert_close(lot["allocated_sqft"], 0.00, 2, "allocated_sqft")
    assert_close(lot["available_sqft"], 10560.00, 2, "available_sqft")

    order = fx.get_order(client, ctx["order_id"])
    assert_field_equals(order, "status", "SUBMITTED")
    assert_close(order["allocated_sqft"], 0.00, 2, "allocated_sqft")
    assert_close(order["fill_rate_pct"], 0.00, 2, "fill_rate_pct")


def _frozen_plant(client: InsulationApiClient) -> Dict[str, Any]:
    """A plant frozen by an over-allowance period, with one held run on a spared SKU.

    PL-A runs on the phenolic chemistry and books 0.2250 kg of formaldehyde against a
    0.200 kg allowance; PL-B runs on the formaldehyde-free one and is scheduled only.
    """
    fx.reset_clock(client)
    program = fx.create_per_specimen_program(client)
    plant = fx.create_plant(client)
    phenolic = fx.create_certified_binder(client, **PHENOLIC_420)
    free = fx.create_certified_formaldehyde_free_binder(client)
    sku_a = fx.create_product_line(
        client, plant["id"], phenolic["id"], program["id"], **SKU_PL_A
    )
    sku_b = fx.create_product_line(
        client, plant["id"], free["id"], program["id"], **SKU_PL_B
    )
    run_a = fx.run_to_curing(
        client,
        plant["id"],
        sku_a["id"],
        line_index=1,
        zone_setpoints_f=list(ZONES_470),
        cure_overrides=dict(CURE_470),
    )
    run_b = fx.schedule_run(
        client,
        plant["id"],
        sku_b["id"],
        line_index=2,
        scheduled_start="2026-08-05T06:00:00Z",
        scheduled_end="2026-08-05T14:00:00Z",
        zone_setpoints_f=list(ZONES_470),
    )
    fx.set_clock(client, "2026-08-04T00:00:00Z")
    frozen = fx.file_emissions_report(
        client, plant["id"], "2026-08-01T00:00:00Z", "2026-08-03T06:00:00Z"
    )
    return {
        "plant_id": plant["id"],
        "phenolic_id": phenolic["id"],
        "free_id": free["id"],
        "sku_a_id": sku_a["id"],
        "sku_b_id": sku_b["id"],
        "run_a_id": run_a["id"],
        "run_b_id": run_b["id"],
        "frozen": frozen,
    }


def test_the_over_allowance_period_freezes_the_plant_and_holds_its_scheduled_run(
    client: InsulationApiClient,
) -> None:
    """PRD 3.9: "Every `CERTIFIED` binder formulation whose `formaldehyde_free` flag is false
    and which is used by a SKU of this plant transitions to `SUSPENDED` - formaldehyde-free
    chemistries are deliberately spared, since they cannot be the source of a formaldehyde
    exceedance."

    Design: Corner/endpoints/clearing_a_frozen_plant_is_conditional_and_does_not_release_its_held_runs
    """
    ctx = _frozen_plant(client)
    frozen = ctx["frozen"]

    assert_field_equals(frozen, "emissions_status", "EXCEEDANCE")
    assert_field_equals(frozen, "melt_posture", "FROZEN")
    assert_field_equals(frozen, "posture_reason", "EMISSIONS_EXCEEDANCE")
    # 900.0 kg of binder at 250 ppm books 0.2250 kg against a 0.200 kg allowance.
    assert_close(frozen["reported_formaldehyde_kg"], 0.2250, 4, "reported_formaldehyde")
    assert_close(frozen["reported_voc_kg"], 3.6900, 4, "reported_voc_kg")

    phenolic = get_success_data(
        client.get_binder_formulation(ctx["phenolic_id"], corporate_ops_headers())
    )
    assert_field_equals(phenolic, "status", "SUSPENDED")
    spared = get_success_data(
        client.get_binder_formulation(ctx["free_id"], corporate_ops_headers())
    )
    assert_field_equals(spared, "status", "CERTIFIED")

    sku_a = fx.get_product_line(client, ctx["sku_a_id"])
    assert_field_equals(sku_a, "certification_status", "SUSPENDED")
    sku_b = fx.get_product_line(client, ctx["sku_b_id"])
    assert_field_equals(sku_b, "certification_status", "DRAFT")

    held = fx.get_run(client, ctx["run_b_id"])
    assert_field_equals(held, "run_status", "HELD")
    assert_field_equals(held, "hold_reason", "PLANT_FROZEN")
    curing = fx.get_run(client, ctx["run_a_id"])
    assert_field_equals(curing, "run_status", "CURING")

    # Staging is blocked entirely while the plant is FROZEN.
    refused = client.create_cullet_batch(
        f.cullet_batch_payload(
            ctx["plant_id"], 500.0, fx.plant_version(client, ctx["plant_id"])
        ),
        plant_operator_headers(ctx["plant_id"]),
    )
    validate_error(refused, ApiErrors.MELT_POSTURE_FROZEN, 409)


def test_a_recompute_review_cannot_clear_a_frozen_plant(
    client: InsulationApiClient,
) -> None:
    """PRD 3.1: "`RESTRICTED` returns to `OPEN` only through an `EnvironmentalCompliance`
    posture review carrying a `decision` of `RECOMPUTE`, which is permitted only while the
    plant is currently `RESTRICTED` and only if `cullet_fraction_ytd` has fallen **strictly
    below** `cullet_restrict_fraction` by review time; `override_reason` must be omitted on a
    `RECOMPUTE`."

    Design: Corner/endpoints/clearing_a_frozen_plant_is_conditional_and_does_not_release_its_held_runs
    """
    ctx = _frozen_plant(client)

    refused = client.posture_review(
        ctx["plant_id"],
        f.posture_review_payload("RECOMPUTE"),
        environmental_compliance_headers(),
    )
    validate_error(refused, ApiErrors.INVALID_STATE, 409)

    plant = fx.get_plant(client, ctx["plant_id"])
    assert_field_equals(plant, "melt_posture", "FROZEN")
    assert_field_equals(plant, "posture_reason", "EMISSIONS_EXCEEDANCE")


def test_the_override_clears_the_posture_and_leaves_the_hold_for_an_explicit_release(
    client: InsulationApiClient,
) -> None:
    """PRD 3.1: "A `FROZEN` plant returns to `OPEN` only through an
    `EnvironmentalCompliance` posture review carrying a `decision` of `OVERRIDE_TO_OPEN`,
    which requires a non-empty `override_reason`; the supplied text is stored on the plant,
    `posture_reason` becomes `MANUAL_OVERRIDE`, `version` is incremented, and - critically -
    the `emissions_status` dimension is left exactly where it was and runs the freeze put on
    hold are **not** released automatically."

    Design: Corner/endpoints/clearing_a_frozen_plant_is_conditional_and_does_not_release_its_held_runs
    """
    ctx = _frozen_plant(client)
    before = fx.get_plant(client, ctx["plant_id"])

    cleared = fx.posture_review(
        client,
        ctx["plant_id"],
        "OVERRIDE_TO_OPEN",
        override_reason="permit amendment filed with the state",
    )

    assert_field_equals(cleared, "melt_posture", "OPEN")
    assert_field_equals(cleared, "posture_reason", "MANUAL_OVERRIDE")
    assert_field_equals(cleared, "override_reason", "permit amendment filed with the state")
    # The other dimension is untouched: the period stays reported as an exceedance.
    assert_field_equals(cleared, "emissions_status", "EXCEEDANCE")
    assert int(cleared["version"]) == int(before["version"]) + 1, cleared

    still_held = fx.get_run(client, ctx["run_b_id"])
    assert_field_equals(still_held, "run_status", "HELD")
    assert_field_equals(still_held, "hold_reason", "PLANT_FROZEN")

    released = get_success_data(
        client.release_hold(
            ctx["run_b_id"], plant_operator_headers(ctx["plant_id"])
        )
    )
    assert_field_equals(released, "run_status", "SCHEDULED")
    assert released["hold_reason"] is None, released
