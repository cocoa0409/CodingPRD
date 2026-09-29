"""Error-catalogue corners: every refusal the plant can raise on a well-formed request.

Each test below is a single-fault probe - the request under test is valid in every
respect except the one rule being asserted, so the global validation priority ladder
cannot legitimately answer with a different, higher-priority error identifier.
"""

from typing import Any, Dict, List

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import InsulationApiClient
from test_helpers.api_errors import ApiErrors
from test_helpers.assertions import assert_close, assert_field_equals
from test_helpers.constants import SKU_PL_A, SKU_PL_C
from test_helpers.test_users import (
    certification_officer_headers,
    channel_buyer_headers,
    channel_manager_headers,
    corporate_ops_headers,
    environmental_compliance_headers,
    plant_operator_headers,
    quality_engineer_headers,
)

# --- Shared scenario builders -------------------------------------------------


def _plant_at_the_restrict_level(client: InsulationApiClient) -> Dict[str, Any]:
    """Charge 2800.00 kg of cullet into a 10000.00 kg melt so the ratio lands on 0.2800.

    The plant's `cullet_restrict_fraction` is 0.28, so the charge tightens the melt
    posture to RESTRICTED by equality.
    """
    ctx = fx.base_setup(client)
    batches = fx.stage_cullet_batches(client, ctx["plant_id"], [1500.00, 1300.00])
    run = fx.run_to_melting(
        client,
        ctx["plant_id"],
        ctx["sku_id"],
        [batches[0]["id"], batches[1]["id"]],
    )
    ctx.update({"batches": batches, "run": run, "run_id": run["id"]})
    return ctx


def _run_with_a_rejected_batch(client: InsulationApiClient) -> Dict[str, Any]:
    """Two staged batches, the second rejected, and a SCHEDULED run at its start."""
    ctx = fx.base_setup(client)
    batches = fx.stage_cullet_batches(client, ctx["plant_id"], [1500.00, 1300.00])
    get_success_data(
        client.reject_cullet_batch(
            batches[1]["id"],
            "organic contamination on the screen",
            plant_operator_headers(ctx["plant_id"]),
        )
    )
    run = fx.schedule_run(client, ctx["plant_id"], ctx["sku_id"])
    fx.set_clock(client, "2026-08-02T06:00:00Z")
    ctx.update({"batches": batches, "run": run, "run_id": run["id"]})
    return ctx


def _test_in_lab(client: InsulationApiClient) -> Dict[str, Any]:
    """A thermal test of a CURING run, moved into the laboratory on attempt 1."""
    ctx = fx.base_setup(client)
    run = fx.run_to_curing(client, ctx["plant_id"], ctx["sku_id"])
    test = fx.request_thermal_test(client, run["id"], ctx["sku_id"], ctx["program_id"])
    get_success_data(client.start_lab(test["id"], quality_engineer_headers()))
    ctx.update({"run": run, "run_id": run["id"], "test": test, "test_id": test["id"]})
    return ctx


def _open_changeover(client: InsulationApiClient) -> Dict[str, Any]:
    """A PACKAGED outgoing run, a SCHEDULED incoming run, and an OPEN purge window.

    The logical clock is left at 2026-08-03T06:00:00Z, before the window's end.
    """
    ctx = fx.base_setup(client, sku_overrides=dict(SKU_PL_A))
    sku_incoming = fx.create_product_line(
        client,
        ctx["plant_id"],
        ctx["binder_id"],
        ctx["program_id"],
        **dict(SKU_PL_C),
    )
    outgoing = fx.schedule_run(
        client,
        ctx["plant_id"],
        ctx["sku_id"],
        scheduled_start="2026-08-03T06:00:00Z",
        scheduled_end="2026-08-03T14:00:00Z",
    )
    fx.set_clock(client, "2026-08-03T06:00:00Z")
    fx.start_melt(client, ctx["plant_id"], outgoing["id"], [])
    fx.start_cure(client, ctx["plant_id"], outgoing["id"])
    outgoing = fx.package_run(client, ctx["plant_id"], outgoing["id"], 120)
    incoming = fx.schedule_run(
        client,
        ctx["plant_id"],
        sku_incoming["id"],
        scheduled_start="2026-08-03T14:00:00Z",
        scheduled_end="2026-08-03T22:00:00Z",
    )
    changeover = get_success_data(
        client.create_changeover(
            f.changeover_payload(
                ctx["plant_id"],
                outgoing["id"],
                incoming["id"],
                1,
                "2026-08-03T13:30:00Z",
                "2026-08-03T14:30:00Z",
            ),
            plant_operator_headers(ctx["plant_id"]),
        ),
        201,
    )
    ctx.update(
        {
            "sku_incoming": sku_incoming,
            "outgoing": outgoing,
            "outgoing_id": outgoing["id"],
            "incoming": incoming,
            "changeover": changeover,
            "changeover_id": changeover["id"],
        }
    )
    return ctx


def _melting_run_on_a_free_binder(client: InsulationApiClient) -> Dict[str, Any]:
    """A MELTING run whose binder cures at 420 F over a 150 s minimum dwell."""
    fx.reset_clock(client)
    program = fx.create_per_specimen_program(client)
    plant = fx.create_plant(client)
    binder = fx.create_certified_formaldehyde_free_binder(client)
    sku = fx.create_product_line(client, plant["id"], binder["id"], program["id"])
    run = fx.run_to_melting(client, plant["id"], sku["id"])
    return {
        "program": program,
        "plant": plant,
        "plant_id": plant["id"],
        "binder": binder,
        "sku": sku,
        "sku_id": sku["id"],
        "run": run,
        "run_id": run["id"],
    }


def _binder_at_the_revision_ceiling(client: InsulationApiClient) -> Dict[str, Any]:
    """Walk a formulation twice around the revision loop, then park it awaiting a third.

    After two accepted REVISE decisions `revision_count` is 2, and a third
    REQUEST_REVISION leaves the row back in REVISION_REQUIRED.
    """
    fx.reset_clock(client)
    binder = fx.create_draft_binder(
        client, formaldehyde_free=False, formaldehyde_ppm=200, voc_g_per_kg=4.0
    )
    binder_id = binder["id"]
    chemistry = [(180, 3.8), (150, 3.5), (120, 3.2)]
    for index, (ppm, voc) in enumerate(chemistry):
        get_success_data(client.submit_binder(binder_id, quality_engineer_headers()))
        measured = chemistry[index - 1] if index else (200, 4.0)
        get_success_data(
            client.record_binder_emissions_test(
                binder_id,
                f.binder_emissions_test_payload(
                    measured[0], measured[1], f"LAB-920{index + 1}"
                ),
                certification_officer_headers(),
            )
        )
        get_success_data(
            client.binder_certification_decision(
                binder_id,
                f.binder_decision_payload(
                    "REQUEST_REVISION", revision_notes=f"attempt {index + 1} short"
                ),
                certification_officer_headers(),
            )
        )
        if index == 2:
            break
        revised = get_success_data(
            client.revise_binder(
                binder_id,
                f.binder_revise_payload(
                    "REVISE",
                    formaldehyde_free=False,
                    formaldehyde_ppm=ppm,
                    voc_g_per_kg=voc,
                    min_cure_temp_f=420.0,
                    min_dwell_s=150.0,
                    loi_target_pct=4.5,
                ),
                quality_engineer_headers(),
            )
        )
        assert_field_equals(revised, "revision_count", index + 1)
    return {"binder_id": binder_id}


