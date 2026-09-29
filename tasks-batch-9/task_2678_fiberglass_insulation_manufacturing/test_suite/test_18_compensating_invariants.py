"""Compensating operations that must restore an invariant exactly: a cullet reversal
conserving glass mass, and a line revocation conserving lot coverage.

Queue A / compensating_invariant.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import get_success_data

from test_helpers import fixtures as fx
from test_helpers.api_client import InsulationApiClient
from test_helpers.assertions import assert_close, assert_field_equals
from test_helpers.constants import SKU_PL_A, ZONES_470
from test_helpers.test_users import channel_manager_headers, plant_operator_headers

FREE_BINDER = {
    "code": "BF-FREE-1",
    "formaldehyde_free": True,
    "formaldehyde_ppm": 0,
    "voc_g_per_kg": 3.2,
    "min_cure_temp_f": 420.0,
    "min_dwell_s": 150.0,
    "loi_target_pct": 4.5,
}


def _charged_melt(client: InsulationApiClient) -> Dict[str, Any]:
    """Three staged batches of 1200.00, 1400.00 and 500.00 kg; the 3000.00 kg ceiling
    admits the first two whole and skips the third."""
    ctx = fx.base_setup(
        client, binder_overrides=dict(FREE_BINDER), sku_overrides=dict(SKU_PL_A)
    )
    batches = fx.stage_cullet_batches(
        client, ctx["plant_id"], [1200.00, 1400.00, 500.00]
    )
    run = fx.schedule_run(
        client,
        ctx["plant_id"],
        ctx["sku_id"],
        scheduled_start="2026-08-03T06:00:00Z",
        scheduled_end="2026-08-03T14:00:00Z",
        line_index=1,
        target_pull_kg=9200.0,
        zone_setpoints_f=list(ZONES_470),
    )
    fx.set_clock(client, "2026-08-03T06:00:00Z")
    melted = fx.start_melt(
        client, ctx["plant_id"], run["id"], [b["id"] for b in batches]
    )
    ctx.update(
        {
            "batches": batches,
            "batch_1": batches[0]["id"],
            "batch_2": batches[1]["id"],
            "batch_3": batches[2]["id"],
            "run_id": run["id"],
            "melted": melted,
            "plant_before": fx.get_plant(client, ctx["plant_id"]),
        }
    )
    return ctx


def _reverse(client: InsulationApiClient, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(
        client.reverse_cullet_batch(
            ctx["batch_2"],
            plant_operator_headers(ctx["plant_id"]),
            {"reversal_note": "Wet cullet found in the pile after charging"},
        )
    )


def test_the_reversal_swaps_cullet_for_virgin_batch_on_the_run(
    client: InsulationApiClient,
) -> None:
    """PRD 3.5: "and on the run, `cullet_charged_kg` decreases by `mass_kg`,
    `virgin_batch_kg` increases by the same mass, `cullet_fraction` is recomputed, and
    `total_charge_kg` is left untouched - the glass-mass invariant holds exactly."

    Design: Difficulty/compensating_invariant/cullet_charge_reversal_preserves_total_glass_mass
    """
    ctx = _charged_melt(client)
    before = ctx["melted"]
    assert_close(before["total_charge_kg"], 10000.00, 2, "total_charge_kg")
    assert_close(before["allowed_cullet_kg"], 3000.00, 2, "allowed_cullet_kg")
    assert_close(before["cullet_charged_kg"], 2600.00, 2, "cullet_charged_kg")
    assert_close(before["virgin_batch_kg"], 7400.00, 2, "virgin_batch_kg")
    assert_close(before["cullet_fraction"], 0.2600, 4, "cullet_fraction")

    reversed_batch = _reverse(client, ctx)

    assert_field_equals(reversed_batch, "status", "STAGED")
    assert reversed_batch["charged_run_id"] is None
    assert_field_equals(
        fx.get_cullet_batch(client, ctx["batch_1"]), "status", "CHARGED"
    )
    assert_field_equals(fx.get_cullet_batch(client, ctx["batch_3"]), "status", "STAGED")

    after = fx.get_run(client, ctx["run_id"])
    assert_close(after["cullet_charged_kg"], 1200.00, 2, "cullet_charged_kg")
    assert_close(after["virgin_batch_kg"], 8800.00, 2, "virgin_batch_kg")
    assert_close(after["cullet_fraction"], 0.1200, 4, "cullet_fraction")
    # The invariant: the charge total never moves and the two buckets still sum to it.
    assert_close(after["total_charge_kg"], 10000.00, 2, "total_charge_kg")
    assert_close(
        after["cullet_charged_kg"] + after["virgin_batch_kg"],
        10000.00,
        2,
        "cullet_charged_kg + virgin_batch_kg",
    )
    assert_close(after["allowed_cullet_kg"], 3000.00, 2, "allowed_cullet_kg")
    assert_field_equals(after, "run_status", "MELTING")


def test_the_reversal_returns_the_mass_to_the_plants_on_hand_pile(
    client: InsulationApiClient,
) -> None:
    """PRD 3.5: "The batch returns `CHARGED -> STAGED` with `charged_run_id` cleared; the
    plant's `cullet_on_hand_kg` increases by `mass_kg`, its `cullet_charged_kg_ytd`
    decreases by the same mass and its `cullet_fraction_ytd` is recomputed."

    Design: Difficulty/compensating_invariant/cullet_charge_reversal_preserves_total_glass_mass
    """
    ctx = _charged_melt(client)
    before = ctx["plant_before"]
    assert_close(before["cullet_received_kg_ytd"], 3100.00, 2, "cullet_received_kg_ytd")
    assert_close(before["cullet_on_hand_kg"], 500.00, 2, "cullet_on_hand_kg")
    assert_close(before["cullet_charged_kg_ytd"], 2600.00, 2, "cullet_charged_kg_ytd")

    _reverse(client, ctx)

    after = fx.get_plant(client, ctx["plant_id"])
    assert_close(after["cullet_on_hand_kg"], 1900.00, 2, "cullet_on_hand_kg")
    assert_close(after["cullet_charged_kg_ytd"], 1200.00, 2, "cullet_charged_kg_ytd")
    assert_close(after["cullet_fraction_ytd"], 0.1200, 4, "cullet_fraction_ytd")
    # The invariant: received glass is conserved across the on-hand and charged buckets.
    assert_close(after["cullet_received_kg_ytd"], 3100.00, 2, "cullet_received_kg_ytd")
    assert_close(
        after["cullet_on_hand_kg"] + after["cullet_charged_kg_ytd"],
        3100.00,
        2,
        "cullet_on_hand_kg + cullet_charged_kg_ytd",
    )


def test_the_reversal_does_not_rewind_the_charge_denominator_or_reject_the_glass(
    client: InsulationApiClient,
) -> None:
    """PRD 3.5: "the batch moves `STAGED -> REJECTED`, which is terminal, the reason is
    stored, and the plant's `cullet_on_hand_kg` decreases by `mass_kg` while
    `cullet_rejected_kg_ytd` increases by the same mass, so the glass leaves the on-hand
    pool without ever having been charged."

    PRD 3.5: "A reversal does **not** clear a `RESTRICTED` posture on its own; lowering
    the ratio merely makes the environmental recompute review of 3.1 succeed."

    Design: Difficulty/compensating_invariant/cullet_charge_reversal_preserves_total_glass_mass
    """
    ctx = _charged_melt(client)
    assert_close(
        ctx["plant_before"]["total_charge_kg_ytd"], 10000.00, 2, "total_charge_kg_ytd"
    )
    assert_close(
        ctx["plant_before"]["cullet_fraction_ytd"], 0.2600, 4, "cullet_fraction_ytd"
    )
    assert_field_equals(ctx["plant_before"], "melt_posture", "OPEN")

    _reverse(client, ctx)

    after = fx.get_plant(client, ctx["plant_id"])
    # Only the numerator is rewound; the accumulated charge total stays where it was.
    assert_close(after["total_charge_kg_ytd"], 10000.00, 2, "total_charge_kg_ytd")
    assert_close(after["cullet_rejected_kg_ytd"], 0.00, 2, "cullet_rejected_kg_ytd")
    assert_field_equals(after, "melt_posture", "OPEN")
    assert after["posture_reason"] is None


def _committed_allocation(client: InsulationApiClient) -> Dict[str, Any]:
    """A CONTRACT_FIRST cycle over peak-season August, committed against one lot."""
    ctx = fx.certified_sku_with_lot(client, bags_produced=120)
    order = fx.place_order(
        client,
        ctx["sku_id"],
        8800.0,
        channel_type="DISTRIBUTOR",
        priority_tier="CONTRACT",
        required_by="2026-08-31T00:00:00Z",
    )
    cycle = fx.open_cycle(
        client,
        ctx["plant_id"],
        ctx["sku_id"],
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-08-31T23:59:59Z",
        allocation_basis="CONTRACT_FIRST",
    )
    fx.propose_cycle(client, cycle["id"])
    committed = fx.commit_cycle(client, cycle["id"])
    lines = fx.lines_for_cycle(client, cycle["id"])
    assert len(lines) == 1, "the waterfall should have cut exactly one line"
    ctx.update(
        {
            "order_id": order["id"],
            "cycle_id": cycle["id"],
            "committed": committed,
            "line_id": lines[0]["id"],
            "line_before": lines[0],
        }
    )
    return ctx


def test_revoking_the_only_line_restores_the_lots_whole_coverage(
    client: InsulationApiClient,
) -> None:
    """PRD 3.8: "Revoking a line is the compensating leg and applies from `PROPOSED` or
    from `ALLOCATED`, landing on the terminal `REVOKED` with `revoke_reason`
    `MANUAL_REVOKE` and an optional `revoke_note`."

    Design: Difficulty/compensating_invariant/allocation_line_revoke_restores_lot_coverage_and_order_ledger
    """
    ctx = _committed_allocation(client)
    assert_field_equals(ctx["line_before"], "status", "ALLOCATED")
    assert_close(ctx["line_before"]["allocated_sqft"], 8800.00, 2, "allocated_sqft")
    assert_field_equals(ctx["line_before"], "bags", 100)

    lot_before = fx.get_lot(client, ctx["lot_id"])
    assert_close(lot_before["produced_sqft"], 10560.00, 2, "produced_sqft")
    assert_close(lot_before["allocated_sqft"], 8800.00, 2, "allocated_sqft")
    assert_close(lot_before["available_sqft"], 1760.00, 2, "available_sqft")
    assert_close(
        lot_before["allocated_sqft"] + lot_before["available_sqft"],
        10560.00,
        2,
        "allocated_sqft + available_sqft",
    )

    revoked = get_success_data(
        client.revoke_allocation_line(
            ctx["line_id"],
            channel_manager_headers(),
            {"revoke_note": "Distributor deferred the pull to September"},
        )
    )

    assert_field_equals(revoked, "status", "REVOKED")
    assert_field_equals(revoked, "revoke_reason", "MANUAL_REVOKE")

    lot_after = fx.get_lot(client, ctx["lot_id"])
    assert_field_equals(lot_after, "status", "AVAILABLE")
    assert lot_after["quarantine_reason"] is None
    assert_close(lot_after["allocated_sqft"], 0.00, 2, "allocated_sqft")
    assert_close(lot_after["available_sqft"], 10560.00, 2, "available_sqft")
    # The invariant: produced coverage is immutable and the two buckets still sum to it.
    assert_close(lot_after["produced_sqft"], 10560.00, 2, "produced_sqft")
    assert_close(
        lot_after["allocated_sqft"] + lot_after["available_sqft"],
        10560.00,
        2,
        "allocated_sqft + available_sqft",
    )


def test_revoking_the_only_line_rewinds_the_order_and_cycle_ledgers(
    client: InsulationApiClient,
) -> None:
    """PRD 3.8: "the order's `allocated_sqft`, `fill_rate_pct` and status are recomputed,
    moving `ALLOCATED -> PARTIAL` when some coverage survives and `ALLOCATED ->
    BACKORDERED` when the revocation removed the order's entire allocation in one step - a
    fully filled order can drop straight to `BACKORDERED` without passing through
    `PARTIAL` when its only line is revoked - while a `PARTIAL` order that loses its last
    allocated square foot moves `PARTIAL -> BACKORDERED`; and the cycle's `allocated_sqft`
    and `unallocated_sqft` are recomputed."

    Design: Difficulty/compensating_invariant/allocation_line_revoke_restores_lot_coverage_and_order_ledger
    """
    ctx = _committed_allocation(client)
    order_before = fx.get_order(client, ctx["order_id"])
    assert_field_equals(order_before, "status", "ALLOCATED")
    assert_close(order_before["fill_rate_pct"], 100.00, 2, "fill_rate_pct")
    cycle_before = ctx["committed"]
    assert_field_equals(cycle_before, "peak_season", True)
    assert_close(cycle_before["allocatable_sqft"], 8976.00, 2, "allocatable_sqft")
    assert_close(cycle_before["allocated_sqft"], 8800.00, 2, "allocated_sqft")
    assert_close(cycle_before["unallocated_sqft"], 176.00, 2, "unallocated_sqft")

    get_success_data(
        client.revoke_allocation_line(
            ctx["line_id"],
            channel_manager_headers(),
            {"revoke_note": "Distributor deferred the pull to September"},
        )
    )

    order_after = fx.get_order(client, ctx["order_id"])
    assert_close(order_after["allocated_sqft"], 0.00, 2, "allocated_sqft")
    assert_close(order_after["fill_rate_pct"], 0.00, 2, "fill_rate_pct")
    assert_field_equals(order_after, "status", "BACKORDERED")
    assert_close(order_after["requested_sqft"], 8800.00, 2, "requested_sqft")

    cycle_after = fx.get_cycle(client, ctx["cycle_id"])
    assert_close(cycle_after["allocated_sqft"], 0.00, 2, "allocated_sqft")
    assert_close(cycle_after["unallocated_sqft"], 8976.00, 2, "unallocated_sqft")
    # The freed supply stays re-proposable: the allocatable pool is untouched and its two
    # buckets still sum to it.
    assert_close(cycle_after["allocatable_sqft"], 8976.00, 2, "allocatable_sqft")
    assert_close(
        cycle_after["allocated_sqft"] + cycle_after["unallocated_sqft"],
        8976.00,
        2,
        "allocated_sqft + unallocated_sqft",
    )
    assert_close(cycle_after["total_available_sqft"], 10560.00, 2, "total_available_sqft")
    assert_close(cycle_after["seasonal_reserve_sqft"], 1584.00, 2, "seasonal_reserve_sqft")
    assert_close(cycle_after["total_requested_sqft"], 8800.00, 2, "total_requested_sqft")
    assert_close(cycle_after["shortage_ratio"], 1.0000, 4, "shortage_ratio")
    assert_field_equals(cycle_after, "peak_season", True)
    # Revoking its last line does not reopen the cycle.
    assert_field_equals(cycle_after, "status", "COMMITTED")

    run = fx.get_run(client, ctx["run_id"])
    assert_close(run["produced_sqft"], 10560.00, 2, "produced_sqft")
    assert_field_equals(run, "qc_status", "CONFORMING")
