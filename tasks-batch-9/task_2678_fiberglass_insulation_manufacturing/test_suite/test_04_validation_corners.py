"""Validation corners: the priority ladder's tie-breaks and the boundary cases that
sit exactly on a declared limit.

Queue B / validations.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import InsulationApiClient
from test_helpers.api_errors import ApiErrors
from test_helpers.assertions import (
    assert_area,
    assert_close,
    assert_emissions,
    assert_field_equals,
)
from test_helpers.constants import SKU_PL_A, SKU_PL_C, ZONES_470
from test_helpers.test_users import (
    certification_officer_headers,
    channel_manager_headers,
    plant_operator_headers,
    quality_engineer_headers,
)

# A phenolic chemistry whose cure envelope (420 F / 150 s) is reachable by the
# 470 F / 40 fpm line settings used below.
PHENOLIC_420 = {
    "formaldehyde_free": False,
    "formaldehyde_ppm": 250,
    "voc_g_per_kg": 4.1,
    "min_cure_temp_f": 420.0,
    "min_dwell_s": 150.0,
    "loi_target_pct": 5.0,
}

# Declared R 13.0 less a 0.30 tolerance puts the conformance floor at 12.70.
WEAK_SPECIMENS = [12.40, 12.90, 12.90]
STRONG_SPECIMENS = [13.10, 13.20, 12.90]


def _reference_data(client: InsulationApiClient) -> Dict[str, Any]:
    """A four-zone, two-line plant with one SKU registered on it."""
    return fx.base_setup(client, sku_overrides=dict(SKU_PL_A))


def _attempt_run(
    client: InsulationApiClient, ctx: Dict[str, Any], **overrides: Any
):
    """POST /production-runs as the plant's own operator, returning the raw response."""
    return client.create_production_run(
        f.production_run_payload(ctx["plant_id"], ctx["sku_id"], **overrides),
        plant_operator_headers(ctx["plant_id"]),
    )


def test_the_zone_array_is_measured_against_the_plants_own_oven_zone_count(
    client: InsulationApiClient,
) -> None:
    """PRD 3.4: "Last, the array length of `zone_setpoints_f` must equal the plant's
    `oven_zone_count` exactly and every setpoint in it must be positive, or the request
    is refused with `ERR_OVEN_ZONE_MISMATCH`."

    Design: Corner/validations/run_zone_setpoints_must_match_the_ovens_zone_count
    """
    ctx = _reference_data(client)
    assert_field_equals(ctx["plant"], "oven_zone_count", 4)

    short = _attempt_run(client, ctx, zone_setpoints_f=[470.0, 470.0, 470.0])
    validate_error(short, ApiErrors.OVEN_ZONE_MISMATCH, 422)

    long = _attempt_run(
        client, ctx, zone_setpoints_f=[470.0, 470.0, 470.0, 470.0, 470.0]
    )
    validate_error(long, ApiErrors.OVEN_ZONE_MISMATCH, 422)

    dead_zone = _attempt_run(client, ctx, zone_setpoints_f=[470.0, 470.0, 470.0, 0.0])
    validate_error(dead_zone, ApiErrors.OVEN_ZONE_MISMATCH, 422)

    accepted = _attempt_run(client, ctx, zone_setpoints_f=list(ZONES_470))
    validate_success(accepted, 201)

    _data, meta = validate_paginated(
        client.list_production_runs(
            plant_operator_headers(ctx["plant_id"]), {"plant_id": ctx["plant_id"]}
        )
    )
    # Only the four-zone request created a row; the three refusals created nothing.
    assert meta["total_count"] == 1, meta


def test_a_line_index_out_of_range_outranks_the_zone_mismatch(
    client: InsulationApiClient,
) -> None:
    """PRD 3.4: "Only after occupancy does the system verify that `line_index` is a whole
    number between 1 and the plant's `production_line_count` inclusive, returning
    `ERR_LINE_INDEX_OUT_OF_RANGE` otherwise; a request that both collides in time and
    names a nonexistent line therefore reports the occupancy conflict."

    PRD 2.8: "This ordering is normative: when a request violates two rules at once,
    only the earlier rung's error identifier may be returned."

    Design: Corner/validations/run_zone_setpoints_must_match_the_ovens_zone_count
    """
    ctx = _reference_data(client)
    assert_field_equals(ctx["plant"], "production_line_count", 2)

    both_wrong = _attempt_run(
        client, ctx, line_index=5, zone_setpoints_f=[470.0, 470.0, 470.0]
    )
    validate_error(both_wrong, ApiErrors.LINE_INDEX_OUT_OF_RANGE, 422)

    _data, meta = validate_paginated(
        client.list_production_runs(
            plant_operator_headers(ctx["plant_id"]), {"plant_id": ctx["plant_id"]}
        )
    )
    assert meta["total_count"] == 0, meta