# --- Unresolved path identifiers ---------------------------------------------


def test_each_single_row_route_reports_its_own_not_found_code(
    client: InsulationApiClient,
) -> None:
    """PRD 2.9: "The twelve not-found identifiers are `ERR_PLANT_NOT_FOUND` (for
    `plantId` in a path or `plant_id` in a body), `ERR_CERTIFICATION_PROGRAM_NOT_FOUND`
    (`programId`, `certification_program_id`), `ERR_BINDER_FORMULATION_NOT_FOUND`
    (`binderId`, `binder_formulation_id`), `ERR_PRODUCT_LINE_NOT_FOUND`
    (`productLineId`, `product_line_id`), `ERR_PRODUCTION_RUN_NOT_FOUND` (`runId`, and
    `production_run_id`, `outgoing_run_id`, `incoming_run_id` or `source_run_id` in a
    body), `ERR_CHANGEOVER_EVENT_NOT_FOUND` (`changeoverId`),
    `ERR_THERMAL_TEST_NOT_FOUND` (`testId`), `ERR_INVENTORY_LOT_NOT_FOUND` (`lotId`,
    `inventory_lot_id`), `ERR_ALLOCATION_CYCLE_NOT_FOUND` (`cycleId`,
    `allocation_cycle_id`), `ERR_CHANNEL_ORDER_NOT_FOUND` (`orderId`,
    `channel_order_id`), `ERR_ALLOCATION_LINE_NOT_FOUND` (`lineId`) and
    `ERR_CULLET_BATCH_NOT_FOUND` (`batchId`, and any element of a supplied
    `cullet_batch_ids` array). All twelve carry HTTP 404."

    Design: Corner/errors/every_unresolved_path_id_returns_its_own_not_found_code
    """
    ops = corporate_ops_headers()
    missing = NON_EXISTENT_UUID

    probes = [
        ("programId", client.get_certification_program(missing, ops),
         ApiErrors.CERTIFICATION_PROGRAM_NOT_FOUND),
        ("plantId", client.get_plant(missing, ops), ApiErrors.PLANT_NOT_FOUND),
        ("binderId", client.get_binder_formulation(missing, ops),
         ApiErrors.BINDER_FORMULATION_NOT_FOUND),
        ("productLineId", client.get_product_line(missing, ops),
         ApiErrors.PRODUCT_LINE_NOT_FOUND),
        ("runId", client.get_production_run(missing, ops),
         ApiErrors.PRODUCTION_RUN_NOT_FOUND),
        ("changeoverId", client.get_changeover(missing, ops),
         ApiErrors.CHANGEOVER_EVENT_NOT_FOUND),
        ("testId", client.get_thermal_test(missing, ops), ApiErrors.THERMAL_TEST_NOT_FOUND),
        ("lotId", client.get_inventory_lot(missing, ops), ApiErrors.INVENTORY_LOT_NOT_FOUND),
        ("batchId", client.get_cullet_batch(missing, ops), ApiErrors.CULLET_BATCH_NOT_FOUND),
        ("cycleId", client.get_allocation_cycle(missing, ops),
         ApiErrors.ALLOCATION_CYCLE_NOT_FOUND),
        ("orderId", client.get_channel_order(missing, ops), ApiErrors.CHANNEL_ORDER_NOT_FOUND),
        ("lineId", client.get_allocation_line(missing, ops),
         ApiErrors.ALLOCATION_LINE_NOT_FOUND),
    ]

    seen: List[str] = []
    for identifier, response, expected in probes:
        error = validate_error(response, expected, 404)
        assert error["error_id"] == expected, identifier
        seen.append(error["error_id"])

    assert len(probes) == 12
    # No two path identifiers may collapse onto a shared not-found code.
    assert len(set(seen)) == 12, seen


def test_an_empty_collection_reads_as_a_page_rather_than_a_not_found(
    client: InsulationApiClient,
) -> None:
    """PRD 2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more`
    inside the `meta` object of the envelope." PRD 4: "every other successful request,
    including every state-advancing action and every read, answers with HTTP 200."

    Design: Corner/errors/every_unresolved_path_id_returns_its_own_not_found_code
    """
    data, meta = validate_paginated(client.list_changeovers(corporate_ops_headers()))

    assert data == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0


# --- Melt posture at the restrict level --------------------------------------


def test_staging_more_cullet_is_refused_while_the_plant_sits_at_the_restrict_level(
    client: InsulationApiClient,
) -> None:
    """PRD 3.5: "Staging is blocked entirely while the plant is `FROZEN` with
    `ERR_MELT_POSTURE_FROZEN`, and blocked while the plant is `RESTRICTED` with
    `ERR_MELT_POSTURE_RESTRICTED`."

    Design: Corner/errors/staging_more_cullet_at_the_restrict_level_is_rejected_until_a_reversal_clears_it
    """
    ctx = _plant_at_the_restrict_level(client)
    plant = fx.get_plant(client, ctx["plant_id"])

    # The charge landed the ratio exactly on cullet_restrict_fraction.
    assert_close(plant["cullet_fraction_ytd"], 0.2800, 4, "cullet_fraction_ytd")
    assert_field_equals(plant, "melt_posture", "RESTRICTED")
    assert_field_equals(plant, "posture_reason", "CULLET_FRACTION_AT_RESTRICT_LEVEL")

    refused = client.create_cullet_batch(
        f.cullet_batch_payload(ctx["plant_id"], 200.00, plant["version"]),
        plant_operator_headers(ctx["plant_id"]),
    )
    validate_error(refused, ApiErrors.MELT_POSTURE_RESTRICTED, 409)

    after = fx.get_plant(client, ctx["plant_id"])
    assert_close(after["cullet_received_kg_ytd"], 2800.00, 2, "cullet_received_kg_ytd")
    assert_close(after["cullet_on_hand_kg"], 0.00, 2, "cullet_on_hand_kg")
    assert after["version"] == plant["version"]
    assert len(fx.cullet_batches_for_plant(client, ctx["plant_id"])) == 2


