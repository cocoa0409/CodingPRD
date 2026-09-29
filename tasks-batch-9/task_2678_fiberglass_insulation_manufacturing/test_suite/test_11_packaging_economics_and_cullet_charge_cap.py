"""Combinatorial formulas: the packaging trade-off and the circular cullet cap.

Queue A / combinatorial_formula.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import InsulationApiClient
from test_helpers.assertions import (
    assert_bale_volume,
    assert_close,
    assert_field_equals,
    assert_mass,
    assert_per_sqft_cost,
    assert_ratio,
)
from test_helpers.constants import (
    BINDER_FORMALDEHYDE_FREE,
    SKU_PL_A,
    SKU_PL_B,
    ZONES_470,
)
from test_helpers.test_users import corporate_ops_headers, plant_operator_headers


def _reference_data(client: InsulationApiClient) -> Dict[str, Any]:
    """Program RCERT-PS, plant NWK and a CERTIFIED formaldehyde-free binder."""
    fx.reset_clock(client)
    program = fx.create_per_specimen_program(client)
    plant = fx.create_plant(client)
    binder = fx.create_certified_binder(client, **BINDER_FORMALDEHYDE_FREE)
    return {
        "program": program,
        "program_id": program["id"],
        "plant": plant,
        "plant_id": plant["id"],
        "binder_id": binder["id"],
        "operator": plant_operator_headers(plant["id"]),
    }


# ---------------------------------------------------------------------------
# packaging_economics_nested_min_max_with_dual_truck_limits
# ---------------------------------------------------------------------------


def test_unfaced_sku_packaging_economics_are_bound_by_the_trailer_cube(
    client: InsulationApiClient,
) -> None:
    """An UNFACED SKU at ratio 6.0 loses recovery but no facing penalty.

    PRD 3.3: "The volume-bound count is 3800 divided by
    `compressed_bale_volume_ft3`, truncated down to a whole number of bales; the
    payload-bound count is 19500 divided by `bale_mass_kg`, likewise truncated
    down. `bales_per_truck` is the smaller of those two counts - whichever limit
    binds first wins, and for a lightly compressed light-density SKU that is
    usually the cube rather than the scale."

    Design: Difficulty/combinatorial_formula/packaging_economics_nested_min_max_with_dual_truck_limits
    """
    ctx = _reference_data(client)
    pl_a = fx.create_product_line(
        client, ctx["plant_id"], ctx["binder_id"], ctx["program_id"], **SKU_PL_A
    )

    assert_close(pl_a["recovered_thickness_pct"], 90.00, 2, "recovered_thickness_pct")
    assert_bale_volume(pl_a["compressed_bale_volume_ft3"], 3.500)
    assert_field_equals(pl_a, "bales_per_truck", 1085)
    assert_per_sqft_cost(pl_a["freight_cost_per_sqft"], 0.025660, "freight_cost_per_sqft")
    assert_per_sqft_cost(
        pl_a["recovery_penalty_per_sqft"], 0.006000, "recovery_penalty_per_sqft"
    )
    assert_per_sqft_cost(
        pl_a["net_landed_cost_per_sqft"], 0.031660, "net_landed_cost_per_sqft"
    )


def test_faced_sku_pays_the_flat_facing_recovery_penalty_at_creation(
    client: InsulationApiClient,
) -> None:
    """A KRAFT-faced SKU at ratio 5.0 gives up a further 2.0 points of recovery.

    PRD 3.3: "From a nominal 100 percent the system subtracts that excess
    multiplied by 5.0, rounded half up to two decimal places, and then subtracts a
    further flat 2.0 percentage points whenever the SKU's facing is anything other
    than `UNFACED`."

    Design: Difficulty/combinatorial_formula/packaging_economics_nested_min_max_with_dual_truck_limits
    """
    ctx = _reference_data(client)
    pl_b = fx.create_product_line(
        client, ctx["plant_id"], ctx["binder_id"], ctx["program_id"], **SKU_PL_B
    )

    assert_close(pl_b["recovered_thickness_pct"], 93.00, 2, "recovered_thickness_pct")
    assert_bale_volume(pl_b["compressed_bale_volume_ft3"], 5.100)
    assert_field_equals(pl_b, "bales_per_truck", 745)
    assert_per_sqft_cost(pl_b["freight_cost_per_sqft"], 0.067114, "freight_cost_per_sqft")
    assert_per_sqft_cost(
        pl_b["net_landed_cost_per_sqft"], 0.069514, "net_landed_cost_per_sqft"
    )


def test_maximum_compression_clamps_recovery_up_to_the_hard_floor(
    client: InsulationApiClient,
) -> None:
    """Re-tuning PL-B to ratio 8.0 drives raw recovery below the 80.00 floor.

    PRD 3.3: "The result is rounded half up to two decimal places, and
    `recovered_thickness_pct` is the greater of that result and a hard floor of
    80.00 percent."

    Design: Difficulty/combinatorial_formula/packaging_economics_nested_min_max_with_dual_truck_limits
    """
    ctx = _reference_data(client)
    pl_b = fx.create_product_line(
        client, ctx["plant_id"], ctx["binder_id"], ctx["program_id"], **SKU_PL_B
    )

    patched = get_success_data(
        client.patch_packaging(
            pl_b["id"],
            f.packaging_patch_payload(compression_ratio=8.0),
            corporate_ops_headers(),
        )
    )

    assert_close(patched["recovered_thickness_pct"], 80.00, 2, "recovered_thickness_pct")
    assert_bale_volume(patched["compressed_bale_volume_ft3"], 3.188)
    assert_field_equals(patched, "bales_per_truck", 1191)
    assert_per_sqft_cost(
        patched["freight_cost_per_sqft"], 0.041982, "freight_cost_per_sqft"
    )
    assert_per_sqft_cost(
        patched["recovery_penalty_per_sqft"], 0.018000, "recovery_penalty_per_sqft"
    )
    assert_per_sqft_cost(
        patched["net_landed_cost_per_sqft"], 0.059982, "net_landed_cost_per_sqft"
    )


def test_packaging_patch_leaves_unsupplied_geometry_untouched(
    client: InsulationApiClient,
) -> None:
    """Only the supplied packaging fields replace their stored values.

    PRD 3.3: "The caller may supply any subset of `compression_ratio`,
    `bale_volume_ft3`, `bale_mass_kg` and `bag_sqft`; the supplied fields replace
    their stored values and all six derived figures - `recovered_thickness_pct`,
    `compressed_bale_volume_ft3`, `bales_per_truck`, `freight_cost_per_sqft`,
    `recovery_penalty_per_sqft` and `net_landed_cost_per_sqft` - are recomputed
    from scratch by the five steps above."

    Design: Difficulty/combinatorial_formula/packaging_economics_nested_min_max_with_dual_truck_limits
    """
    ctx = _reference_data(client)
    pl_b = fx.create_product_line(
        client, ctx["plant_id"], ctx["binder_id"], ctx["program_id"], **SKU_PL_B
    )

    patched = get_success_data(
        client.patch_packaging(
            pl_b["id"],
            f.packaging_patch_payload(compression_ratio=8.0),
            corporate_ops_headers(),
        )
    )

    assert_close(patched["compression_ratio"], 8.0, 1, "compression_ratio")
    assert_close(patched["bale_volume_ft3"], 25.5, 2, "bale_volume_ft3")
    assert_close(patched["bale_mass_kg"], 15.0, 2, "bale_mass_kg")
    assert_close(patched["bag_sqft"], 49.0, 2, "bag_sqft")


# ---------------------------------------------------------------------------
# cullet_charge_cap_circular_dependency_evaluation_order
# ---------------------------------------------------------------------------


def _charge_scenario(client: InsulationApiClient) -> Dict[str, Any]:
    """Three STAGED batches of 1200/1400/500 kg and a SCHEDULED 9200 kg run."""
    ctx = _reference_data(client)
    pl_a = fx.create_product_line(
        client, ctx["plant_id"], ctx["binder_id"], ctx["program_id"], **SKU_PL_A
    )
    batches = fx.stage_cullet_batches(client, ctx["plant_id"], [1200.0, 1400.0, 500.0])
    run = fx.schedule_run(
        client,
        ctx["plant_id"],
        pl_a["id"],
        line_index=1,
        scheduled_start="2026-08-03T06:00:00Z",
        scheduled_end="2026-08-03T14:00:00Z",
        target_pull_kg=9200.0,
        zone_setpoints_f=ZONES_470,
    )
    fx.set_clock(client, "2026-08-03T06:00:00Z")
    ctx.update({"pl_a": pl_a, "batches": batches, "run": run})
    return ctx


def test_cullet_ceiling_is_taken_against_the_total_charge_not_the_virgin_mass(
    client: InsulationApiClient,
) -> None:
    """The circular cap resolves by pinning the total charge to the pull target.

    PRD 3.4: "The cullet ceiling is then taken against that total and never against
    the virgin mass: `allowed_cullet_kg` is `total_charge_kg` multiplied by the
    plant's `max_cullet_fraction`, truncated **down** to two decimal places."

    Design: Difficulty/combinatorial_formula/cullet_charge_cap_circular_dependency_evaluation_order
    """
    ctx = _charge_scenario(client)
    batch_ids = [b["id"] for b in ctx["batches"]]

    melting = fx.start_melt(client, ctx["plant_id"], ctx["run"]["id"], batch_ids)

    assert_mass(melting["total_charge_kg"], 10000.00, "total_charge_kg")
    assert_mass(melting["allowed_cullet_kg"], 3000.00, "allowed_cullet_kg")
    assert_mass(melting["cullet_charged_kg"], 2600.00, "cullet_charged_kg")
    assert_mass(melting["virgin_batch_kg"], 7400.00, "virgin_batch_kg")
    assert_ratio(melting["cullet_fraction"], 0.2600, "cullet_fraction")
    assert_close(
        melting["virgin_batch_kg"] + melting["cullet_charged_kg"],
        melting["total_charge_kg"],
        2,
        "virgin + cullet must balance the total charge",
    )
    assert_field_equals(melting, "run_status", "MELTING")


def test_oversized_batch_is_skipped_whole_rather_than_split_into_the_headroom(
    client: InsulationApiClient,
) -> None:
    """400 kg of headroom remains, yet the 500 kg batch stays in the yard.

    PRD 3.4: "Batches are then consumed **whole** and greedily in `created_at`
    ascending order: for each staged batch in turn, if adding its `mass_kg` to the
    mass charged so far would still leave the running total at or below
    `allowed_cullet_kg`, the batch is charged; otherwise it is skipped entirely -
    never partially charged - and left in `STAGED` for a later run, and smaller
    batches later in the ordering are still considered."

    Design: Difficulty/combinatorial_formula/cullet_charge_cap_circular_dependency_evaluation_order
    """
    ctx = _charge_scenario(client)
    batch_1, batch_2, batch_3 = ctx["batches"]

    fx.start_melt(
        client,
        ctx["plant_id"],
        ctx["run"]["id"],
        [batch_1["id"], batch_2["id"], batch_3["id"]],
    )

    first = fx.get_cullet_batch(client, batch_1["id"])
    second = fx.get_cullet_batch(client, batch_2["id"])
    third = fx.get_cullet_batch(client, batch_3["id"])

    assert_field_equals(first, "status", "CHARGED")
    assert_field_equals(first, "charged_run_id", ctx["run"]["id"])
    assert_field_equals(second, "status", "CHARGED")
    assert_field_equals(second, "charged_run_id", ctx["run"]["id"])
    assert_field_equals(third, "status", "STAGED")
    assert_field_equals(third, "charged_run_id", None)
    assert_mass(third["mass_kg"], 500.00, "skipped batch mass_kg")


def test_plant_glass_ledger_follows_the_charge_without_tripping_the_restriction(
    client: InsulationApiClient,
) -> None:
    """The charge moves four plant accumulators and leaves the posture OPEN.

    PRD 3.4: "In the same request the plant's ledger moves: `cullet_charged_kg_ytd`
    increases by the mass charged, `total_charge_kg_ytd` increases by the run's
    total charge, `cullet_fraction_ytd` is recomputed as the charged-cullet
    accumulator divided by the total-charge accumulator rounded half up to four
    decimal places, and `cullet_on_hand_kg` is recomputed as received less charged
    less rejected."

    Design: Difficulty/combinatorial_formula/cullet_charge_cap_circular_dependency_evaluation_order
    """
    ctx = _charge_scenario(client)
    batch_ids = [b["id"] for b in ctx["batches"]]

    fx.start_melt(client, ctx["plant_id"], ctx["run"]["id"], batch_ids)

    plant = fx.get_plant(client, ctx["plant_id"])
    assert_mass(plant["cullet_charged_kg_ytd"], 2600.00, "cullet_charged_kg_ytd")
    assert_mass(plant["total_charge_kg_ytd"], 10000.00, "total_charge_kg_ytd")
    assert_ratio(plant["cullet_fraction_ytd"], 0.2600, "cullet_fraction_ytd")
    assert_mass(plant["cullet_on_hand_kg"], 500.00, "cullet_on_hand_kg")
    assert_field_equals(plant, "melt_posture", "OPEN")
    assert_field_equals(plant, "posture_reason", None)
