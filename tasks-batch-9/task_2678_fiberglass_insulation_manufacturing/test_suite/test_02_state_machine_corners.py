"""Corner coverage for the production run's two state dimensions.

Breadth slice: the ProductionRun state machine - its twin initial states, the
SCHEDULED -> MELTING charge edge, the edges that do not exist, the temporal
precondition on the melt, the packaging side effect, terminal lockdown after a
close, and the state-conditional SKU-suspension cascade.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import InsulationApiClient
from test_helpers.api_errors import ApiErrors
from test_helpers.assertions import assert_close, assert_field_equals
from test_helpers.constants import SKU_PL_A, ZONES_470
from test_helpers.test_users import (
    CERTIFICATION_OFFICER_USER_ID_ALT,
    certification_officer_headers,
    corporate_ops_headers,
    plant_operator_headers,
)

# A formaldehyde-free chemistry: 0 ppm free formaldehyde, curing from 420 F with a
# 150 s minimum dwell (PRD 3.2 input fields).
FREE_BINDER = {
    "code": "BF-FREE-1",
    "formaldehyde_free": True,
    "formaldehyde_ppm": 0,
    "voc_g_per_kg": 3.2,
    "min_cure_temp_f": 420.0,
    "min_dwell_s": 150.0,
    "loi_target_pct": 4.5,
}

RUN_START = "2026-08-03T06:00:00Z"
RUN_END = "2026-08-03T14:00:00Z"
ONE_MINUTE_EARLY = "2026-08-03T05:59:00Z"

# oven_length_ft 120 / line_speed_fpm 40 * 60 = dwell_s 180.00; dwell ratio
# 180 / 150 = 1.2; temperature margin (470 - 420) / 60 = 0.833333...;
# cure_index = 1.2 * (1 + 0.833333) / 2 * 100 = 110.00 (PRD 3.4).
CURE_MEASUREMENTS = {
    "avg_zone_temp_f": 470.0,
    "line_speed_fpm": 40.0,
    "binder_applied_kg": 900.0,
}
EXPECTED_DWELL_S = 180.00
EXPECTED_CURE_INDEX = 110.00

# target_pull_kg 9200 / melt yield 0.92 = 10000.00 kg of charge; the cullet
# ceiling is 10000.00 * max_cullet_fraction 0.30 = 3000.00 kg (PRD 3.4).
TARGET_PULL_KG = 9200.0
EXPECTED_TOTAL_CHARGE_KG = 10000.00
EXPECTED_ALLOWED_CULLET_KG = 3000.00

BAGS_PRODUCED = 120
EXPECTED_PRODUCED_SQFT = 10560.00  # 120 bags * the SKU's bag_sqft of 88.0


def _scheduled_run(
    client: InsulationApiClient, clock: str = RUN_START, **run_overrides: Any
) -> Dict[str, Any]:
    """Reference data plus one SCHEDULED run of PL-A on line 1 for [06:00, 14:00)."""
    ctx = fx.base_setup(
        client,
        binder_overrides=dict(FREE_BINDER),
        sku_overrides=dict(SKU_PL_A),
    )
    fx.set_clock(client, clock)
    overrides: Dict[str, Any] = {
        "scheduled_start": RUN_START,
        "scheduled_end": RUN_END,
        "line_index": 1,
        "target_pull_kg": TARGET_PULL_KG,
        "zone_setpoints_f": list(ZONES_470),
    }
    overrides.update(run_overrides)
    run = fx.schedule_run(client, ctx["plant_id"], ctx["sku_id"], **overrides)
    ctx["run"] = run
    ctx["run_id"] = run["id"]
    return ctx


def _melting_run(client: InsulationApiClient) -> Dict[str, Any]:
    ctx = _scheduled_run(client)
    ctx["run"] = fx.start_melt(client, ctx["plant_id"], ctx["run_id"])
    return ctx


def _curing_run(client: InsulationApiClient) -> Dict[str, Any]:
    ctx = _melting_run(client)
    ctx["run"] = fx.start_cure(
        client, ctx["plant_id"], ctx["run_id"], **CURE_MEASUREMENTS
    )
    return ctx


def _packaged_run(client: InsulationApiClient) -> Dict[str, Any]:
    ctx = _curing_run(client)
    ctx["run"] = fx.package_run(
        client, ctx["plant_id"], ctx["run_id"], bags_produced=BAGS_PRODUCED
    )
    ctx["lot"] = fx.lot_for_run(client, ctx["run_id"])
    ctx["lot_id"] = ctx["lot"]["id"]
    return ctx


def test_a_new_run_lands_scheduled_and_unsampled_with_zeroed_glass_counters(
    client: InsulationApiClient,
) -> None:
    """PRD 3.4: "The new run lands with `run_status` `SCHEDULED`, `qc_status`
    `UNSAMPLED`, `hold_reason` null, `changeover_scrap_kg` 0.00, `cullet_charged_kg`
    0.00, and every other mass, cure and emissions figure null."

    Design: Corner/state_machines/a_new_production_run_starts_scheduled_and_unsampled
    """
    ctx = _scheduled_run(client)
    run = ctx["run"]

    assert_field_equals(run, "run_status", "SCHEDULED")
    assert_field_equals(run, "qc_status", "UNSAMPLED")
    assert run["hold_reason"] is None
    assert_close(run["changeover_scrap_kg"], 0.00, 2, "changeover_scrap_kg")
    assert_close(run["cullet_charged_kg"], 0.00, 2, "cullet_charged_kg")

    # Every other mass, cure and emissions figure is still unset - the charge has not
    # been struck, the oven has not run and no binder has been sprayed.
    for field in (
        "total_charge_kg",
        "allowed_cullet_kg",
        "virgin_batch_kg",
        "dwell_s",
        "cure_index",
        "binder_applied_kg",
        "formaldehyde_kg",
        "voc_kg",
    ):
        assert run[field] is None, f"expected {field} null on a fresh run, got {run[field]!r}"

    # The row survives a re-read unchanged.
    reread = fx.get_run(client, ctx["run_id"])
    assert_field_equals(reread, "run_status", "SCHEDULED")
    assert_field_equals(reread, "qc_status", "UNSAMPLED")
    assert reread["hold_reason"] is None


def test_charging_the_furnace_advances_the_scheduled_run_to_melting(
    client: InsulationApiClient,
) -> None:
    """PRD 3.4: "Charging the furnace advances the run `SCHEDULED -> MELTING` and is the
    single most tightly coupled operation in the API."

    Design: Corner/state_machines/start_melt_moves_a_scheduled_run_to_melting_and_charges_the_glass
    """
    ctx = _scheduled_run(client)
    batch = fx.stage_cullet(client, ctx["plant_id"], 1500.00)
    assert_field_equals(batch, "status", "STAGED")

    melting = get_success_data(
        client.start_melt(
            ctx["run_id"], [batch["id"]], plant_operator_headers(ctx["plant_id"])
        )
    )

    assert_field_equals(melting, "run_status", "MELTING")
    # The quality dimension is untouched by a physical transition.
    assert_field_equals(melting, "qc_status", "UNSAMPLED")
    # 9200 / 0.92 = 10000.00 kg charged; ceiling 10000.00 * 0.30 = 3000.00 kg; the one
    # 1500.00 kg batch fits whole, leaving 10000.00 - 1500.00 = 8500.00 kg of virgin
    # glass and a per-run fraction of 1500 / 10000 = 0.1500.
    assert_close(melting["total_charge_kg"], EXPECTED_TOTAL_CHARGE_KG, 2, "total_charge_kg")
    assert_close(
        melting["allowed_cullet_kg"], EXPECTED_ALLOWED_CULLET_KG, 2, "allowed_cullet_kg"
    )
    assert_close(melting["cullet_charged_kg"], 1500.00, 2, "cullet_charged_kg")
    assert_close(melting["virgin_batch_kg"], 8500.00, 2, "virgin_batch_kg")
    assert_close(melting["cullet_fraction"], 0.1500, 4, "cullet_fraction")

    charged = fx.get_cullet_batch(client, batch["id"])
    assert_field_equals(charged, "status", "CHARGED")
    assert_field_equals(charged, "charged_run_id", ctx["run_id"])


def test_packaging_a_run_that_is_still_melting_is_refused(
    client: InsulationApiClient,
) -> None:
    """PRD 3.4: "Packaging advances the run `CURING -> PACKAGED` and takes
    `bags_produced`, the whole count of bags baled off the line, which must be positive."

    Design: Corner/state_machines/packaging_a_run_that_is_still_melting_returns_invalid_state
    """
    ctx = _melting_run(client)
    assert_field_equals(ctx["run"], "run_status", "MELTING")

    # A MELTING run has no binder on it yet, so the refusal may be reported either as the
    # missing edge (PRD 2.8 rung 8) or as the unmet non-zero `binder_applied_kg`
    # requirement (PRD 3.4, rung 5).
    validate_error_is_one_of(
        client.package_run(
            ctx["run_id"], BAGS_PRODUCED, plant_operator_headers(ctx["plant_id"])
        ),
        [ApiErrors.INVALID_STATE, ApiErrors.INVALID_REQUEST],
    )

    run = fx.get_run(client, ctx["run_id"])
    assert_field_equals(run, "run_status", "MELTING")
    # No finished-goods lot exists, because only a successful packaging creates one.
    assert fx.lots_for_run(client, ctx["run_id"]) == []


def test_closing_or_releasing_a_melting_run_is_refused_as_a_missing_edge(
    client: InsulationApiClient,
) -> None:
    """PRD 2.8 rung 8: "The target row's current state permits the requested transition -
    `ERR_INVALID_STATE`." PRD 3.4: "Closing advances the run `PACKAGED -> CLOSED` and
    stamps `closed_at` with the logical clock's current reading."; "Releasing a hold is
    the only way a `HELD` run returns to `SCHEDULED`".

    Design: Corner/state_machines/packaging_a_run_that_is_still_melting_returns_invalid_state
    """
    ctx = _melting_run(client)

    # Closing is reachable only from PACKAGED, and releasing a hold only from HELD.
    validate_error(
        client.close_run(ctx["run_id"], plant_operator_headers(ctx["plant_id"])),
        ApiErrors.INVALID_STATE,
    )
    validate_error(
        client.release_hold(ctx["run_id"], plant_operator_headers(ctx["plant_id"])),
        ApiErrors.INVALID_STATE,
    )

    run = fx.get_run(client, ctx["run_id"])
    assert_field_equals(run, "run_status", "MELTING")
    assert run["closed_at"] is None
    assert run["hold_reason"] is None


def test_a_second_start_cure_on_the_same_run_is_rejected_and_changes_nothing(
    client: InsulationApiClient,
) -> None:
    """PRD 2.8: "It equally covers every repeat of an already-applied trigger and every
    trigger aimed at a row already in a terminal state."

    Design: Corner/state_machines/a_second_start_cure_on_the_same_run_is_rejected
    """
    ctx = _curing_run(client)
    first = ctx["run"]
    assert_field_equals(first, "run_status", "CURING")
    # 120 ft / 40 fpm * 60 = 180.00 s dwell; ratio 180 / 150 = 1.2; margin
    # (470 - 420) / 60 clamped = 0.8333...; index 1.2 * 1.8333... / 2 * 100 = 110.00.
    assert_close(first["dwell_s"], EXPECTED_DWELL_S, 2, "dwell_s")
    assert_close(first["cure_index"], EXPECTED_CURE_INDEX, 2, "cure_index")
    assert_close(first["voc_kg"], 2.8800, 4, "voc_kg")

    # A replay whose measurements would have scored a legal but different index: 120 / 30
    # * 60 = 240.00 s dwell, ratio capped at 1.25, margin (480 - 420) / 60 = 1, so
    # 1.25 * 2 / 2 * 100 = 125.00, with VOC 500 * 3.2 / 1000 = 1.6000 kg.
    validate_error(
        client.start_cure(
            ctx["run_id"],
            f.start_cure_payload(
                avg_zone_temp_f=480.0, line_speed_fpm=30.0, binder_applied_kg=500.0
            ),
            plant_operator_headers(ctx["plant_id"]),
        ),
        ApiErrors.INVALID_STATE,
    )

    run = fx.get_run(client, ctx["run_id"])
    assert_field_equals(run, "run_status", "CURING")
    assert_close(run["dwell_s"], EXPECTED_DWELL_S, 2, "dwell_s")
    assert_close(run["cure_index"], EXPECTED_CURE_INDEX, 2, "cure_index")
    assert_close(run["binder_applied_kg"], 900.00, 2, "binder_applied_kg")
    assert_close(run["formaldehyde_kg"], 0.0000, 4, "formaldehyde_kg")
    assert_close(run["voc_kg"], 2.8800, 4, "voc_kg")


def test_aborting_a_closed_run_is_rejected_by_terminal_state_lockdown(
    client: InsulationApiClient,
) -> None:
    """PRD 3.4: "Aborting is the compensating exit and is available from `SCHEDULED`,
    `MELTING` or `CURING`, each landing on the terminal `ABORTED`."

    Design: Corner/state_machines/aborting_a_closed_run_is_rejected_by_terminal_state_lockdown
    """
    ctx = _packaged_run(client)
    # Closing requires the run to have been sampled at least once, so the lab is asked
    # for a test before the run is closed.
    fx.request_thermal_test(
        client,
        ctx["run_id"],
        ctx["sku_id"],
        ctx["program_id"],
        window_start="2026-08-03T10:00:00Z",
        window_end="2026-08-03T16:00:00Z",
    )
    closed = get_success_data(
        client.close_run(ctx["run_id"], plant_operator_headers(ctx["plant_id"]))
    )
    assert_field_equals(closed, "run_status", "CLOSED")

    validate_error(
        client.abort_run(
            ctx["run_id"], "line fire", plant_operator_headers(ctx["plant_id"])
        ),
        ApiErrors.INVALID_STATE,
    )

    run = fx.get_run(client, ctx["run_id"])
    assert_field_equals(run, "run_status", "CLOSED")
    assert run["closed_at"] is not None
    # The abort's unwind never ran: the charge ledger still reads as it did at melt start.
    assert_close(run["total_charge_kg"], EXPECTED_TOTAL_CHARGE_KG, 2, "total_charge_kg")
    assert_close(run["virgin_batch_kg"], EXPECTED_TOTAL_CHARGE_KG, 2, "virgin_batch_kg")


def test_a_closed_run_cannot_be_packaged_or_closed_again(
    client: InsulationApiClient,
) -> None:
    """PRD 2.8: "It equally covers every repeat of an already-applied trigger and every
    trigger aimed at a row already in a terminal state."

    Design: Corner/state_machines/aborting_a_closed_run_is_rejected_by_terminal_state_lockdown
    """
    ctx = _packaged_run(client)
    fx.request_thermal_test(
        client,
        ctx["run_id"],
        ctx["sku_id"],
        ctx["program_id"],
        window_start="2026-08-03T10:00:00Z",
        window_end="2026-08-03T16:00:00Z",
    )
    get_success_data(
        client.close_run(ctx["run_id"], plant_operator_headers(ctx["plant_id"]))
    )

    # The run already carries 900 kg of binder and a cure index of 110.00, so nothing but
    # the terminal state can explain either refusal.
    validate_error(
        client.package_run(
            ctx["run_id"], BAGS_PRODUCED, plant_operator_headers(ctx["plant_id"])
        ),
        ApiErrors.INVALID_STATE,
    )
    validate_error(
        client.close_run(ctx["run_id"], plant_operator_headers(ctx["plant_id"])),
        ApiErrors.INVALID_STATE,
    )

    run = fx.get_run(client, ctx["run_id"])
    assert_field_equals(run, "run_status", "CLOSED")
    # The repeated packaging did not double the area or mint a second lot.
    assert_close(run["produced_sqft"], EXPECTED_PRODUCED_SQFT, 2, "produced_sqft")
    assert len(fx.lots_for_run(client, ctx["run_id"])) == 1


def test_start_melt_one_minute_before_the_scheduled_window_opens_is_rejected(
    client: InsulationApiClient,
) -> None:
    """PRD 3.4: "the logical clock must have reached or passed `scheduled_start`, because a
    run may not be started before its scheduled window opens, and an early attempt is
    refused with `ERR_INVALID_STATE`".

    Design: Corner/state_machines/start_melt_before_the_scheduled_window_opens_is_rejected
    """
    ctx = _scheduled_run(client, clock=ONE_MINUTE_EARLY)
    batch = fx.stage_cullet(client, ctx["plant_id"], 1500.00)

    validate_error(
        client.start_melt(
            ctx["run_id"], [batch["id"]], plant_operator_headers(ctx["plant_id"])
        ),
        ApiErrors.INVALID_STATE,
    )

    run = fx.get_run(client, ctx["run_id"])
    assert_field_equals(run, "run_status", "SCHEDULED")
    assert run["total_charge_kg"] is None
    # The refused charge consumed nothing: the batch is still on the yard.
    untouched = fx.get_cullet_batch(client, batch["id"])
    assert_field_equals(untouched, "status", "STAGED")
    assert untouched["charged_run_id"] is None
    # And the plant's glass ledger never moved.
    plant = fx.get_plant(client, ctx["plant_id"])
    assert_close(plant["cullet_charged_kg_ytd"], 0.00, 2, "cullet_charged_kg_ytd")
    assert_close(plant["total_charge_kg_ytd"], 0.00, 2, "total_charge_kg_ytd")


def test_start_melt_at_the_exact_scheduled_start_instant_is_accepted(
    client: InsulationApiClient,
) -> None:
    """PRD 3.4: "the logical clock must have reached or passed `scheduled_start`, because a
    run may not be started before its scheduled window opens, and an early attempt is
    refused with `ERR_INVALID_STATE`".

    Design: Corner/state_machines/start_melt_before_the_scheduled_window_opens_is_rejected
    """
    ctx = _scheduled_run(client, clock=RUN_START)

    # The clock reads exactly `scheduled_start`, which counts as reached.
    melting = get_success_data(
        client.start_melt(ctx["run_id"], [], plant_operator_headers(ctx["plant_id"]))
    )

    assert_field_equals(melting, "run_status", "MELTING")
    assert_close(melting["total_charge_kg"], EXPECTED_TOTAL_CHARGE_KG, 2, "total_charge_kg")


def test_packaging_cascade_creates_exactly_one_available_lot_for_the_run(
    client: InsulationApiClient,
) -> None:
    """PRD 3.4: "On success `produced_sqft` on the run is `bags_produced` multiplied by the
    SKU's `bag_sqft`, and the server cascade-creates exactly one finished-goods lot:
    status `AVAILABLE`, `parent_lot_id` null, `bags` equal to `bags_produced`,
    `produced_sqft` equal to the run's `produced_sqft`, `allocated_sqft` 0.00 and
    `available_sqft` equal to `produced_sqft`."

    Design: Corner/state_machines/packaging_creates_exactly_one_inventory_lot_for_the_run
    """
    ctx = _curing_run(client)
    # Nothing exists before the baling step.
    assert fx.lots_for_run(client, ctx["run_id"]) == []

    packaged = fx.package_run(
        client, ctx["plant_id"], ctx["run_id"], bags_produced=BAGS_PRODUCED
    )
    assert_field_equals(packaged, "run_status", "PACKAGED")
    # 120 bags * 88.0 sqft = 10560.00 sqft.
    assert_close(packaged["produced_sqft"], EXPECTED_PRODUCED_SQFT, 2, "produced_sqft")

    # The lot appears in no response body; it is found only by filtering the collection.
    lots, _meta = validate_paginated(
        client.list_inventory_lots(
            corporate_ops_headers(), {"production_run_id": ctx["run_id"], "limit": 100}
        )
    )
    assert len(lots) == 1, f"expected exactly one cascade-created lot, got {len(lots)}"
    lot = lots[0]
    assert_field_equals(lot, "status", "AVAILABLE")
    assert lot["parent_lot_id"] is None
    assert_field_equals(lot, "production_run_id", ctx["run_id"])
    assert_field_equals(lot, "bags", BAGS_PRODUCED)
    assert_close(lot["produced_sqft"], EXPECTED_PRODUCED_SQFT, 2, "produced_sqft")
    assert_close(lot["allocated_sqft"], 0.00, 2, "allocated_sqft")
    assert_close(lot["available_sqft"], EXPECTED_PRODUCED_SQFT, 2, "available_sqft")


SUSPENSION_DAY_START = "2026-08-04T06:00:00Z"
SUSPENSION_DAY_END = "2026-08-04T14:00:00Z"


def _sku_with_a_scheduled_and_a_curing_run(
    client: InsulationApiClient,
) -> Dict[str, Any]:
    """A CERTIFIED SKU carrying one run still SCHEDULED, one already CURING, and an OPEN
    allocation cycle."""
    ctx = fx.certified_sku_with_lot(client, sku_overrides=dict(SKU_PL_A))
    assert_field_equals(ctx["sku"], "certification_status", "CERTIFIED")

    scheduled = fx.schedule_run(
        client,
        ctx["plant_id"],
        ctx["sku_id"],
        scheduled_start=SUSPENSION_DAY_START,
        scheduled_end=SUSPENSION_DAY_END,
        line_index=1,
        target_pull_kg=TARGET_PULL_KG,
    )
    curing = fx.schedule_run(
        client,
        ctx["plant_id"],
        ctx["sku_id"],
        scheduled_start=SUSPENSION_DAY_START,
        scheduled_end=SUSPENSION_DAY_END,
        line_index=2,
        target_pull_kg=TARGET_PULL_KG,
    )
    cycle = fx.open_cycle(client, ctx["plant_id"], ctx["sku_id"])

    fx.set_clock(client, SUSPENSION_DAY_START)
    fx.start_melt(client, ctx["plant_id"], curing["id"])
    curing = fx.start_cure(client, ctx["plant_id"], curing["id"])

    assert_field_equals(scheduled, "run_status", "SCHEDULED")
    assert_field_equals(curing, "run_status", "CURING")
    assert_field_equals(cycle, "status", "OPEN")

    ctx["scheduled_run_id"] = scheduled["id"]
    ctx["curing_run_id"] = curing["id"]
    ctx["cycle_id"] = cycle["id"]
    return ctx


def test_suspending_a_sku_holds_only_its_scheduled_runs_and_leaves_the_curing_one_running(
    client: InsulationApiClient,
) -> None:
    """PRD 3.6: "`SUSPEND` applies from `CERTIFIED` or from `DERATED`, and both origins
    carry identical consequences: `certification_status` becomes `SUSPENDED`, every
    production run of the SKU whose `run_status` is `SCHEDULED` transitions `SCHEDULED ->
    HELD` with `hold_reason` `PRODUCT_LINE_SUSPENDED`, and every allocation cycle of the
    SKU whose status is `OPEN` or `PROPOSED` transitions to `CANCELLED` with its proposed
    lines revoked."

    Design: Corner/state_machines/suspending_a_sku_holds_only_its_scheduled_runs_and_leaves_the_curing_one_running
    """
    ctx = _sku_with_a_scheduled_and_a_curing_run(client)

    suspended = get_success_data(
        client.sku_certification_decision(
            ctx["sku_id"],
            f.sku_decision_payload("SUSPEND"),
            certification_officer_headers(CERTIFICATION_OFFICER_USER_ID_ALT),
        )
    )
    assert_field_equals(suspended, "certification_status", "SUSPENDED")

    held = fx.get_run(client, ctx["scheduled_run_id"])
    assert_field_equals(held, "run_status", "HELD")
    assert_field_equals(held, "hold_reason", "PRODUCT_LINE_SUSPENDED")

    # The cascade is conditioned on SCHEDULED alone: a run already in the oven keeps
    # running, and so does the packaged one.
    still_curing = fx.get_run(client, ctx["curing_run_id"])
    assert_field_equals(still_curing, "run_status", "CURING")
    assert still_curing["hold_reason"] is None

    packaged = fx.get_run(client, ctx["run_id"])
    assert_field_equals(packaged, "run_status", "PACKAGED")
    assert packaged["hold_reason"] is None

    cancelled = fx.get_cycle(client, ctx["cycle_id"])
    assert_field_equals(cancelled, "status", "CANCELLED")


def test_the_suspension_hold_reaches_exactly_one_run_of_the_sku(
    client: InsulationApiClient,
) -> None:
    """PRD 3.6: "`SUSPEND` applies from `CERTIFIED` or from `DERATED`, and both origins
    carry identical consequences: `certification_status` becomes `SUSPENDED`, every
    production run of the SKU whose `run_status` is `SCHEDULED` transitions `SCHEDULED ->
    HELD` with `hold_reason` `PRODUCT_LINE_SUSPENDED`, and every allocation cycle of the
    SKU whose status is `OPEN` or `PROPOSED` transitions to `CANCELLED` with its proposed
    lines revoked."

    Design: Corner/state_machines/suspending_a_sku_holds_only_its_scheduled_runs_and_leaves_the_curing_one_running
    """
    ctx = _sku_with_a_scheduled_and_a_curing_run(client)
    get_success_data(
        client.sku_certification_decision(
            ctx["sku_id"],
            f.sku_decision_payload("SUSPEND"),
            certification_officer_headers(CERTIFICATION_OFFICER_USER_ID_ALT),
        )
    )

    held, _meta = validate_paginated(
        client.list_production_runs(
            corporate_ops_headers(),
            {"product_line_id": ctx["sku_id"], "run_status": "HELD", "limit": 100},
        )
    )
    assert [row["id"] for row in held] == [ctx["scheduled_run_id"]], (
        "only the SCHEDULED run of the suspended SKU may be held"
    )

    remaining, _meta2 = validate_paginated(
        client.list_production_runs(
            corporate_ops_headers(),
            {"product_line_id": ctx["sku_id"], "run_status": "SCHEDULED", "limit": 100},
        )
    )
    assert remaining == [], "no run of the suspended SKU may still read SCHEDULED"