def test_a_recompute_review_is_refused_while_the_ratio_is_still_at_the_restrict_level(
    client: InsulationApiClient,
) -> None:
    """PRD 3.1: "`RESTRICTED` returns to `OPEN` only through an
    `EnvironmentalCompliance` posture review carrying a `decision` of `RECOMPUTE`, which
    is permitted only while the plant is currently `RESTRICTED` and only if
    `cullet_fraction_ytd` has fallen **strictly below** `cullet_restrict_fraction` by
    review time; `override_reason` must be omitted on a `RECOMPUTE`." PRD 2.8: "any
    precondition a state transition declares that no more specific rung already covers
    reports `ERR_INVALID_STATE` with HTTP 409."

    Design: Corner/errors/staging_more_cullet_at_the_restrict_level_is_rejected_until_a_reversal_clears_it
    """
    ctx = _plant_at_the_restrict_level(client)

    refused = client.posture_review(
        ctx["plant_id"],
        f.posture_review_payload("RECOMPUTE"),
        environmental_compliance_headers(),
    )
    validate_error(refused, ApiErrors.INVALID_STATE, 409)

    plant = fx.get_plant(client, ctx["plant_id"])
    assert_field_equals(plant, "melt_posture", "RESTRICTED")
    assert_field_equals(plant, "posture_reason", "CULLET_FRACTION_AT_RESTRICT_LEVEL")
    assert_close(plant["cullet_fraction_ytd"], 0.2800, 4, "cullet_fraction_ytd")


def test_staging_is_accepted_once_a_reversal_and_a_recompute_have_cleared_the_posture(
    client: InsulationApiClient,
) -> None:
    """PRD 3.5: "A reversal does **not** clear a `RESTRICTED` posture on its own;
    lowering the ratio merely makes the environmental recompute review of 3.1 succeed."

    Design: Corner/errors/staging_more_cullet_at_the_restrict_level_is_rejected_until_a_reversal_clears_it
    """
    ctx = _plant_at_the_restrict_level(client)
    second = ctx["batches"][1]

    reversed_batch = get_success_data(
        client.reverse_cullet_batch(
            second["id"], plant_operator_headers(ctx["plant_id"])
        )
    )
    assert_field_equals(reversed_batch, "status", "STAGED")
    assert reversed_batch["charged_run_id"] is None

    # The ratio has fallen, but the posture is still RESTRICTED on its own.
    lowered = fx.get_plant(client, ctx["plant_id"])
    assert_close(lowered["cullet_charged_kg_ytd"], 1500.00, 2, "cullet_charged_kg_ytd")
    assert_close(lowered["cullet_fraction_ytd"], 0.1500, 4, "cullet_fraction_ytd")
    assert_close(lowered["cullet_on_hand_kg"], 1300.00, 2, "cullet_on_hand_kg")
    assert_field_equals(lowered, "melt_posture", "RESTRICTED")

    run = fx.get_run(client, ctx["run_id"])
    assert_close(run["cullet_charged_kg"], 1500.00, 2, "cullet_charged_kg")
    assert_close(run["virgin_batch_kg"], 8500.00, 2, "virgin_batch_kg")
    assert_close(run["total_charge_kg"], 10000.00, 2, "total_charge_kg")

    reviewed = fx.posture_review(client, ctx["plant_id"], "RECOMPUTE")
    assert_field_equals(reviewed, "melt_posture", "OPEN")
    assert reviewed["posture_reason"] is None

    staged = fx.stage_cullet(client, ctx["plant_id"], 1500.00)
    assert_field_equals(staged, "status", "STAGED")

    plant = fx.get_plant(client, ctx["plant_id"])
    assert_close(plant["cullet_received_kg_ytd"], 4300.00, 2, "cullet_received_kg_ytd")
    assert_close(plant["cullet_on_hand_kg"], 2800.00, 2, "cullet_on_hand_kg")


# --- Formaldehyde claims and certification ceilings --------------------------


def test_a_free_claim_declaring_measurable_formaldehyde_is_rejected(
    client: InsulationApiClient,
) -> None:
    """PRD 3.2: "a formulation claiming `formaldehyde_free` true must declare
    `formaldehyde_ppm` of exactly 0, and a formulation claiming `formaldehyde_free` false
    must declare a `formaldehyde_ppm` strictly greater than 0. Either mismatch is
    rejected with `ERR_FORMALDEHYDE_FREE_CLAIM_INVALID`, and the check guards both the
    initial drafting and any later revision of the chemistry."

    Design: Corner/errors/a_free_claim_that_contradicts_its_own_ppm_and_a_lab_result_over_the_program_limit
    """
    fx.reset_clock(client)

    refused = client.create_binder_formulation(
        f.binder_payload(formaldehyde_free=True, formaldehyde_ppm=5, voc_g_per_kg=3.2),
        quality_engineer_headers(),
    )
    validate_error(refused, ApiErrors.FORMALDEHYDE_FREE_CLAIM_INVALID, 422)

    _data, meta = validate_paginated(
        client.list_binder_formulations(corporate_ops_headers())
    )
    assert meta["total_count"] == 0


def test_a_non_free_claim_declaring_zero_formaldehyde_is_rejected(
    client: InsulationApiClient,
) -> None:
    """PRD 3.2: "The formaldehyde-free claim must be backed by the chemistry, and the
    rule is symmetric in both directions: a formulation claiming `formaldehyde_free` true
    must declare `formaldehyde_ppm` of exactly 0, and a formulation claiming
    `formaldehyde_free` false must declare a `formaldehyde_ppm` strictly greater than 0."

    Design: Corner/errors/a_free_claim_that_contradicts_its_own_ppm_and_a_lab_result_over_the_program_limit
    """
    fx.reset_clock(client)

    refused = client.create_binder_formulation(
        f.binder_payload(formaldehyde_free=False, formaldehyde_ppm=0, voc_g_per_kg=3.2),
        quality_engineer_headers(),
    )
    validate_error(refused, ApiErrors.FORMALDEHYDE_FREE_CLAIM_INVALID, 422)

    _data, meta = validate_paginated(
        client.list_binder_formulations(corporate_ops_headers())
    )
    assert meta["total_count"] == 0


def test_a_lab_measurement_above_the_formaldehyde_ceiling_is_rejected(
    client: InsulationApiClient,
) -> None:
    """PRD 3.2: "A measurement above the certification ceilings never reaches
    `EMISSIONS_TESTING` at all: free formaldehyde may not exceed 300 parts per million
    and VOC release may not exceed 6.0 grams per kilogram of binder, and a breach of
    either is rejected with `ERR_FORMALDEHYDE_LIMIT_EXCEEDED`."

    Design: Corner/errors/a_free_claim_that_contradicts_its_own_ppm_and_a_lab_result_over_the_program_limit
    """
    fx.reset_clock(client)
    binder = fx.create_draft_binder(client)
    get_success_data(client.submit_binder(binder["id"], quality_engineer_headers()))

    refused = client.record_binder_emissions_test(
        binder["id"],
        f.binder_emissions_test_payload(420, 4.1, "LAB-9103"),
        certification_officer_headers(),
    )
    validate_error(refused, ApiErrors.FORMALDEHYDE_LIMIT_EXCEEDED, 422)

    row = get_success_data(
        client.get_binder_formulation(binder["id"], corporate_ops_headers())
    )
    assert_field_equals(row, "status", "SUBMITTED")
    assert row["lab_reference"] is None
    assert_field_equals(row, "formaldehyde_ppm", 250)