def _period_exactly_at_allowance(client: InsulationApiClient) -> Dict[str, Any]:
    """One cured run booking 0.2250 kg of formaldehyde against a 0.2250 kg allowance."""
    fx.reset_clock(client)
    program = fx.create_per_specimen_program(client)
    plant = fx.create_plant(client, formaldehyde_allowance_kg=0.225)
    binder = fx.create_certified_binder(client, **PHENOLIC_420)
    sku = fx.create_product_line(
        client, plant["id"], binder["id"], program["id"], **SKU_PL_A
    )
    fx.set_clock(client, "2026-08-03T06:00:00Z")
    cured = fx.schedule_run(
        client,
        plant["id"],
        sku["id"],
        scheduled_start="2026-08-03T06:00:00Z",
        scheduled_end="2026-08-03T14:00:00Z",
        line_index=1,
        zone_setpoints_f=list(ZONES_470),
    )
    fx.start_melt(client, plant["id"], cured["id"])
    cured = fx.start_cure(
        client,
        plant["id"],
        cured["id"],
        avg_zone_temp_f=470.0,
        line_speed_fpm=40.0,
        binder_applied_kg=900.0,
    )
    later = fx.schedule_run(
        client,
        plant["id"],
        sku["id"],
        scheduled_start="2026-08-04T06:00:00Z",
        scheduled_end="2026-08-04T14:00:00Z",
        line_index=2,
        zone_setpoints_f=list(ZONES_470),
    )
    return {
        "plant_id": plant["id"],
        "sku_id": sku["id"],
        "cured": cured,
        "cured_id": cured["id"],
        "later_id": later["id"],
    }


def test_a_mass_landing_exactly_on_its_allowance_does_not_exceed_it(
    client: InsulationApiClient,
) -> None:
    """PRD 3.9: "The exceedance test compares each rolled-up mass against its allowance
    using a **strict** greater-than in both legs: the period exceeded when
    `reported_formaldehyde_kg` is greater than the plant's `formaldehyde_allowance_kg`
    **or** `reported_voc_kg` is greater than its `voc_allowance_kg`."

    PRD 3.9: "A figure landing exactly on its allowance does **not** exceed it."

    Design: Corner/validations/emission_masses_exactly_at_the_permit_allowance_report_without_exceedance
    """
    ctx = _period_exactly_at_allowance(client)
    assert_emissions(ctx["cured"]["formaldehyde_kg"], 0.2250, "formaldehyde_kg")
    assert_emissions(ctx["cured"]["voc_kg"], 3.6900, "voc_kg")

    plant = fx.file_emissions_report(
        client, ctx["plant_id"], "2026-08-01T00:00:00Z", "2026-08-03T06:00:00Z"
    )

    assert_emissions(
        plant["reported_formaldehyde_kg"], 0.2250, "reported_formaldehyde_kg"
    )
    assert_emissions(plant["reported_voc_kg"], 3.6900, "reported_voc_kg")
    assert_close(plant["formaldehyde_allowance_kg"], 0.225, 3, "allowance")
    assert_field_equals(plant, "emissions_status", "REPORTED")
    assert_field_equals(plant, "melt_posture", "OPEN")
    assert plant["posture_reason"] is None, plant["posture_reason"]


