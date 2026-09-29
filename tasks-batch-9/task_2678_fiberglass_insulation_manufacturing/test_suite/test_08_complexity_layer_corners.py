"""Complexity layers: the two optimistic-concurrency guards, and the derived
coverage ledgers that two parents rebuild after every allocation-line event.

Queue B / complexity_layers.
"""

from typing import Any, Dict, List, Tuple

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import InsulationApiClient
from test_helpers.api_errors import ApiErrors
from test_helpers.assertions import assert_area, assert_close, assert_field_equals, assert_mass
from test_helpers.test_users import channel_manager_headers, plant_operator_headers

# 50 bags and 25 bags of the 88.00 sqft bag the default SKU declares (PRD 2.11).
FULL_TRANCHE = 4400.00
HALF_TRANCHE = 2200.00
LOT_SQFT = 10560.00


def _cycle_ready_scenario(
    client: InsulationApiClient, order_count: int = 1
) -> Dict[str, Any]:
    """Certified SKU, one AVAILABLE lot of 10560.00 sqft, N orders, one OPEN cycle."""
    ctx = fx.certified_sku_with_lot(client, bags_produced=120)
    assert_field_equals(ctx["lot"], "status", "AVAILABLE")
    assert_area(ctx["lot"]["produced_sqft"], LOT_SQFT, "lot.produced_sqft")
    ctx["orders"] = [
        fx.place_order(client, ctx["sku_id"], FULL_TRANCHE) for _ in range(order_count)
    ]
    cycle = fx.open_cycle(client, ctx["plant_id"], ctx["sku_id"])
    assert_field_equals(cycle, "status", "OPEN")
    assert_field_equals(cycle, "allocation_basis", "CONTRACT_FIRST")
    ctx["cycle"] = cycle
    ctx["cycle_id"] = cycle["id"]
    ctx["cycle_v0"] = int(cycle["version"])
    return ctx


def _cut_line(
    client: InsulationApiClient,
    ctx: Dict[str, Any],
    order_id: str,
    sqft: float,
    expected_version: int,
):
    """The raw response of a manual expedite line, so a refusal can be inspected."""
    return client.create_allocation_line(
        f.allocation_line_payload(
            ctx["cycle_id"], order_id, ctx["lot_id"], sqft, expected_version
        ),
        channel_manager_headers(),
    )


def _assert_coverage_conserved(
    client: InsulationApiClient, lot_id: str, label: str
) -> Dict[str, Any]:
    """PRD 2.11 conservation, read straight off the single live lot of the SKU."""
    lot = fx.get_lot(client, lot_id)
    total = round(float(lot["allocated_sqft"]) + float(lot["available_sqft"]), 2)
    assert_area(lot["produced_sqft"], LOT_SQFT, f"{label}: produced_sqft")
    assert abs(total - LOT_SQFT) < 0.005, (
        f"{label}: allocated_sqft + available_sqft == {total}, expected {LOT_SQFT}"
    )
    return lot


# ---------------------------------------------------------------------------
# The allocation cycle's version guards its children.
# ---------------------------------------------------------------------------