def test_a_lab_measurement_above_the_voc_ceiling_is_rejected(
    client: InsulationApiClient,
) -> None:
    """PRD 3.2: "free formaldehyde may not exceed 300 parts per million and VOC release
    may not exceed 6.0 grams per kilogram of binder, and a breach of either is rejected
    with `ERR_FORMALDEHYDE_LIMIT_EXCEEDED`."

    Design: Corner/errors/a_free_claim_that_contradicts_its_own_ppm_and_a_lab_result_over_the_program_limit
    """
    fx.reset_clock(client)
    binder = fx.create_draft_binder(client)
    get_success_data(client.submit_binder(binder["id"], quality_engineer_headers()))

    # Formaldehyde is comfortably inside its ceiling; only the VOC figure breaches.
    refused = client.record_binder_emissions_test(
        binder["id"],
        f.binder_emissions_test_payload(250, 7.0, "LAB-9104"),
        certification_officer_headers(),
    )
    validate_error(refused, ApiErrors.FORMALDEHYDE_LIMIT_EXCEEDED, 422)

    row = get_success_data(
        client.get_binder_formulation(binder["id"], corporate_ops_headers())
    )
    assert_field_equals(row, "status", "SUBMITTED")
    assert row["lab_reference"] is None
    assert_close(row["voc_g_per_kg"], 4.1, 2, "voc_g_per_kg")


def test_a_lab_measurement_sitting_exactly_on_both_ceilings_is_accepted(
    client: InsulationApiClient,
) -> None:
    """PRD 3.2: "free formaldehyde may not exceed 300 parts per million and VOC release
    may not exceed 6.0 grams per kilogram of binder, and a breach of either is rejected
    with `ERR_FORMALDEHYDE_LIMIT_EXCEEDED`."

    Design: Corner/errors/a_free_claim_that_contradicts_its_own_ppm_and_a_lab_result_over_the_program_limit
    """
    fx.reset_clock(client)
    binder = fx.create_draft_binder(client)
    get_success_data(client.submit_binder(binder["id"], quality_engineer_headers()))

    tested = get_success_data(
        client.record_binder_emissions_test(
            binder["id"],
            f.binder_emissions_test_payload(300, 6.0, "LAB-9103"),
            certification_officer_headers(),
        )
    )

    assert_field_equals(tested, "status", "EMISSIONS_TESTING")
    assert_field_equals(tested, "formaldehyde_ppm", 300)
    assert_close(tested["voc_g_per_kg"], 6.0, 2, "voc_g_per_kg")
    assert_field_equals(tested, "lab_reference", "LAB-9103")


# --- Specimen arrays and retests ---------------------------------------------


def test_a_specimen_array_shorter_than_the_program_minimum_is_rejected(
    client: InsulationApiClient,
) -> None:
    """PRD 3.6: "The test must be `IN_LAB`; the array must hold at least the program's
    `min_specimen_count` values and every value in it must be positive, or the request is
    refused with `ERR_SPECIMEN_COUNT_INSUFFICIENT`."

    Design: Corner/errors/a_short_specimen_list_and_a_retest_with_nothing_to_retest_are_rejected
    """
    ctx = _test_in_lab(client)

    refused = client.record_result(
        ctx["test_id"], [13.10, 13.20], quality_engineer_headers()
    )
    validate_error(refused, ApiErrors.SPECIMEN_COUNT_INSUFFICIENT, 422)

    row = fx.get_thermal_test(client, ctx["test_id"])
    assert_field_equals(row, "status", "IN_LAB")
    assert_field_equals(row, "specimen_r_values", [])
    assert_field_equals(row, "specimen_count", 0)
    assert row["conformance_verdict"] is None
    assert row["recorded_by_user_id"] is None

    run = fx.get_run(client, ctx["run_id"])
    assert_field_equals(run, "qc_status", "SAMPLED")


def test_a_specimen_array_carrying_a_non_positive_value_is_rejected(
    client: InsulationApiClient,
) -> None:
    """PRD 3.6: "the array must hold at least the program's `min_specimen_count` values
    and every value in it must be positive, or the request is refused with
    `ERR_SPECIMEN_COUNT_INSUFFICIENT`."

    Design: Corner/errors/a_short_specimen_list_and_a_retest_with_nothing_to_retest_are_rejected
    """
    ctx = _test_in_lab(client)

    # Three values satisfies min_specimen_count, so only the zero reading is at fault.
    refused = client.record_result(
        ctx["test_id"], [13.10, 13.20, 0.0], quality_engineer_headers()
    )
    validate_error(refused, ApiErrors.SPECIMEN_COUNT_INSUFFICIENT, 422)

    row = fx.get_thermal_test(client, ctx["test_id"])
    assert_field_equals(row, "status", "IN_LAB")
    assert_field_equals(row, "specimen_r_values", [])
    assert_field_equals(row, "specimen_count", 0)
    assert row["mean_r_value"] is None
    assert row["min_r_value"] is None


def test_a_retest_on_a_conforming_test_is_rejected(
    client: InsulationApiClient,
) -> None:
    """PRD 3.6: "The test must be `COMPLETED` with a `conformance_verdict` of
    `NONCONFORMING` and an `attempt_number` strictly below the program's `retest_limit`;
    a conforming result or an already-maximal `attempt_number` leaves no retest due and
    the request is refused with `ERR_RETEST_LIMIT_REACHED`."

    Design: Corner/errors/a_short_specimen_list_and_a_retest_with_nothing_to_retest_are_rejected
    """
    ctx = _test_in_lab(client)

    completed = get_success_data(
        client.record_result(
            ctx["test_id"], [13.10, 13.20, 12.90], quality_engineer_headers()
        )
    )
    assert_field_equals(completed, "status", "COMPLETED")
    assert_field_equals(completed, "conformance_verdict", "CONFORMING")
    assert_field_equals(completed, "specimen_count", 3)
    assert_close(completed["min_r_value"], 12.90, 2, "min_r_value")
    assert_close(completed["mean_r_value"], 13.07, 2, "mean_r_value")
    assert_field_equals(completed, "attempt_number", 1)

    # attempt_number 1 is strictly below the program's retest_limit of 2, so only the
    # conforming verdict stands in the way.
    refused = client.request_retest(
        ctx["test_id"],
        f.retest_window_payload("2026-08-04T08:00:00Z", "2026-08-04T12:00:00Z"),
        quality_engineer_headers(),
    )
    validate_error(refused, ApiErrors.RETEST_LIMIT_REACHED, 409)

    row = fx.get_thermal_test(client, ctx["test_id"])
    assert_field_equals(row, "attempt_number", 1)
    assert_field_equals(row, "status", "COMPLETED")
    assert_field_equals(row, "conformance_verdict", "CONFORMING")

    run = fx.get_run(client, ctx["run_id"])
    assert_field_equals(run, "qc_status", "CONFORMING")


# --- Furnace charges and reversals -------------------------------------------