def test_the_boundary_period_never_fires_the_freeze_cascade(
    client: InsulationApiClient,
) -> None:
    """PRD 3.9: "Every production run of the plant whose `run_status` is `SCHEDULED`
    transitions `SCHEDULED -> HELD` with `hold_reason` `PLANT_FROZEN`."

    PRD 3.9: "A figure landing exactly on its allowance does **not** exceed it."

    Design: Corner/validations/emission_masses_exactly_at_the_permit_allowance_report_without_exceedance
    """
    ctx = _period_exactly_at_allowance(client)
    fx.file_emissions_report(
        client, ctx["plant_id"], "2026-08-01T00:00:00Z", "2026-08-03T06:00:00Z"
    )

    later = fx.get_run(client, ctx["later_id"])
    assert_field_equals(later, "run_status", "SCHEDULED")
    assert later["hold_reason"] is None, later["hold_reason"]

    # Reporting reads the runs, it does not rewrite them.
    cured = fx.get_run(client, ctx["cured_id"])
    assert_field_equals(cured, "run_status", "CURING")
    assert_emissions(cured["formaldehyde_kg"], 0.2250, "formaldehyde_kg")

    # A frozen plant refuses a cullet stage; this one accepts it.
    batch = fx.stage_cullet(client, ctx["plant_id"], 500.0)
    assert_field_equals(batch, "status", "STAGED")


def test_an_unresolvable_path_id_is_reported_before_the_body_is_examined(
    client: InsulationApiClient,
) -> None:
    """PRD 2.9: "Path identifiers are resolved strictly left to right before any body
    content is examined, and the leftmost unresolved identifier decides the error."

    Design: Corner/validations/the_error_ladder_prefers_path_404_over_shape_400_over_body_404
    """
    ctx = _reference_data(client)

    # avg_zone_temp_f 0.0 is shape-illegal as well, but the run id does not resolve.
    response = client.start_cure(
        NON_EXISTENT_UUID,
        f.start_cure_payload(
            avg_zone_temp_f=0.0, line_speed_fpm=40.0, binder_applied_kg=900.0
        ),
        plant_operator_headers(ctx["plant_id"]),
    )
    validate_error(response, ApiErrors.PRODUCTION_RUN_NOT_FOUND, 404)


def test_a_malformed_shape_is_reported_before_an_unresolvable_body_foreign_key(
    client: InsulationApiClient,
) -> None:
    """PRD 2.9: "Body foreign keys are resolved only after the request shape has been
    accepted, and they are resolved in the order the endpoint declares them."

    PRD 2.8: "This ordering is normative: when a request violates two rules at once,
    only the earlier rung's error identifier may be returned."

    Design: Corner/validations/the_error_ladder_prefers_path_404_over_shape_400_over_body_404
    """
    ctx = _reference_data(client)
    headers = plant_operator_headers(NON_EXISTENT_UUID)

    inverted = client.create_production_run(
        f.production_run_payload(
            NON_EXISTENT_UUID,
            ctx["sku_id"],
            scheduled_start="2026-08-03T06:00:00Z",
            scheduled_end="2026-08-03T05:00:00Z",
            zone_setpoints_f=list(ZONES_470),
        ),
        headers,
    )
    validate_error(inverted, ApiErrors.INVALID_REQUEST, 400)

    # The very same body with a legal interval finally surfaces the missing plant.
    legal_interval = client.create_production_run(
        f.production_run_payload(
            NON_EXISTENT_UUID,
            ctx["sku_id"],
            scheduled_start="2026-08-03T06:00:00Z",
            scheduled_end="2026-08-03T14:00:00Z",
            zone_setpoints_f=list(ZONES_470),
        ),
        headers,
    )
    validate_error(legal_interval, ApiErrors.PLANT_NOT_FOUND, 404)


def _held_lot_and_open_cycle(client: InsulationApiClient) -> Dict[str, Any]:
    """A conforming 10560.00 sqft lot put on manual hold, with demand waiting for it.

    The order asks for 17600.00 sqft — twice the 8800.00 sqft draw the tests below
    attempt — so a single satisfied draw leaves the order `PARTIAL` rather than
    flipping it to `ALLOCATED`; PRD 3.8 requires the order to be `SUBMITTED`,
    `PARTIAL` or `BACKORDERED` for a manual line, and that state gate sits ahead of
    the balance rule the second draw is meant to trip.
    """
    ctx = fx.certified_sku_with_lot(client)
    order = fx.place_order(client, ctx["sku_id"], 17600.0)
    cycle = fx.open_cycle(client, ctx["plant_id"], ctx["sku_id"])
    fx.quarantine_lot(client, ctx["lot_id"], quarantine_note="moisture check")
    ctx.update(
        {
            "order": order,
            "order_id": order["id"],
            "cycle": cycle,
            "cycle_id": cycle["id"],
        }
    )
    return ctx


