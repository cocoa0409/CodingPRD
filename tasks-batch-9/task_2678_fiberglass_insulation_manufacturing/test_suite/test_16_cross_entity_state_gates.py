"""Cross-entity state gates: a forward transition blocked by a referenced row's status,
and a recovery transition blocked by a parallel state dimension on a sibling row.

Queue A / cross_entity_state_dependency.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import InsulationApiClient
from test_helpers.api_errors import ApiErrors
from test_helpers.assertions import assert_close, assert_field_equals
from test_helpers.constants import SKU_PL_A, ZONES_470
from test_helpers.test_users import (
    QUALITY_ENGINEER_USER_ID_ALT,
    certification_officer_headers,
    quality_engineer_headers,
)

FREE_BINDER = {
    "code": "BF-FREE-1",
    "formaldehyde_free": True,
    "formaldehyde_ppm": 0,
    "voc_g_per_kg": 3.2,
    "min_cure_temp_f": 420.0,
    "min_dwell_s": 150.0,
    "loi_target_pct": 4.5,
}

CONDEMNING_SPECIMENS = [12.40, 12.50, 12.60]
CLEARING_SPECIMENS = [12.70, 13.10, 12.90]


def _sku_on_a_submitted_binder(client: InsulationApiClient) -> Dict[str, Any]:
    """PL-A references a formulation that has left DRAFT but is not yet CERTIFIED."""
    fx.reset_clock(client)
    program = fx.create_per_specimen_program(client)
    plant = fx.create_plant(client)
    binder = fx.create_draft_binder(client, **FREE_BINDER)
    get_success_data(client.submit_binder(binder["id"], quality_engineer_headers()))
    sku = fx.create_product_line(
        client, plant["id"], binder["id"], program["id"], **SKU_PL_A
    )
    return {
        "plant_id": plant["id"],
        "program_id": program["id"],
        "binder_id": binder["id"],
        "sku_id": sku["id"],
        "sku_version": int(sku["version"]),
    }


def test_a_submitted_binder_does_not_open_the_certification_queue(
    client: InsulationApiClient,
) -> None:
    """PRD 3.6: "the SKU must be `DRAFT` and its `BinderFormulation` must be `CERTIFIED`,
    and on success `certification_status` moves `DRAFT -> PENDING_CERTIFICATION`."

    Design: Difficulty/cross_entity_state_dependency/sku_certification_submission_gated_on_binder_reaching_certified
    """
    ctx = _sku_on_a_submitted_binder(client)
    binder = get_success_data(
        client.get_binder_formulation(ctx["binder_id"], quality_engineer_headers())
    )
    assert_field_equals(binder, "status", "SUBMITTED")

    resp = client.submit_sku_certification(ctx["sku_id"], quality_engineer_headers())

    validate_error(resp, ApiErrors.BINDER_NOT_CERTIFIED)

    sku = fx.get_product_line(client, ctx["sku_id"])
    assert_field_equals(sku, "certification_status", "DRAFT")
    assert sku["effective_declared_r_value"] is None
    assert_field_equals(sku, "version", ctx["sku_version"])


def test_a_binder_in_emissions_testing_still_does_not_open_the_queue(
    client: InsulationApiClient,
) -> None:
    """PRD 3.4: "The SKU's binder formulation must be `CERTIFIED`, or the request is
    refused with `ERR_BINDER_NOT_CERTIFIED`."

    Design: Difficulty/cross_entity_state_dependency/sku_certification_submission_gated_on_binder_reaching_certified
    """
    ctx = _sku_on_a_submitted_binder(client)
    tested = get_success_data(
        client.record_binder_emissions_test(
            ctx["binder_id"],
            f.binder_emissions_test_payload(0, 3.2, "LAB-9001"),
            certification_officer_headers(),
        )
    )
    assert_field_equals(tested, "status", "EMISSIONS_TESTING")

    resp = client.submit_sku_certification(ctx["sku_id"], quality_engineer_headers())

    validate_error(resp, ApiErrors.BINDER_NOT_CERTIFIED)

    sku = fx.get_product_line(client, ctx["sku_id"])
    assert_field_equals(sku, "certification_status", "DRAFT")
    assert_field_equals(sku, "version", ctx["sku_version"])


def test_only_a_certified_binder_opens_the_queue(client: InsulationApiClient) -> None:
    """PRD 2.4: "`version`, an integer that starts at 1 on creation and increments by one
    on every mutation of that row."

    Design: Difficulty/cross_entity_state_dependency/sku_certification_submission_gated_on_binder_reaching_certified
    """
    ctx = _sku_on_a_submitted_binder(client)
    validate_error(
        client.submit_sku_certification(ctx["sku_id"], quality_engineer_headers()),
        ApiErrors.BINDER_NOT_CERTIFIED,
    )
    get_success_data(
        client.record_binder_emissions_test(
            ctx["binder_id"],
            f.binder_emissions_test_payload(0, 3.2, "LAB-9001"),
            certification_officer_headers(),
        )
    )
    validate_error(
        client.submit_sku_certification(ctx["sku_id"], quality_engineer_headers()),
        ApiErrors.BINDER_NOT_CERTIFIED,
    )
    certified = get_success_data(
        client.binder_certification_decision(
            ctx["binder_id"],
            f.binder_decision_payload("CERTIFY", emissions_cert_id="EC-4411"),
            certification_officer_headers(),
        )
    )
    assert_field_equals(certified, "status", "CERTIFIED")

    queued = get_success_data(
        client.submit_sku_certification(ctx["sku_id"], quality_engineer_headers())
    )

    assert_field_equals(queued, "certification_status", "PENDING_CERTIFICATION")
    # Neither rejection touched the row: exactly one mutation across the sequence.
    assert_field_equals(queued, "version", ctx["sku_version"] + 1)


def _quarantined_lot(client: InsulationApiClient) -> Dict[str, Any]:
    """A packaged run condemned by a nonconforming test, so its lot sits QUARANTINED."""
    ctx = fx.base_setup(
        client, binder_overrides=dict(FREE_BINDER), sku_overrides=dict(SKU_PL_A)
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
    fx.start_melt(client, ctx["plant_id"], run["id"])
    fx.start_cure(
        client,
        ctx["plant_id"],
        run["id"],
        avg_zone_temp_f=470.0,
        line_speed_fpm=40.0,
        binder_applied_kg=900.0,
    )
    run = fx.package_run(client, ctx["plant_id"], run["id"], bags_produced=120)
    lot = fx.lot_for_run(client, run["id"])
    test = fx.request_thermal_test(
        client,
        run["id"],
        ctx["sku_id"],
        ctx["program_id"],
        window_start="2026-08-05T08:00:00Z",
        window_end="2026-08-05T12:00:00Z",
        user_id=QUALITY_ENGINEER_USER_ID_ALT,
    )
    fx.record_thermal_result(
        client, test["id"], CONDEMNING_SPECIMENS, user_id=QUALITY_ENGINEER_USER_ID_ALT
    )
    ctx.update(
        {
            "run_id": run["id"],
            "lot_id": lot["id"],
            "test_id": test["id"],
        }
    )
    return ctx


def _request_retest(client: InsulationApiClient, test_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.request_retest(
            test_id,
            f.retest_window_payload("2026-08-05T13:00:00Z", "2026-08-05T17:00:00Z"),
            quality_engineer_headers(QUALITY_ENGINEER_USER_ID_ALT),
        )
    )


def test_a_nonconforming_run_blocks_the_release_of_its_lot(
    client: InsulationApiClient,
) -> None:
    """PRD 3.7: "The gate is a cross-entity one: the originating run's `qc_status` must
    read exactly `CONFORMING`, or the release is refused with `ERR_RUN_NOT_CONFORMING`."

    Design: Difficulty/cross_entity_state_dependency/quarantined_lot_release_gated_on_run_qc_status_conforming
    """
    ctx = _quarantined_lot(client)
    run = fx.get_run(client, ctx["run_id"])
    assert_field_equals(run, "qc_status", "NONCONFORMING")

    resp = client.release_lot(
        ctx["lot_id"], quality_engineer_headers(QUALITY_ENGINEER_USER_ID_ALT)
    )

    validate_error(resp, ApiErrors.RUN_NOT_CONFORMING)

    lot = fx.get_lot(client, ctx["lot_id"])
    assert_field_equals(lot, "status", "QUARANTINED")
    assert_field_equals(lot, "quarantine_reason", "RUN_NONCONFORMING")
    assert_close(lot["available_sqft"], 0.00, 2, "available_sqft")
    assert_close(lot["produced_sqft"], 10560.00, 2, "produced_sqft")


def test_a_run_awaiting_a_retest_also_blocks_the_release(
    client: InsulationApiClient,
) -> None:
    """PRD 3.7: "A run still `RETEST_PENDING`, still `NONCONFORMING` or never sampled
    cannot have its lots released, which is precisely why a conforming retest result frees
    the operator to release lots one at a time rather than releasing them itself."

    Design: Difficulty/cross_entity_state_dependency/quarantined_lot_release_gated_on_run_qc_status_conforming
    """
    ctx = _quarantined_lot(client)
    retest = _request_retest(client, ctx["test_id"])
    assert_field_equals(retest, "attempt_number", 2)
    assert_field_equals(retest, "status", "IN_LAB")
    assert retest["conformance_verdict"] is None
    run = fx.get_run(client, ctx["run_id"])
    assert_field_equals(run, "qc_status", "RETEST_PENDING")

    resp = client.release_lot(
        ctx["lot_id"], quality_engineer_headers(QUALITY_ENGINEER_USER_ID_ALT)
    )

    validate_error(resp, ApiErrors.RUN_NOT_CONFORMING)

    lot = fx.get_lot(client, ctx["lot_id"])
    assert_field_equals(lot, "status", "QUARANTINED")
    assert_close(lot["available_sqft"], 0.00, 2, "available_sqft")


def test_a_conforming_run_lets_the_explicit_release_through(
    client: InsulationApiClient,
) -> None:
    """PRD 3.7: "Releasing a quarantined lot returns it `QUARANTINED -> AVAILABLE`, clears
    `quarantine_reason` to null and recomputes `available_sqft` from the ledger."

    Design: Difficulty/cross_entity_state_dependency/quarantined_lot_release_gated_on_run_qc_status_conforming
    """
    ctx = _quarantined_lot(client)
    _request_retest(client, ctx["test_id"])
    cleared = get_success_data(
        client.record_result(
            ctx["test_id"],
            CLEARING_SPECIMENS,
            quality_engineer_headers(QUALITY_ENGINEER_USER_ID_ALT),
        )
    )
    assert_close(cleared["min_r_value"], 12.70, 2, "min_r_value")
    assert_close(cleared["mean_r_value"], 12.90, 2, "mean_r_value")
    assert_field_equals(cleared, "conformance_verdict", "CONFORMING")

    run = fx.get_run(client, ctx["run_id"])
    assert_field_equals(run, "qc_status", "CONFORMING")
    # The clearing verdict alone leaves the lot where the cascade put it.
    still_held = fx.get_lot(client, ctx["lot_id"])
    assert_field_equals(still_held, "status", "QUARANTINED")
    assert_close(still_held["available_sqft"], 0.00, 2, "available_sqft")

    released = get_success_data(
        client.release_lot(
            ctx["lot_id"], quality_engineer_headers(QUALITY_ENGINEER_USER_ID_ALT)
        )
    )

    assert_field_equals(released, "status", "AVAILABLE")
    assert released["quarantine_reason"] is None
    assert_close(released["allocated_sqft"], 0.00, 2, "allocated_sqft")
    assert_close(released["available_sqft"], 10560.00, 2, "available_sqft")
    # Four moves on the quality dimension, none on the physical one.
    assert_field_equals(fx.get_run(client, ctx["run_id"]), "run_status", "PACKAGED")