def test_charging_a_rejected_batch_is_refused_and_leaves_the_whole_melt_unstarted(
    client: InsulationApiClient,
) -> None:
    """PRD 3.4: "The run must be `SCHEDULED`; the logical clock must have reached or
    passed `scheduled_start`, because a run may not be started before its scheduled
    window opens, and an early attempt is refused with `ERR_INVALID_STATE`; the plant must
    not be `FROZEN`; and every named batch must be a cullet batch of the run's own plant
    currently in `STAGED` status, or the charge is refused with
    `ERR_CULLET_BATCH_NOT_STAGED`."

    Design: Corner/errors/charging_a_rejected_batch_and_reversing_after_the_cure_starts_are_both_rejected
    """
    ctx = _run_with_a_rejected_batch(client)
    staged, rejected = ctx["batches"]
    assert_field_equals(fx.get_cullet_batch(client, rejected["id"]), "status", "REJECTED")

    refused = client.start_melt(
        ctx["run_id"],
        [staged["id"], rejected["id"]],
        plant_operator_headers(ctx["plant_id"]),
    )
    validate_error(refused, ApiErrors.CULLET_BATCH_NOT_STAGED, 409)

    run = fx.get_run(client, ctx["run_id"])
    assert_field_equals(run, "run_status", "SCHEDULED")

    # The good batch in the same list must not have been consumed.
    assert_field_equals(fx.get_cullet_batch(client, staged["id"]), "status", "STAGED")
    plant = fx.get_plant(client, ctx["plant_id"])
    assert_close(plant["cullet_charged_kg_ytd"], 0.00, 2, "cullet_charged_kg_ytd")
    assert_close(plant["cullet_on_hand_kg"], 1500.00, 2, "cullet_on_hand_kg")


def test_charging_an_unknown_batch_id_reports_the_batch_not_found(
    client: InsulationApiClient,
) -> None:
    """PRD 2.9: "`ERR_CULLET_BATCH_NOT_FOUND` (`batchId`, and any element of a supplied
    `cullet_batch_ids` array). All twelve carry HTTP 404."

    Design: Corner/errors/charging_a_rejected_batch_and_reversing_after_the_cure_starts_are_both_rejected
    """
    ctx = _run_with_a_rejected_batch(client)
    staged = ctx["batches"][0]

    refused = client.start_melt(
        ctx["run_id"],
        [staged["id"], NON_EXISTENT_UUID],
        plant_operator_headers(ctx["plant_id"]),
    )
    validate_error(refused, ApiErrors.CULLET_BATCH_NOT_FOUND, 404)

    run = fx.get_run(client, ctx["run_id"])
    assert_field_equals(run, "run_status", "SCHEDULED")
    assert_field_equals(fx.get_cullet_batch(client, staged["id"]), "status", "STAGED")


def test_reversing_a_batch_after_the_cure_has_started_is_refused(
    client: InsulationApiClient,
) -> None:
    """PRD 3.5: "Reversing a batch backs it out of a furnace that is still running: the
    batch must be `CHARGED` and the run named by its `charged_run_id` must still be in
    `MELTING`, since the reversal window shuts the moment curing starts - a later attempt
    is refused with `ERR_CULLET_REVERSAL_WINDOW_CLOSED`."

    Design: Corner/errors/charging_a_rejected_batch_and_reversing_after_the_cure_starts_are_both_rejected
    """
    ctx = _run_with_a_rejected_batch(client)
    staged = ctx["batches"][0]

    melting = fx.start_melt(
        client, ctx["plant_id"], ctx["run_id"], [staged["id"]]
    )
    assert_field_equals(melting, "run_status", "MELTING")
    assert_close(melting["cullet_charged_kg"], 1500.00, 2, "cullet_charged_kg")
    assert_close(melting["virgin_batch_kg"], 8500.00, 2, "virgin_batch_kg")
    assert_close(melting["cullet_fraction"], 0.1500, 4, "cullet_fraction")

    curing = fx.start_cure(client, ctx["plant_id"], ctx["run_id"])
    assert_field_equals(curing, "run_status", "CURING")

    refused = client.reverse_cullet_batch(
        staged["id"], plant_operator_headers(ctx["plant_id"])
    )
    validate_error(refused, ApiErrors.CULLET_REVERSAL_WINDOW_CLOSED, 409)

    batch = fx.get_cullet_batch(client, staged["id"])
    assert_field_equals(batch, "status", "CHARGED")
    assert_field_equals(batch, "charged_run_id", ctx["run_id"])

    plant = fx.get_plant(client, ctx["plant_id"])
    assert_close(plant["cullet_charged_kg_ytd"], 1500.00, 2, "cullet_charged_kg_ytd")
    assert_close(plant["cullet_on_hand_kg"], 0.00, 2, "cullet_on_hand_kg")
    run = fx.get_run(client, ctx["run_id"])
    assert_close(run["cullet_charged_kg"], 1500.00, 2, "cullet_charged_kg")


# --- Changeover closes --------------------------------------------------------


def test_closing_a_changeover_before_its_purge_window_ends_is_refused(
    client: InsulationApiClient,
) -> None:
    """PRD 3.5: "Closing a changeover requires the event to be `OPEN` and the logical
    clock to have reached or passed `window_end`; an attempt to close early has no legal
    transition and is refused with `ERR_INVALID_STATE`."

    Design: Corner/errors/closing_a_changeover_early_or_with_recovery_above_the_weighed_trim_is_rejected
    """
    ctx = _open_changeover(client)
    changeover = ctx["changeover"]
    assert_field_equals(changeover, "status", "OPEN")
    assert_close(changeover["density_delta_pct"], 0.00, 2, "density_delta_pct")
    assert_close(changeover["purge_minutes"], 20.00, 2, "purge_minutes")
    assert_close(changeover["provisional_scrap_kg"], 690.00, 2, "provisional_scrap_kg")

    # The mass figures below are perfectly consistent; only the clock is early.
    refused = client.close_changeover(
        ctx["changeover_id"],
        f.close_changeover_payload(300.00, 200.00),
        plant_operator_headers(ctx["plant_id"]),
    )
    validate_error(refused, ApiErrors.INVALID_STATE, 409)

    row = get_success_data(
        client.get_changeover(ctx["changeover_id"], corporate_ops_headers())
    )
    assert_field_equals(row, "status", "OPEN")

    outgoing = fx.get_run(client, ctx["outgoing_id"])
    assert_close(outgoing["changeover_scrap_kg"], 690.00, 2, "changeover_scrap_kg")
    assert fx.cullet_batches_for_plant(client, ctx["plant_id"]) == []


def test_recovering_more_cullet_than_the_weighed_trim_is_refused(
    client: InsulationApiClient,
) -> None:
    """PRD 3.5: "Both must be non-negative and `recovered_cullet_kg` must not exceed
    `weighed_trim_kg`, or the close is refused with `ERR_TRIM_MASS_INCONSISTENT`."

    Design: Corner/errors/closing_a_changeover_early_or_with_recovery_above_the_weighed_trim_is_rejected
    """
    ctx = _open_changeover(client)
    fx.set_clock(client, "2026-08-03T15:00:00Z")

    refused = client.close_changeover(
        ctx["changeover_id"],
        f.close_changeover_payload(300.00, 500.00),
        plant_operator_headers(ctx["plant_id"]),
    )
    validate_error(refused, ApiErrors.TRIM_MASS_INCONSISTENT, 422)

    row = get_success_data(
        client.get_changeover(ctx["changeover_id"], corporate_ops_headers())
    )
    assert_field_equals(row, "status", "OPEN")

    outgoing = fx.get_run(client, ctx["outgoing_id"])
    assert_close(outgoing["changeover_scrap_kg"], 690.00, 2, "changeover_scrap_kg")
    assert fx.cullet_batches_for_plant(client, ctx["plant_id"]) == []