def test_a_stale_expected_allocation_cycle_version_is_refused_and_writes_nothing(
    client: InsulationApiClient,
) -> None:
    """PRD 2.6: "Cutting a manual allocation line requires
    `expected_allocation_cycle_version` as a mandatory field carrying the client's last
    observed `version` of the target `AllocationCycle`. If that value does not equal the
    cycle's current `version`, the request is rejected with
    `ERR_STALE_ALLOCATION_CYCLE_VERSION` and HTTP 412."

    Design: Corner/complexity_layers/a_stale_expected_allocation_cycle_version_is_refused_and_a_refreshed_one_succeeds
    """
    ctx = _cycle_ready_scenario(client, order_count=2)
    v0 = ctx["cycle_v0"]
    order1, order2 = ctx["orders"][0]["id"], ctx["orders"][1]["id"]

    first = validate_success(_cut_line(client, ctx, order1, FULL_TRANCHE, v0), 201)
    assert_field_equals(first, "status", "ALLOCATED")
    assert_area(first["allocated_sqft"], FULL_TRANCHE, "line1.allocated_sqft")
    assert_field_equals(first, "bags", 50)
    # The PARENT's version advances on a child write, which is what goes stale.
    assert_field_equals(fx.get_cycle(client, ctx["cycle_id"]), "version", v0 + 1)

    # A second line for the OTHER order is legitimate business behaviour - the lot still
    # holds 6160.00 sqft - so only the stale token can explain a refusal.
    refused = _cut_line(client, ctx, order2, FULL_TRANCHE, v0)
    validate_error(refused, ApiErrors.STALE_ALLOCATION_CYCLE_VERSION)
    assert refused.status_code == 412, (
        f"a stale cycle version is a 412, got {refused.status_code}"
    )

    # The refused write changed nothing at all.
    lines, meta = validate_paginated(
        client.list_allocation_lines(
            channel_manager_headers(), {"allocation_cycle_id": ctx["cycle_id"]}
        )
    )
    assert meta["total_count"] == 1, "the refused line was not created"
    assert_field_equals(lines[0], "id", first["id"])
    lot = _assert_coverage_conserved(client, ctx["lot_id"], "after the refusal")
    assert_area(lot["allocated_sqft"], FULL_TRANCHE, "lot.allocated_sqft")
    assert_field_equals(fx.get_cycle(client, ctx["cycle_id"]), "version", v0 + 1)
    assert_field_equals(fx.get_order(client, order2), "status", "SUBMITTED")
    assert_area(fx.get_order(client, order2)["allocated_sqft"], 0.00, "order2.allocated_sqft")


def test_a_refreshed_cycle_version_accepts_the_byte_identical_line_body(
    client: InsulationApiClient,
) -> None:
    """PRD 2.6: "Proposing, committing and cancelling a cycle each increment its
    `version`, as does every successful manual line, so any of those advances invalidates
    a client's earlier read."

    Design: Corner/complexity_layers/a_stale_expected_allocation_cycle_version_is_refused_and_a_refreshed_one_succeeds
    """
    ctx = _cycle_ready_scenario(client, order_count=2)
    v0 = ctx["cycle_v0"]
    order1, order2 = ctx["orders"][0]["id"], ctx["orders"][1]["id"]

    validate_success(_cut_line(client, ctx, order1, FULL_TRANCHE, v0), 201)
    validate_error(
        _cut_line(client, ctx, order2, FULL_TRANCHE, v0),
        ApiErrors.STALE_ALLOCATION_CYCLE_VERSION,
    )

    # Re-reading the cycle is the whole remedy: the body is not changed by one byte.
    refreshed = fx.get_cycle(client, ctx["cycle_id"])
    v1 = int(refreshed["version"])
    assert v1 == v0 + 1, f"the refreshed version is {v0} + 1, got {v1}"

    second = validate_success(_cut_line(client, ctx, order2, FULL_TRANCHE, v1), 201)
    assert_field_equals(second, "status", "ALLOCATED")
    assert_area(second["allocated_sqft"], FULL_TRANCHE, "line2.allocated_sqft")

    lot = _assert_coverage_conserved(client, ctx["lot_id"], "after the retry")
    assert_area(lot["allocated_sqft"], 8800.00, "lot.allocated_sqft")
    assert_area(lot["available_sqft"], 1760.00, "lot.available_sqft")
    assert_field_equals(lot, "status", "AVAILABLE")
    assert_field_equals(fx.get_cycle(client, ctx["cycle_id"]), "version", v0 + 2)

    for order_id in (order1, order2):
        order = fx.get_order(client, order_id)
        assert_field_equals(order, "status", "ALLOCATED")
        assert_close(order["fill_rate_pct"], 100.00, 2, "fill_rate_pct")


# ---------------------------------------------------------------------------
# The plant's version guards its cullet ledger.
# ---------------------------------------------------------------------------