def _line_attempt(client: InsulationApiClient, ctx: Dict[str, Any], sqft: float):
    """Cut a manual expedite line against the freshly-read cycle version."""
    version = int(fx.get_cycle(client, ctx["cycle_id"])["version"])
    return client.create_allocation_line(
        f.allocation_line_payload(
            ctx["cycle_id"], ctx["order_id"], ctx["lot_id"], sqft, version
        ),
        channel_manager_headers(),
    )


def test_a_held_lot_reports_its_quarantine_rather_than_its_zero_balance(
    client: InsulationApiClient,
) -> None:
    """PRD 3.8: "The cycle must be `OPEN` or `PROPOSED`; the order must be `SUBMITTED`,
    `PARTIAL` or `BACKORDERED` and its `product_line_id` must equal the cycle's; the lot
    must be `AVAILABLE` or `ALLOCATED` with its `product_line_id` and `plant_id` both
    matching the cycle's, and it must not be `QUARANTINED` or the request is refused with
    `ERR_LOT_QUARANTINED`; `allocated_sqft` must be an exact positive multiple of the
    SKU's `bag_sqft` or the request is refused with `ERR_BAG_MULTIPLE_MISMATCH`; and
    finally `allocated_sqft` must not exceed the lot's `available_sqft` and must not push
    the order's `allocated_sqft` above its `requested_sqft`, or the request is refused
    with `ERR_ALLOCATION_EXCEEDS_LOT_AVAILABLE`."

    Design: Corner/validations/a_quarantined_lot_reports_quarantine_not_an_exhausted_balance
    """
    ctx = _held_lot_and_open_cycle(client)

    held = fx.get_lot(client, ctx["lot_id"])
    assert_field_equals(held, "status", "QUARANTINED")
    assert_field_equals(held, "quarantine_reason", "MANUAL_HOLD")
    assert_area(held["available_sqft"], 0.00, "available_sqft")

    # The 0.00 balance would also justify ERR_ALLOCATION_EXCEEDS_LOT_AVAILABLE.
    validate_error(
        _line_attempt(client, ctx, 8800.0), ApiErrors.LOT_QUARANTINED, 409
    )


def test_once_released_the_same_line_is_cut_and_the_repeat_hits_the_balance_rule(
    client: InsulationApiClient,
) -> None:
    """PRD 3.8: "The cycle must be `OPEN` or `PROPOSED`; the order must be `SUBMITTED`,
    `PARTIAL` or `BACKORDERED` and its `product_line_id` must equal the cycle's; the lot
    must be `AVAILABLE` or `ALLOCATED` with its `product_line_id` and `plant_id` both
    matching the cycle's, and it must not be `QUARANTINED` or the request is refused with
    `ERR_LOT_QUARANTINED`; `allocated_sqft` must be an exact positive multiple of the
    SKU's `bag_sqft` or the request is refused with `ERR_BAG_MULTIPLE_MISMATCH`; and
    finally `allocated_sqft` must not exceed the lot's `available_sqft` and must not push
    the order's `allocated_sqft` above its `requested_sqft`, or the request is refused
    with `ERR_ALLOCATION_EXCEEDS_LOT_AVAILABLE`."

    Design: Corner/validations/a_quarantined_lot_reports_quarantine_not_an_exhausted_balance
    """
    ctx = _held_lot_and_open_cycle(client)

    released = get_success_data(
        client.release_lot(ctx["lot_id"], quality_engineer_headers())
    )
    assert_field_equals(released, "status", "AVAILABLE")
    assert_area(released["available_sqft"], 10560.00, "available_sqft")

    line = get_success_data(_line_attempt(client, ctx, 8800.0), 201)
    assert_field_equals(line, "status", "ALLOCATED")
    assert_field_equals(line, "bags", 100)
    assert_area(line["allocated_sqft"], 8800.00, "allocated_sqft")

    booked = fx.get_lot(client, ctx["lot_id"])
    assert_area(booked["allocated_sqft"], 8800.00, "allocated_sqft")
    assert_area(booked["available_sqft"], 1760.00, "available_sqft")

    # The repeat carries a refreshed cycle version, so it fails on the balance itself.
    validate_error(
        _line_attempt(client, ctx, 8800.0),
        ApiErrors.ALLOCATION_EXCEEDS_LOT_AVAILABLE,
        422,
    )