def test_closing_an_already_closed_changeover_is_refused(
    client: InsulationApiClient,
) -> None:
    """PRD 2.8: "It equally covers every repeat of an already-applied trigger and every
    trigger aimed at a row already in a terminal state."

    Design: Corner/errors/closing_a_changeover_early_or_with_recovery_above_the_weighed_trim_is_rejected
    """
    ctx = _open_changeover(client)
    fx.set_clock(client, "2026-08-03T15:00:00Z")

    closed = get_success_data(
        client.close_changeover(
            ctx["changeover_id"],
            f.close_changeover_payload(300.00, 200.00),
            plant_operator_headers(ctx["plant_id"]),
        )
    )
    assert_field_equals(closed, "status", "CLOSED")
    assert_close(closed["reconciled_scrap_kg"], 100.00, 2, "reconciled_scrap_kg")
    assert_close(closed["scrap_variance_kg"], -390.00, 2, "scrap_variance_kg")
    assert_close(
        fx.get_run(client, ctx["outgoing_id"])["changeover_scrap_kg"],
        100.00,
        2,
        "changeover_scrap_kg",
    )
    minted = fx.cullet_batches_for_plant(client, ctx["plant_id"])
    assert len(minted) == 1
    assert_field_equals(minted[0], "source_type", "CHANGEOVER_SCRAP")
    assert_field_equals(minted[0], "status", "STAGED")
    assert_close(minted[0]["mass_kg"], 200.00, 2, "mass_kg")

    repeated = client.close_changeover(
        ctx["changeover_id"],
        f.close_changeover_payload(300.00, 200.00),
        plant_operator_headers(ctx["plant_id"]),
    )
    validate_error(repeated, ApiErrors.INVALID_STATE, 409)

    # The second close must not mint a second cullet batch.
    assert len(fx.cullet_batches_for_plant(client, ctx["plant_id"])) == 1
    assert_close(
        fx.get_run(client, ctx["outgoing_id"])["changeover_scrap_kg"],
        100.00,
        2,
        "changeover_scrap_kg",
    )


# --- Emissions reporting periods ---------------------------------------------


def test_a_report_filed_against_a_period_that_has_not_closed_is_rejected(
    client: InsulationApiClient,
) -> None:
    """PRD 3.9: "The period must also already be over: `period_end` must fall at or
    before the current logical clock reading, and a report filed against a period that has
    not yet closed is refused with `ERR_EMISSIONS_PERIOD_INVALID`."

    Design: Corner/errors/an_emissions_period_that_has_not_closed_yet_is_rejected
    """
    fx.reset_clock(client)
    plant = fx.create_plant(client)
    fx.set_clock(client, "2026-08-03T06:00:00Z")

    # A well-ordered interval whose end simply lies in the plant's future.
    refused = client.file_emissions_report(
        plant["id"],
        f.emissions_report_payload("2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z"),
        environmental_compliance_headers(),
    )
    validate_error(refused, ApiErrors.EMISSIONS_PERIOD_INVALID, 422)

    row = fx.get_plant(client, plant["id"])
    assert_field_equals(row, "emissions_status", "COMPLIANT")
    assert_field_equals(row, "melt_posture", "OPEN")


def test_a_degenerate_reporting_interval_is_a_request_shape_failure(
    client: InsulationApiClient,
) -> None:
    """PRD 3.9: "The payload carries `period_start` and `period_end`, with `period_end`
    strictly later than `period_start` - an inverted interval is a plain interval check
    reported as `ERR_INVALID_REQUEST` by the request-shape rung of the ladder."

    PRD 3.9: "That rule owns only the future-period case, since the ordering leg has
    already been reported at a lower priority."

    Design: Corner/errors/an_emissions_period_that_has_not_closed_yet_is_rejected
    """
    fx.reset_clock(client)
    plant = fx.create_plant(client)
    fx.set_clock(client, "2026-08-03T06:00:00Z")

    # Both endpoints are already in the past, so the future-period rule cannot fire.
    refused = client.file_emissions_report(
        plant["id"],
        f.emissions_report_payload("2026-08-01T00:00:00Z", "2026-08-01T00:00:00Z"),
        environmental_compliance_headers(),
    )
    validate_error(refused, ApiErrors.INVALID_REQUEST, 400)

    assert_field_equals(
        fx.get_plant(client, plant["id"]), "emissions_status", "COMPLIANT"
    )


def test_a_period_ending_exactly_on_the_clock_reading_is_accepted(
    client: InsulationApiClient,
) -> None:
    """PRD 3.9: "`period_end` must fall at or before the current logical clock reading,
    and a report filed against a period that has not yet closed is refused with
    `ERR_EMISSIONS_PERIOD_INVALID`."

    Design: Corner/errors/an_emissions_period_that_has_not_closed_yet_is_rejected
    """
    fx.reset_clock(client)
    plant = fx.create_plant(client)
    fx.set_clock(client, "2026-08-03T06:00:00Z")

    reported = get_success_data(
        client.file_emissions_report(
            plant["id"],
            f.emissions_report_payload("2026-08-01T00:00:00Z", "2026-08-03T06:00:00Z"),
            environmental_compliance_headers(),
        )
    )

    assert_field_equals(reported, "emissions_status", "REPORTED")
    assert_close(reported["reported_formaldehyde_kg"], 0.0000, 4, "reported_formaldehyde_kg")
    assert_close(reported["reported_voc_kg"], 0.0000, 4, "reported_voc_kg")
    # No run booked any mass, so neither allowance leg trips and nothing freezes.
    assert_field_equals(reported, "melt_posture", "OPEN")
    assert reported["posture_reason"] is None


# --- The cure-index gate ------------------------------------------------------


def test_a_line_running_too_fast_to_cure_is_refused_at_start_cure(
    client: InsulationApiClient,
) -> None:
    """PRD 3.4: "The gate is a floor of 100.00: a `cure_index` **below** 100.00 is
    refused with `ERR_CURE_INDEX_BELOW_MINIMUM`, and a value of exactly 100.00 passes."

    Design: Corner/errors/a_cure_index_below_the_minimum_is_rejected_at_start_cure
    """
    ctx = _melting_run_on_a_free_binder(client)

    # 120 ft of oven at 60 fpm is 120.00 s of dwell against a 150.0 s minimum, and
    # 430 F is 10 degrees over the binder's 420.0 F minimum: cure_index 46.67.
    refused = client.start_cure(
        ctx["run_id"],
        f.start_cure_payload(
            avg_zone_temp_f=430.0, line_speed_fpm=60.0, binder_applied_kg=900.0
        ),
        plant_operator_headers(ctx["plant_id"]),
    )
    validate_error(refused, ApiErrors.CURE_INDEX_BELOW_MINIMUM, 422)

    run = fx.get_run(client, ctx["run_id"])
    assert_field_equals(run, "run_status", "MELTING")