def test_a_stale_expected_plant_version_is_refused_when_staging_a_second_batch(
    client: InsulationApiClient,
) -> None:
    """PRD 2.6: "Staging a cullet batch requires `expected_plant_version` as a mandatory
    field carrying the client's last observed `version` of the target `Plant`. If that
    value does not equal the plant's current `version`, the request is rejected with
    `ERR_STALE_PLANT_VERSION` and HTTP 412."

    Design: Corner/complexity_layers/a_stale_expected_plant_version_is_refused_when_staging_cullet
    """
    fx.reset_clock(client)
    plant = fx.create_plant(client)
    plant_id = plant["id"]
    operator = plant_operator_headers(plant_id)
    assert_field_equals(plant, "melt_posture", "OPEN")
    assert_mass(plant["cullet_received_kg_ytd"], 0.00, "cullet_received_kg_ytd")
    assert_mass(plant["cullet_on_hand_kg"], 0.00, "cullet_on_hand_kg")
    pv1 = int(plant["version"])

    staged = validate_success(
        client.create_cullet_batch(
            f.cullet_batch_payload(plant_id, 500.00, pv1), operator
        ),
        201,
    )
    assert_field_equals(staged, "status", "STAGED")
    assert_mass(staged["mass_kg"], 500.00, "batch1.mass_kg")

    after_first = fx.get_plant(client, plant_id)
    assert_mass(after_first["cullet_received_kg_ytd"], 500.00, "cullet_received_kg_ytd")
    assert_mass(after_first["cullet_on_hand_kg"], 500.00, "cullet_on_hand_kg")
    assert_field_equals(after_first, "version", pv1 + 1)

    # Staging a second pile is ordinary business, so the only defect in this request is
    # the version it was built from.
    refused = client.create_cullet_batch(
        f.cullet_batch_payload(plant_id, 600.00, pv1), operator
    )
    validate_error(refused, ApiErrors.STALE_PLANT_VERSION)
    assert refused.status_code == 412, (
        f"a stale plant version is a 412, got {refused.status_code}"
    )

    # The refused stage wrote nothing: the ledger and the version both stand still.
    unchanged = fx.get_plant(client, plant_id)
    assert_mass(unchanged["cullet_received_kg_ytd"], 500.00, "cullet_received_kg_ytd")
    assert_mass(unchanged["cullet_on_hand_kg"], 500.00, "cullet_on_hand_kg")
    assert_field_equals(unchanged, "version", pv1 + 1)
    batches = fx.cullet_batches_for_plant(client, plant_id)
    assert len(batches) == 1, f"only the first batch exists, found {len(batches)}"
    assert_field_equals(batches[0], "id", staged["id"])


def test_a_refreshed_plant_version_lets_the_second_stage_through(
    client: InsulationApiClient,
) -> None:
    """PRD 2.6: "A successful stage increments the plant's `version` by one, which is why
    a second stage against a stale figure fails."
    PRD 3.1: "`cullet_on_hand_kg` the mass still sitting in the yard - equal to the
    received total less the charged total less the rejected total, held to two decimal
    places, and identical to the summed mass of the plant's batches still in `STAGED`
    status."

    Design: Corner/complexity_layers/a_stale_expected_plant_version_is_refused_when_staging_cullet
    """
    fx.reset_clock(client)
    plant = fx.create_plant(client)
    plant_id = plant["id"]
    operator = plant_operator_headers(plant_id)
    pv1 = int(plant["version"])

    validate_success(
        client.create_cullet_batch(
            f.cullet_batch_payload(plant_id, 500.00, pv1), operator
        ),
        201,
    )
    validate_error(
        client.create_cullet_batch(
            f.cullet_batch_payload(plant_id, 600.00, pv1), operator
        ),
        ApiErrors.STALE_PLANT_VERSION,
    )

    pv2 = int(fx.get_plant(client, plant_id)["version"])
    assert pv2 == pv1 + 1, f"the refreshed plant version is {pv1} + 1, got {pv2}"

    second = validate_success(
        client.create_cullet_batch(
            f.cullet_batch_payload(plant_id, 600.00, pv2), operator
        ),
        201,
    )
    assert_field_equals(second, "status", "STAGED")

    final = fx.get_plant(client, plant_id)
    assert_mass(final["cullet_received_kg_ytd"], 1100.00, "cullet_received_kg_ytd")
    assert_mass(final["cullet_on_hand_kg"], 1100.00, "cullet_on_hand_kg")
    assert_mass(final["cullet_charged_kg_ytd"], 0.00, "cullet_charged_kg_ytd")
    assert_mass(final["cullet_rejected_kg_ytd"], 0.00, "cullet_rejected_kg_ytd")
    assert_field_equals(final, "version", pv1 + 2)
    assert len(fx.cullet_batches_for_plant(client, plant_id)) == 2