def _quarantined_by_cascade(client: InsulationApiClient) -> Dict[str, Any]:
    """A packaged run judged NONCONFORMING, whose lot the cascade has quarantined."""
    ctx = fx.base_setup(client)
    run = fx.run_to_packaged(client, ctx["plant_id"], ctx["sku_id"])
    lot = fx.lot_for_run(client, run["id"])
    test = fx.completed_thermal_test(
        client, run["id"], ctx["sku_id"], ctx["program_id"], WEAK_SPECIMENS
    )
    ctx.update(
        {
            "run": run,
            "run_id": run["id"],
            "lot": lot,
            "lot_id": lot["id"],
            "test": test,
            "test_id": test["id"],
        }
    )
    return ctx


def test_a_release_is_refused_while_the_originating_run_reads_nonconforming(
    client: InsulationApiClient,
) -> None:
    """PRD 3.7: "The gate is a cross-entity one: the originating run's `qc_status` must
    read exactly `CONFORMING`, or the release is refused with `ERR_RUN_NOT_CONFORMING`."

    Design: Corner/validations/releasing_a_held_lot_depends_on_the_qc_state_of_a_different_entity
    """
    ctx = _quarantined_by_cascade(client)
    assert_field_equals(ctx["test"], "conformance_verdict", "NONCONFORMING")

    # Nobody called the quarantine endpoint; the verdict cascade did this.
    lot = fx.get_lot(client, ctx["lot_id"])
    assert_field_equals(lot, "status", "QUARANTINED")
    assert_field_equals(lot, "quarantine_reason", "RUN_NONCONFORMING")
    assert_area(lot["available_sqft"], 0.00, "available_sqft")

    run = fx.get_run(client, ctx["run_id"])
    assert_field_equals(run, "qc_status", "NONCONFORMING")

    validate_error(
        client.release_lot(ctx["lot_id"], quality_engineer_headers()),
        ApiErrors.RUN_NOT_CONFORMING,
        409,
    )


def test_the_same_release_is_accepted_only_after_the_run_turns_conforming(
    client: InsulationApiClient,
) -> None:
    """PRD 3.7: "A run still `RETEST_PENDING`, still `NONCONFORMING` or never sampled
    cannot have its lots released, which is precisely why a conforming retest result
    frees the operator to release lots one at a time rather than releasing them itself."

    Design: Corner/validations/releasing_a_held_lot_depends_on_the_qc_state_of_a_different_entity
    """
    ctx = _quarantined_by_cascade(client)

    retest = get_success_data(
        client.request_retest(
            ctx["test_id"],
            f.retest_window_payload("2026-08-04T08:00:00Z", "2026-08-04T12:00:00Z"),
            quality_engineer_headers(),
        )
    )
    assert_field_equals(retest, "attempt_number", 2)
    assert_field_equals(fx.get_run(client, ctx["run_id"]), "qc_status", "RETEST_PENDING")
    validate_error(
        client.release_lot(ctx["lot_id"], quality_engineer_headers()),
        ApiErrors.RUN_NOT_CONFORMING,
        409,
    )

    cleared = get_success_data(
        client.record_result(
            ctx["test_id"], STRONG_SPECIMENS, quality_engineer_headers()
        )
    )
    assert_field_equals(cleared, "conformance_verdict", "CONFORMING")
    assert_field_equals(fx.get_run(client, ctx["run_id"]), "qc_status", "CONFORMING")

    # The conforming retest did not walk the quarantine back by itself.
    assert_field_equals(fx.get_lot(client, ctx["lot_id"]), "status", "QUARANTINED")

    released = get_success_data(
        client.release_lot(ctx["lot_id"], quality_engineer_headers())
    )
    assert_field_equals(released, "status", "AVAILABLE")
    assert released["quarantine_reason"] is None, released["quarantine_reason"]
    assert_area(released["available_sqft"], 10560.00, "available_sqft")