def test_an_oven_below_the_binder_minimum_is_refused_at_start_cure(
    client: InsulationApiClient,
) -> None:
    """PRD 3.4: "subtract the formulation's `min_cure_temp_f` from `avg_zone_temp_f`,
    divide by 60.0, and clamp the result into the closed range from 0 to 1 - an oven
    running below the binder's minimum contributes a margin of exactly 0, and one running
    60 degrees or more above it contributes exactly 1."

    Design: Corner/errors/a_cure_index_below_the_minimum_is_rejected_at_start_cure
    """
    ctx = _melting_run_on_a_free_binder(client)

    # 40 fpm gives 180.00 s of dwell, a ratio of 1.2, but 410 F is under the binder's
    # 420.0 F minimum so the margin clamps to 0 and cure_index is only 60.00.
    refused = client.start_cure(
        ctx["run_id"],
        f.start_cure_payload(
            avg_zone_temp_f=410.0, line_speed_fpm=40.0, binder_applied_kg=900.0
        ),
        plant_operator_headers(ctx["plant_id"]),
    )
    validate_error(refused, ApiErrors.CURE_INDEX_BELOW_MINIMUM, 422)

    run = fx.get_run(client, ctx["run_id"])
    assert_field_equals(run, "run_status", "MELTING")


def test_a_recipe_landing_exactly_on_the_cure_floor_is_accepted_after_a_refusal(
    client: InsulationApiClient,
) -> None:
    """PRD 3.4: "a `cure_index` **below** 100.00 is refused with
    `ERR_CURE_INDEX_BELOW_MINIMUM`, and a value of exactly 100.00 passes."

    Design: Corner/errors/a_cure_index_below_the_minimum_is_rejected_at_start_cure
    """
    ctx = _melting_run_on_a_free_binder(client)

    refused = client.start_cure(
        ctx["run_id"],
        f.start_cure_payload(
            avg_zone_temp_f=430.0, line_speed_fpm=60.0, binder_applied_kg=900.0
        ),
        plant_operator_headers(ctx["plant_id"]),
    )
    validate_error(refused, ApiErrors.CURE_INDEX_BELOW_MINIMUM, 422)

    # 48 fpm is exactly the binder's 150.0 s minimum dwell and 480 F saturates the
    # 60-degree margin: 1.0 * (1 + 1) / 2 * 100 = 100.00, exactly on the floor.
    cured = get_success_data(
        client.start_cure(
            ctx["run_id"],
            f.start_cure_payload(
                avg_zone_temp_f=480.0, line_speed_fpm=48.0, binder_applied_kg=900.0
            ),
            plant_operator_headers(ctx["plant_id"]),
        )
    )

    assert_field_equals(cured, "run_status", "CURING")
    assert_close(cured["dwell_s"], 150.00, 2, "dwell_s")
    assert_close(cured["cure_index"], 100.00, 2, "cure_index")
    assert_close(cured["formaldehyde_kg"], 0.0000, 4, "formaldehyde_kg")
    assert_close(cured["voc_kg"], 2.8800, 4, "voc_kg")


# --- Selling and allocating an uncertified SKU -------------------------------


def test_an_order_on_an_uncertified_sku_is_refused(
    client: InsulationApiClient,
) -> None:
    """PRD 3.8: "The SKU's `certification_status` must be `CERTIFIED` or `DERATED` - an
    uncertified, suspended or withdrawn SKU cannot be sold, and the attempt is refused
    with `ERR_PRODUCT_LINE_NOT_CERTIFIED`; a derated SKU is fully sellable, merely at a
    lower published R-value."

    Design: Corner/errors/an_uncertified_sku_cannot_take_orders_or_be_proposed_for_allocation
    """
    ctx = fx.base_setup(client)
    assert_field_equals(
        fx.get_product_line(client, ctx["sku_id"]), "certification_status", "DRAFT"
    )

    refused = client.create_channel_order(
        f.channel_order_payload(ctx["sku_id"], 8800.00), channel_buyer_headers()
    )
    validate_error(refused, ApiErrors.PRODUCT_LINE_NOT_CERTIFIED, 409)

    _data, meta = validate_paginated(client.list_channel_orders(corporate_ops_headers()))
    assert meta["total_count"] == 0


def test_proposing_a_cycle_on_an_uncertified_sku_is_refused_before_supply_is_weighed(
    client: InsulationApiClient,
) -> None:
    """PRD 3.8: "Proposing runs the waterfall and moves the cycle `OPEN -> PROPOSED`. The
    SKU must be `CERTIFIED` or `DERATED`, or the proposal is refused with
    `ERR_PRODUCT_LINE_NOT_CERTIFIED`." PRD 2.8 orders the ladder so that rung 12 carries
    "`ERR_PRODUCT_LINE_NOT_CERTIFIED`" ahead of rung "13. Allocation feasibility, in this
    order: `ERR_NO_ALLOCATABLE_SUPPLY`, `ERR_NO_ELIGIBLE_ORDERS`, then
    `ERR_ALLOCATION_EXCEEDS_LOT_AVAILABLE`."

    Design: Corner/errors/an_uncertified_sku_cannot_take_orders_or_be_proposed_for_allocation
    """
    ctx = fx.base_setup(client)

    # Opening a cycle carries no certification precondition of its own.
    cycle = fx.open_cycle(client, ctx["plant_id"], ctx["sku_id"])
    assert_field_equals(cycle, "status", "OPEN")

    refused = client.propose_cycle(cycle["id"], channel_manager_headers())
    # The certification rung precedes the allocation-feasibility rung, so this is not
    # reported as a supply or demand shortage.
    validate_error(refused, ApiErrors.PRODUCT_LINE_NOT_CERTIFIED, 409)

    row = fx.get_cycle(client, cycle["id"])
    assert_field_equals(row, "status", "OPEN")
    assert fx.lines_for_cycle(client, cycle["id"]) == []


# --- Repacking a lot that is still spoken for --------------------------------


def test_repacking_a_lot_that_still_carries_an_allocation_line_is_refused(
    client: InsulationApiClient,
) -> None:
    """PRD 3.7: "The lot must be `AVAILABLE` with `allocated_sqft` exactly 0.00 and no
    allocation line on it in `PROPOSED` or `ALLOCATED`, or the request is refused with
    `ERR_LOT_HAS_ALLOCATIONS` - the reservation-versus-booking distinction matters here,
    because a merely proposed line still blocks a repack even though it contributes
    nothing to `allocated_sqft`."

    Design: Corner/errors/repacking_a_lot_that_still_carries_an_allocation_line_is_rejected
    """
    ctx = fx.certified_sku_with_lot(client, bags_produced=120)
    order = fx.place_order(client, ctx["sku_id"], 8800.00)
    cycle = fx.open_cycle(client, ctx["plant_id"], ctx["sku_id"])
    line = fx.manual_line(client, cycle["id"], order["id"], ctx["lot_id"], 8800.00)
    assert_field_equals(line, "status", "ALLOCATED")

    lot = fx.get_lot(client, ctx["lot_id"])
    assert_close(lot["produced_sqft"], 10560.00, 2, "produced_sqft")
    assert_close(lot["allocated_sqft"], 8800.00, 2, "allocated_sqft")
    # Coverage remains, so the lot itself is still AVAILABLE - only the booked
    # square footage stands in the way of a split.
    assert_close(lot["available_sqft"], 1760.00, 2, "available_sqft")
    assert_field_equals(lot, "status", "AVAILABLE")

    refused = client.repack_lot(
        ctx["lot_id"], [60, 60], plant_operator_headers(ctx["plant_id"])
    )
    validate_error(refused, ApiErrors.LOT_HAS_ALLOCATIONS, 409)

    parent = fx.get_lot(client, ctx["lot_id"])
    assert_field_equals(parent, "status", "AVAILABLE")
    assert_field_equals(parent, "bags", 120)
    assert fx.child_lots(client, ctx["lot_id"]) == []