# ---------------------------------------------------------------------------
# Four derived fields on two parents, rebuilt from the surviving lines.
# ---------------------------------------------------------------------------


def _one_line(client: InsulationApiClient) -> Dict[str, Any]:
    """One 2200.00 sqft manual line against a 4400.00 sqft order."""
    ctx = _cycle_ready_scenario(client, order_count=1)
    ctx["order_id"] = ctx["orders"][0]["id"]
    ctx["line1"] = validate_success(
        _cut_line(client, ctx, ctx["order_id"], HALF_TRANCHE, ctx["cycle_v0"]), 201
    )
    return ctx


def _two_lines(client: InsulationApiClient) -> Dict[str, Any]:
    """A second 2200.00 sqft line on the SAME order, so the parents must aggregate."""
    ctx = _one_line(client)
    version = int(fx.get_cycle(client, ctx["cycle_id"])["version"])
    ctx["line2"] = validate_success(
        _cut_line(client, ctx, ctx["order_id"], HALF_TRANCHE, version), 201
    )
    return ctx


def test_the_first_manual_line_recomputes_both_parent_ledgers(
    client: InsulationApiClient,
) -> None:
    """PRD 3.8: "each served order's `allocated_sqft` becomes its prior allocation plus
    its grant, quantized to two decimal places, its `fill_rate_pct` becomes
    `allocated_sqft` divided by `requested_sqft` multiplied by 100, quantized to two
    decimal places, and its status is **derived** from the comparison: `ALLOCATED` when
    `allocated_sqft` equals `requested_sqft` exactly, `PARTIAL` when it is greater than
    zero but short of the request, and `BACKORDERED` when it is exactly 0.00 - an order
    that was eligible but could not be funded a whole bag."
    PRD 3.7: "a lot in `AVAILABLE` or `ALLOCATED` becomes `ALLOCATED` when
    `available_sqft` reaches exactly 0.00 and `AVAILABLE` whenever it is greater than
    0.00."

    Design: Corner/complexity_layers/order_and_lot_derived_coverage_is_recomputed_after_every_line_create_and_revoke
    """
    ctx = _one_line(client)
    assert_field_equals(ctx["line1"], "status", "ALLOCATED")
    assert_field_equals(ctx["line1"], "bags", 25)

    order = fx.get_order(client, ctx["order_id"])
    assert_area(order["allocated_sqft"], HALF_TRANCHE, "order.allocated_sqft")
    assert_close(order["fill_rate_pct"], 50.00, 2, "order.fill_rate_pct")
    assert_field_equals(order, "status", "PARTIAL")

    lot = _assert_coverage_conserved(client, ctx["lot_id"], "after line 1")
    assert_area(lot["allocated_sqft"], HALF_TRANCHE, "lot.allocated_sqft")
    assert_area(lot["available_sqft"], 8360.00, "lot.available_sqft")
    # 8360.00 is greater than 0.00, so the derived status is AVAILABLE.
    assert_field_equals(lot, "status", "AVAILABLE")