def _two_programs_awaiting_a_verdict(client: InsulationApiClient) -> Dict[str, Any]:
    """The same specimen data on two SKUs whose programs differ only in policy."""
    fx.reset_clock(client)
    per_specimen = fx.create_per_specimen_program(client)
    lot_mean = fx.create_lot_mean_program(client, derate_allowed=False)
    plant = fx.create_plant(client)
    binder = fx.create_certified_binder(client)
    sku_ps = fx.create_product_line(
        client, plant["id"], binder["id"], per_specimen["id"], **SKU_PL_A
    )
    sku_lm = fx.create_product_line(
        client, plant["id"], binder["id"], lot_mean["id"], **SKU_PL_C
    )
    fx.submit_sku(client, sku_ps["id"])
    fx.submit_sku(client, sku_lm["id"])
    run_ps = fx.run_to_curing(client, plant["id"], sku_ps["id"], line_index=1)
    run_lm = fx.run_to_curing(client, plant["id"], sku_lm["id"], line_index=2)
    test_ps = fx.completed_thermal_test(
        client, run_ps["id"], sku_ps["id"], per_specimen["id"], WEAK_SPECIMENS
    )
    test_lm = fx.completed_thermal_test(
        client, run_lm["id"], sku_lm["id"], lot_mean["id"], WEAK_SPECIMENS
    )
    return {
        "sku_ps_id": sku_ps["id"],
        "sku_lm_id": sku_lm["id"],
        "test_ps": test_ps,
        "test_lm": test_lm,
    }


def test_a_derate_is_refused_when_the_program_forbids_it(
    client: InsulationApiClient,
) -> None:
    """PRD 3.6: "It requires the SKU to be `PENDING_CERTIFICATION`, the program's
    `derate_allowed` to be true, and the SKU's most recently created thermal test - taken
    in `created_at` ascending order and using the **last** row - to have status
    `COMPLETED` or `EXHAUSTED` with a non-null `mean_r_value`."

    PRD 3.6: "The resulting `effective_declared_r_value` must be strictly greater than 0
    **and** strictly less than `declared_r_value`, and any failure of the
    `derate_allowed` flag, the test-availability requirement or that strict band is
    refused with `ERR_DERATE_NOT_PERMITTED`."

    Design: Corner/validations/derate_is_only_offered_when_the_program_allows_it
    """
    ctx = _two_programs_awaiting_a_verdict(client)

    # The lot-mean read of the very same specimens actually conforms; the flag is
    # checked regardless, and 12.73 would have snapped down to a legal 12.50.
    assert_field_equals(ctx["test_lm"], "conformance_verdict", "CONFORMING")
    assert_close(ctx["test_lm"]["mean_r_value"], 12.73, 2, "mean_r_value")

    refused = client.sku_certification_decision(
        ctx["sku_lm_id"],
        f.sku_decision_payload("DERATE", decision_note="lot mean is short"),
        certification_officer_headers(),
    )
    validate_error(refused, ApiErrors.DERATE_NOT_PERMITTED, 422)

    sku = fx.get_product_line(client, ctx["sku_lm_id"])
    assert_field_equals(sku, "certification_status", "PENDING_CERTIFICATION")
    assert sku["effective_declared_r_value"] is None, sku


def test_the_identical_derate_is_granted_when_the_program_allows_it(
    client: InsulationApiClient,
) -> None:
    """PRD 3.6: "The derated figure is snapped down onto a half-point grid: the basis
    value is that test's `min_r_value` when the program's `conformance_basis` is
    `PER_SPECIMEN` and its `mean_r_value` when the basis is `LOT_MEAN`; divide the basis
    value by a derate step of 0.5 and take the floor to a whole number of steps; multiply
    the step count back by 0.5 and quantize to two decimal places."

    Design: Corner/validations/derate_is_only_offered_when_the_program_allows_it
    """
    ctx = _two_programs_awaiting_a_verdict(client)

    assert_field_equals(ctx["test_ps"], "conformance_verdict", "NONCONFORMING")
    assert_close(ctx["test_ps"]["min_r_value"], 12.40, 2, "min_r_value")

    derated = get_success_data(
        client.sku_certification_decision(
            ctx["sku_ps_id"],
            f.sku_decision_payload("DERATE", decision_note="worst specimen is short"),
            certification_officer_headers(),
        )
    )

    assert_field_equals(derated, "certification_status", "DERATED")
    # 12.40 / 0.5 floors to 24 steps, and 24 * 0.5 is 12.00.
    assert_close(derated["effective_declared_r_value"], 12.00, 2, "effective_r")
    assert_field_equals(derated, "certified_by_user_id", "co-1")
    assert_field_equals(derated, "nonconformance_count", 0)