def test_the_identical_repack_is_accepted_once_the_line_is_revoked(
    client: InsulationApiClient,
) -> None:
    """PRD 3.7: "On success the parent moves `AVAILABLE -> REPACKED`, a terminal state,
    with `available_sqft` forced to 0.00, and one child lot is created per element with
    `parent_lot_id` pointing at the parent, status `AVAILABLE`, `bags` equal to that
    element and `produced_sqft` equal to the element multiplied by the SKU's `bag_sqft`."

    Design: Corner/errors/repacking_a_lot_that_still_carries_an_allocation_line_is_rejected
    """
    ctx = fx.certified_sku_with_lot(client, bags_produced=120)
    order = fx.place_order(client, ctx["sku_id"], 8800.00)
    cycle = fx.open_cycle(client, ctx["plant_id"], ctx["sku_id"])
    line = fx.manual_line(client, cycle["id"], order["id"], ctx["lot_id"], 8800.00)

    revoked = get_success_data(
        client.revoke_allocation_line(line["id"], channel_manager_headers())
    )
    assert_field_equals(revoked, "status", "REVOKED")

    freed = fx.get_lot(client, ctx["lot_id"])
    assert_close(freed["allocated_sqft"], 0.00, 2, "allocated_sqft")
    assert_close(freed["available_sqft"], 10560.00, 2, "available_sqft")
    assert_field_equals(freed, "status", "AVAILABLE")
    assert_field_equals(fx.get_order(client, order["id"]), "status", "BACKORDERED")

    split = get_success_data(
        client.repack_lot(ctx["lot_id"], [60, 60], plant_operator_headers(ctx["plant_id"]))
    )
    assert_field_equals(split, "status", "REPACKED")
    assert_close(split["available_sqft"], 0.00, 2, "available_sqft")

    children = fx.child_lots(client, ctx["lot_id"])
    assert len(children) == 2
    for child in children:
        assert_field_equals(child, "status", "AVAILABLE")
        assert_field_equals(child, "bags", 60)
        assert_field_equals(child, "parent_lot_id", ctx["lot_id"])
        assert_close(child["produced_sqft"], 5280.00, 2, "produced_sqft")


# --- The binder revision ceiling ---------------------------------------------


def test_a_third_revision_past_the_ceiling_is_refused(
    client: InsulationApiClient,
) -> None:
    """PRD 3.2: "The loop is capped: `revision_count` must be strictly below two before a
    further revision is accepted, so a formulation may cycle back to `DRAFT` at most
    twice. A third attempt is rejected with `ERR_BINDER_REVISION_LIMIT_REACHED`."

    Design: Corner/errors/revising_past_the_max_binder_revisions_ceiling_is_rejected
    """
    ctx = _binder_at_the_revision_ceiling(client)
    parked = get_success_data(
        client.get_binder_formulation(ctx["binder_id"], corporate_ops_headers())
    )
    assert_field_equals(parked, "status", "REVISION_REQUIRED")
    assert_field_equals(parked, "revision_count", 2)

    refused = client.revise_binder(
        ctx["binder_id"],
        f.binder_revise_payload(
            "REVISE",
            formaldehyde_free=False,
            formaldehyde_ppm=100,
            voc_g_per_kg=3.0,
            min_cure_temp_f=420.0,
            min_dwell_s=150.0,
            loi_target_pct=4.5,
        ),
        quality_engineer_headers(),
    )
    validate_error(refused, ApiErrors.BINDER_REVISION_LIMIT_REACHED, 409)

    row = get_success_data(
        client.get_binder_formulation(ctx["binder_id"], corporate_ops_headers())
    )
    assert_field_equals(row, "status", "REVISION_REQUIRED")
    assert_field_equals(row, "revision_count", 2)
    # The refused chemistry must not have been written.
    assert_field_equals(row, "formaldehyde_ppm", 150)
    assert_close(row["voc_g_per_kg"], 3.5, 2, "voc_g_per_kg")


def test_withdrawal_is_still_available_at_the_revision_ceiling(
    client: InsulationApiClient,
) -> None:
    """PRD 3.2: "On `WITHDRAW`, the six chemistry fields must be omitted, and a
    `REVISION_REQUIRED` formulation moves straight to the terminal `WITHDRAWN`, firing the
    same two-hop product-line suspension cascade described above."

    Design: Corner/errors/revising_past_the_max_binder_revisions_ceiling_is_rejected
    """
    ctx = _binder_at_the_revision_ceiling(client)

    withdrawn = get_success_data(
        client.revise_binder(
            ctx["binder_id"],
            f.binder_revise_payload("WITHDRAW"),
            quality_engineer_headers(),
        )
    )

    assert_field_equals(withdrawn, "status", "WITHDRAWN")
    assert_field_equals(withdrawn, "revision_count", 2)


def test_revising_a_withdrawn_formulation_reports_invalid_state(
    client: InsulationApiClient,
) -> None:
    """PRD 2.8: "It equally covers every repeat of an already-applied trigger and every
    trigger aimed at a row already in a terminal state." PRD 2.8: "Because the state check
    at rung 8 precedes every domain constraint at rung 12, a request that both targets a
    wrongly-stated row and carries a bad quantity reports `ERR_INVALID_STATE`."

    Design: Corner/errors/revising_past_the_max_binder_revisions_ceiling_is_rejected
    """
    ctx = _binder_at_the_revision_ceiling(client)
    get_success_data(
        client.revise_binder(
            ctx["binder_id"],
            f.binder_revise_payload("WITHDRAW"),
            quality_engineer_headers(),
        )
    )

    refused = client.revise_binder(
        ctx["binder_id"],
        f.binder_revise_payload(
            "REVISE",
            formaldehyde_free=False,
            formaldehyde_ppm=100,
            voc_g_per_kg=3.0,
            min_cure_temp_f=420.0,
            min_dwell_s=150.0,
            loi_target_pct=4.5,
        ),
        quality_engineer_headers(),
    )
    validate_error(refused, ApiErrors.INVALID_STATE, 409)

    row = get_success_data(
        client.get_binder_formulation(ctx["binder_id"], corporate_ops_headers())
    )
    assert_field_equals(row, "status", "WITHDRAWN")
    assert_field_equals(row, "revision_count", 2)