def test_a_second_line_on_the_same_order_aggregates_instead_of_replacing(
    client: InsulationApiClient,
) -> None:
    """PRD 3.7: "`allocated_sqft` is the sum of `allocated_sqft` over the allocation lines
    whose `inventory_lot_id` is this lot and whose status is exactly `ALLOCATED`,
    quantized to two decimal places."

    Design: Corner/complexity_layers/order_and_lot_derived_coverage_is_recomputed_after_every_line_create_and_revoke
    """
    ctx = _two_lines(client)
    assert ctx["line2"]["id"] != ctx["line1"]["id"], "the second line is a new row"

    order = fx.get_order(client, ctx["order_id"])
    assert_area(order["allocated_sqft"], FULL_TRANCHE, "order.allocated_sqft")
    assert_close(order["fill_rate_pct"], 100.00, 2, "order.fill_rate_pct")
    assert_field_equals(order, "status", "ALLOCATED")

    lot = _assert_coverage_conserved(client, ctx["lot_id"], "after line 2")
    # An aggregate of both lines, not a copy of the latest line's 2200.00.
    assert_area(lot["allocated_sqft"], FULL_TRANCHE, "lot.allocated_sqft")
    assert_area(lot["available_sqft"], 6160.00, "lot.available_sqft")
    assert_field_equals(lot, "status", "AVAILABLE")

    booked = fx.lines_for_order(client, ctx["order_id"], status="ALLOCATED")
    assert len(booked) == 2, f"both lines are booked, found {len(booked)}"


def test_revoking_each_line_walks_both_parents_back_exactly(
    client: InsulationApiClient,
) -> None:
    """PRD 3.8: "The lot's ledger is recomputed and a fully drawn-down lot returns
    `ALLOCATED -> AVAILABLE`; the order's `allocated_sqft`, `fill_rate_pct` and status are
    recomputed, moving `ALLOCATED -> PARTIAL` when some coverage survives and
    `ALLOCATED -> BACKORDERED` when the revocation removed the order's entire allocation
    in one step - a fully filled order can drop straight to `BACKORDERED` without passing
    through `PARTIAL` when its only line is revoked - while a `PARTIAL` order that loses
    its last allocated square foot moves `PARTIAL -> BACKORDERED`; and the cycle's
    `allocated_sqft` and `unallocated_sqft` are recomputed."

    Design: Corner/complexity_layers/order_and_lot_derived_coverage_is_recomputed_after_every_line_create_and_revoke
    """
    ctx = _two_lines(client)

    revoked_first = validate_success(
        client.revoke_allocation_line(
            ctx["line1"]["id"],
            channel_manager_headers(),
            {"revoke_note": "first tranche released"},
        )
    )
    assert_field_equals(revoked_first, "status", "REVOKED")
    assert_field_equals(revoked_first, "revoke_reason", "MANUAL_REVOKE")
    # Revocation is per line: the survivor is untouched.
    assert_field_equals(fx.get_line(client, ctx["line2"]["id"]), "status", "ALLOCATED")

    order = fx.get_order(client, ctx["order_id"])
    assert_area(order["allocated_sqft"], HALF_TRANCHE, "order.allocated_sqft")
    assert_close(order["fill_rate_pct"], 50.00, 2, "order.fill_rate_pct")
    assert_field_equals(order, "status", "PARTIAL")

    lot = _assert_coverage_conserved(client, ctx["lot_id"], "after revoking line 1")
    assert_area(lot["allocated_sqft"], HALF_TRANCHE, "lot.allocated_sqft")
    assert_area(lot["available_sqft"], 8360.00, "lot.available_sqft")
    assert_field_equals(lot, "status", "AVAILABLE")

    revoked_second = validate_success(
        client.revoke_allocation_line(
            ctx["line2"]["id"],
            channel_manager_headers(),
            {"revoke_note": "second tranche released"},
        )
    )
    assert_field_equals(revoked_second, "status", "REVOKED")

    order = fx.get_order(client, ctx["order_id"])
    assert_area(order["allocated_sqft"], 0.00, "order.allocated_sqft")
    assert_close(order["fill_rate_pct"], 0.00, 2, "order.fill_rate_pct")
    assert_field_equals(order, "status", "BACKORDERED")

    lot = _assert_coverage_conserved(client, ctx["lot_id"], "after revoking line 2")
    assert_area(lot["allocated_sqft"], 0.00, "lot.allocated_sqft")
    assert_area(lot["available_sqft"], LOT_SQFT, "lot.available_sqft")
    assert_field_equals(lot, "status", "AVAILABLE")
