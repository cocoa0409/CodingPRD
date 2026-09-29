"""Composite setup helpers.

The runner restarts the server before every test, so every helper here builds
its state from scratch using only PRD-declared endpoints. Nothing is inserted
directly into storage.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .api_client import InsulationApiClient
from .constants import CLOCK_EPOCH
from .test_users import (
    certification_officer_headers,
    channel_buyer_headers,
    channel_manager_headers,
    corporate_ops_headers,
    environmental_compliance_headers,
    plant_operator_headers,
    quality_engineer_headers,
)

# --- Clock -------------------------------------------------------------------


def set_clock(client: InsulationApiClient, current_utc: str) -> Dict[str, Any]:
    """PRD 2.4: the logical clock is driven explicitly by CorporateOps."""
    return get_success_data(client.set_clock(current_utc, corporate_ops_headers()))


def reset_clock(client: InsulationApiClient) -> Dict[str, Any]:
    return set_clock(client, CLOCK_EPOCH)


# --- Reference data ----------------------------------------------------------


def create_program(client: InsulationApiClient, **overrides: Any) -> Dict[str, Any]:
    payload = f.certification_program_payload(**overrides)
    return get_success_data(
        client.create_certification_program(payload, corporate_ops_headers()), 201
    )


def create_per_specimen_program(
    client: InsulationApiClient, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.create_certification_program(
            f.per_specimen_program_payload(**overrides), corporate_ops_headers()
        ),
        201,
    )


def create_lot_mean_program(
    client: InsulationApiClient, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.create_certification_program(
            f.lot_mean_program_payload(**overrides), corporate_ops_headers()
        ),
        201,
    )


def create_plant(client: InsulationApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        client.create_plant(f.plant_payload(**overrides), corporate_ops_headers()), 201
    )


def get_plant(client: InsulationApiClient, plant_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_plant(plant_id, corporate_ops_headers()))


def plant_version(client: InsulationApiClient, plant_id: str) -> int:
    return int(get_plant(client, plant_id)["version"])


# --- Binder formulations -----------------------------------------------------


def create_draft_binder(client: InsulationApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        client.create_binder_formulation(
            f.binder_payload(**overrides), quality_engineer_headers()
        ),
        201,
    )


def certify_binder(
    client: InsulationApiClient,
    binder_id: str,
    formaldehyde_ppm: float,
    voc_g_per_kg: float,
    emissions_cert_id: str = "CERT-0001",
) -> Dict[str, Any]:
    """DRAFT -> SUBMITTED -> EMISSIONS_TESTING -> CERTIFIED (PRD 3.2)."""
    get_success_data(client.submit_binder(binder_id, quality_engineer_headers()))
    get_success_data(
        client.record_binder_emissions_test(
            binder_id,
            f.binder_emissions_test_payload(formaldehyde_ppm, voc_g_per_kg),
            certification_officer_headers(),
        )
    )
    return get_success_data(
        client.binder_certification_decision(
            binder_id,
            f.binder_decision_payload("CERTIFY", emissions_cert_id=emissions_cert_id),
            certification_officer_headers(),
        )
    )


def create_certified_binder(
    client: InsulationApiClient, **overrides: Any
) -> Dict[str, Any]:
    """A CERTIFIED phenolic formulation unless overridden."""
    binder = create_draft_binder(client, **overrides)
    return certify_binder(
        client,
        binder["id"],
        binder["formaldehyde_ppm"],
        binder["voc_g_per_kg"],
    )


def create_certified_formaldehyde_free_binder(
    client: InsulationApiClient, **overrides: Any
) -> Dict[str, Any]:
    payload = f.formaldehyde_free_binder_payload(**overrides)
    binder = get_success_data(
        client.create_binder_formulation(payload, quality_engineer_headers()), 201
    )
    return certify_binder(
        client, binder["id"], payload["formaldehyde_ppm"], payload["voc_g_per_kg"]
    )


# --- Product lines -----------------------------------------------------------


def create_product_line(
    client: InsulationApiClient,
    plant_id: str,
    binder_formulation_id: str,
    certification_program_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.product_line_payload(
        plant_id, binder_formulation_id, certification_program_id, **overrides
    )
    return get_success_data(
        client.create_product_line(payload, corporate_ops_headers()), 201
    )


def get_product_line(client: InsulationApiClient, product_line_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.get_product_line(product_line_id, corporate_ops_headers())
    )


# --- Base scenario -----------------------------------------------------------


def base_setup(
    client: InsulationApiClient,
    program_overrides: Optional[Dict[str, Any]] = None,
    plant_overrides: Optional[Dict[str, Any]] = None,
    binder_overrides: Optional[Dict[str, Any]] = None,
    sku_overrides: Optional[Dict[str, Any]] = None,
    lot_mean: bool = False,
) -> Dict[str, Any]:
    """Program + plant + CERTIFIED binder + DRAFT SKU, with the clock at epoch."""
    reset_clock(client)
    if lot_mean:
        program = create_lot_mean_program(client, **(program_overrides or {}))
    else:
        program = create_per_specimen_program(client, **(program_overrides or {}))
    plant = create_plant(client, **(plant_overrides or {}))
    binder = create_certified_binder(client, **(binder_overrides or {}))
    sku = create_product_line(
        client,
        plant["id"],
        binder["id"],
        program["id"],
        **(sku_overrides or {}),
    )
    return {
        "program": program,
        "plant": plant,
        "binder": binder,
        "sku": sku,
        "plant_id": plant["id"],
        "sku_id": sku["id"],
        "program_id": program["id"],
        "binder_id": binder["id"],
        "operator": plant_operator_headers(plant["id"]),
    }


# --- Production runs ---------------------------------------------------------


def schedule_run(
    client: InsulationApiClient,
    plant_id: str,
    product_line_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.production_run_payload(plant_id, product_line_id, **overrides)
    return get_success_data(
        client.create_production_run(payload, plant_operator_headers(plant_id)), 201
    )


def get_run(client: InsulationApiClient, run_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_production_run(run_id, corporate_ops_headers()))


def start_melt(
    client: InsulationApiClient,
    plant_id: str,
    run_id: str,
    cullet_batch_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.start_melt(
            run_id, list(cullet_batch_ids or []), plant_operator_headers(plant_id)
        )
    )


def start_cure(
    client: InsulationApiClient, plant_id: str, run_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.start_cure(
            run_id, f.start_cure_payload(**overrides), plant_operator_headers(plant_id)
        )
    )


def package_run(
    client: InsulationApiClient, plant_id: str, run_id: str, bags_produced: int = 120
) -> Dict[str, Any]:
    return get_success_data(
        client.package_run(run_id, bags_produced, plant_operator_headers(plant_id))
    )


def run_to_melting(
    client: InsulationApiClient,
    plant_id: str,
    product_line_id: str,
    cullet_batch_ids: Optional[List[str]] = None,
    clock: str = "2026-08-02T06:00:00Z",
    **run_overrides: Any,
) -> Dict[str, Any]:
    """Schedule a run, advance the clock into its window and charge the furnace."""
    run = schedule_run(client, plant_id, product_line_id, **run_overrides)
    set_clock(client, clock)
    return start_melt(client, plant_id, run["id"], cullet_batch_ids)


def run_to_curing(
    client: InsulationApiClient,
    plant_id: str,
    product_line_id: str,
    cullet_batch_ids: Optional[List[str]] = None,
    clock: str = "2026-08-02T06:00:00Z",
    cure_overrides: Optional[Dict[str, Any]] = None,
    **run_overrides: Any,
) -> Dict[str, Any]:
    run = run_to_melting(
        client, plant_id, product_line_id, cullet_batch_ids, clock, **run_overrides
    )
    return start_cure(client, plant_id, run["id"], **(cure_overrides or {}))


def run_to_packaged(
    client: InsulationApiClient,
    plant_id: str,
    product_line_id: str,
    bags_produced: int = 120,
    cullet_batch_ids: Optional[List[str]] = None,
    clock: str = "2026-08-02T06:00:00Z",
    cure_overrides: Optional[Dict[str, Any]] = None,
    **run_overrides: Any,
) -> Dict[str, Any]:
    run = run_to_curing(
        client,
        plant_id,
        product_line_id,
        cullet_batch_ids,
        clock,
        cure_overrides,
        **run_overrides,
    )
    return package_run(client, plant_id, run["id"], bags_produced)


# --- Lots (cascade-created, discoverable only by filtering: PRD 3.4 / 2.3) ---


def lots_for_run(client: InsulationApiClient, run_id: str) -> List[Dict[str, Any]]:
    data, _meta = validate_paginated(
        client.list_inventory_lots(
            corporate_ops_headers(), {"production_run_id": run_id, "limit": 100}
        )
    )
    return data


def lot_for_run(client: InsulationApiClient, run_id: str) -> Dict[str, Any]:
    lots = lots_for_run(client, run_id)
    assert len(lots) == 1, (
        f"packaging cascade-creates exactly one lot for run {run_id}, found {len(lots)}"
    )
    return lots[0]


def child_lots(client: InsulationApiClient, parent_lot_id: str) -> List[Dict[str, Any]]:
    data, _meta = validate_paginated(
        client.list_inventory_lots(
            corporate_ops_headers(), {"parent_lot_id": parent_lot_id, "limit": 100}
        )
    )
    return data


def get_lot(client: InsulationApiClient, lot_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_inventory_lot(lot_id, corporate_ops_headers()))


# --- Cullet batches ----------------------------------------------------------


def stage_cullet(
    client: InsulationApiClient,
    plant_id: str,
    mass_kg: float,
    source_type: str = "EXTERNAL",
    source_run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Stage one batch, re-reading the plant version for the OCC guard (PRD 2.6)."""
    payload = f.cullet_batch_payload(
        plant_id,
        mass_kg,
        plant_version(client, plant_id),
        source_type=source_type,
        source_run_id=source_run_id,
    )
    return get_success_data(
        client.create_cullet_batch(payload, plant_operator_headers(plant_id)), 201
    )


def stage_cullet_batches(
    client: InsulationApiClient, plant_id: str, masses: List[float]
) -> List[Dict[str, Any]]:
    """Stage several batches in order, so created_at ascending matches the list."""
    return [stage_cullet(client, plant_id, mass) for mass in masses]


def cullet_batches_for_plant(
    client: InsulationApiClient, plant_id: str, **filters: Any
) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"plant_id": plant_id, "limit": 100}
    params.update(filters)
    data, _meta = validate_paginated(
        client.list_cullet_batches(corporate_ops_headers(), params)
    )
    return data


def get_cullet_batch(client: InsulationApiClient, batch_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_cullet_batch(batch_id, corporate_ops_headers()))


# --- Thermal tests -----------------------------------------------------------


def request_thermal_test(
    client: InsulationApiClient,
    run_id: str,
    product_line_id: str,
    certification_program_id: str,
    window_start: str = "2026-08-03T08:00:00Z",
    window_end: str = "2026-08-03T16:00:00Z",
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    headers = (
        quality_engineer_headers(user_id) if user_id else quality_engineer_headers()
    )
    payload = f.thermal_test_payload(
        run_id,
        product_line_id,
        certification_program_id,
        window_start=window_start,
        window_end=window_end,
    )
    return get_success_data(client.create_thermal_test(payload, headers), 201)


def record_thermal_result(
    client: InsulationApiClient,
    test_id: str,
    specimen_r_values: List[float],
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    headers = (
        quality_engineer_headers(user_id) if user_id else quality_engineer_headers()
    )
    get_success_data(client.start_lab(test_id, headers))
    return get_success_data(client.record_result(test_id, specimen_r_values, headers))


def completed_thermal_test(
    client: InsulationApiClient,
    run_id: str,
    product_line_id: str,
    certification_program_id: str,
    specimen_r_values: List[float],
    window_start: str = "2026-08-03T08:00:00Z",
    window_end: str = "2026-08-03T16:00:00Z",
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """REQUESTED -> IN_LAB -> result recorded, in one call (PRD 3.6)."""
    test = request_thermal_test(
        client,
        run_id,
        product_line_id,
        certification_program_id,
        window_start,
        window_end,
        user_id,
    )
    return record_thermal_result(client, test["id"], specimen_r_values, user_id)


def get_thermal_test(client: InsulationApiClient, test_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_thermal_test(test_id, corporate_ops_headers()))


def thermal_tests_for_sku(
    client: InsulationApiClient, product_line_id: str
) -> List[Dict[str, Any]]:
    data, _meta = validate_paginated(
        client.list_thermal_tests(
            corporate_ops_headers(), {"product_line_id": product_line_id, "limit": 100}
        )
    )
    return data


# --- SKU certification -------------------------------------------------------


def submit_sku(client: InsulationApiClient, product_line_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.submit_sku_certification(product_line_id, quality_engineer_headers())
    )


def certify_sku(
    client: InsulationApiClient,
    product_line_id: str,
    officer_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    headers = (
        certification_officer_headers(officer_user_id)
        if officer_user_id
        else certification_officer_headers()
    )
    return get_success_data(
        client.sku_certification_decision(
            product_line_id, f.sku_decision_payload("CERTIFY"), headers
        )
    )


def certified_sku_with_lot(
    client: InsulationApiClient,
    bags_produced: int = 120,
    specimen_r_values: Optional[List[float]] = None,
    program_overrides: Optional[Dict[str, Any]] = None,
    plant_overrides: Optional[Dict[str, Any]] = None,
    sku_overrides: Optional[Dict[str, Any]] = None,
    lot_mean: bool = False,
) -> Dict[str, Any]:
    """Full chain: reference data -> packaged run -> conforming test -> CERTIFIED SKU.

    Returns the base_setup dict extended with `run`, `lot` and `test`.
    """
    ctx = base_setup(
        client,
        program_overrides=program_overrides,
        plant_overrides=plant_overrides,
        sku_overrides=sku_overrides,
        lot_mean=lot_mean,
    )
    submit_sku(client, ctx["sku_id"])
    run = run_to_packaged(
        client, ctx["plant_id"], ctx["sku_id"], bags_produced=bags_produced
    )
    lot = lot_for_run(client, run["id"])
    test = completed_thermal_test(
        client,
        run["id"],
        ctx["sku_id"],
        ctx["program_id"],
        specimen_r_values or [13.10, 13.00, 12.90],
    )
    sku = certify_sku(client, ctx["sku_id"])
    ctx.update(
        {
            "run": run,
            "run_id": run["id"],
            "lot": lot,
            "lot_id": lot["id"],
            "test": test,
            "test_id": test["id"],
            "sku": sku,
        }
    )
    return ctx


# --- Lot disposition ---------------------------------------------------------


def quarantine_lot(
    client: InsulationApiClient, lot_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.quarantine_lot(
            lot_id, f.quarantine_payload("HOLD", **overrides), quality_engineer_headers()
        )
    )


# --- Channel demand and allocation ------------------------------------------


def place_order(
    client: InsulationApiClient,
    product_line_id: str,
    requested_sqft: float,
    buyer_user_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    headers = (
        channel_buyer_headers(buyer_user_id) if buyer_user_id else channel_buyer_headers()
    )
    payload = f.channel_order_payload(product_line_id, requested_sqft, **overrides)
    return get_success_data(client.create_channel_order(payload, headers), 201)


def get_order(client: InsulationApiClient, order_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_channel_order(order_id, corporate_ops_headers()))


def open_cycle(
    client: InsulationApiClient,
    plant_id: str,
    product_line_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.allocation_cycle_payload(plant_id, product_line_id, **overrides)
    return get_success_data(
        client.create_allocation_cycle(payload, channel_manager_headers()), 201
    )


def get_cycle(client: InsulationApiClient, cycle_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.get_allocation_cycle(cycle_id, corporate_ops_headers())
    )


def propose_cycle(client: InsulationApiClient, cycle_id: str) -> Dict[str, Any]:
    return get_success_data(client.propose_cycle(cycle_id, channel_manager_headers()))


def commit_cycle(client: InsulationApiClient, cycle_id: str) -> Dict[str, Any]:
    return get_success_data(client.commit_cycle(cycle_id, channel_manager_headers()))


def lines_for_cycle(
    client: InsulationApiClient, cycle_id: str, **filters: Any
) -> List[Dict[str, Any]]:
    """Proposed lines appear in no response body; they are found by filter (PRD 3.8)."""
    params: Dict[str, Any] = {"allocation_cycle_id": cycle_id, "limit": 100}
    params.update(filters)
    data, _meta = validate_paginated(
        client.list_allocation_lines(corporate_ops_headers(), params)
    )
    return data


def lines_for_order(
    client: InsulationApiClient, order_id: str, **filters: Any
) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"channel_order_id": order_id, "limit": 100}
    params.update(filters)
    data, _meta = validate_paginated(
        client.list_allocation_lines(corporate_ops_headers(), params)
    )
    return data


def lines_for_lot(
    client: InsulationApiClient, lot_id: str, **filters: Any
) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"inventory_lot_id": lot_id, "limit": 100}
    params.update(filters)
    data, _meta = validate_paginated(
        client.list_allocation_lines(corporate_ops_headers(), params)
    )
    return data


def manual_line(
    client: InsulationApiClient,
    cycle_id: str,
    order_id: str,
    lot_id: str,
    allocated_sqft: float,
    expected_version: Optional[int] = None,
) -> Dict[str, Any]:
    version = (
        expected_version
        if expected_version is not None
        else int(get_cycle(client, cycle_id)["version"])
    )
    payload = f.allocation_line_payload(
        cycle_id, order_id, lot_id, allocated_sqft, version
    )
    return get_success_data(
        client.create_allocation_line(payload, channel_manager_headers()), 201
    )


def get_line(client: InsulationApiClient, line_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_allocation_line(line_id, corporate_ops_headers()))


# --- Emissions and posture ---------------------------------------------------


def file_emissions_report(
    client: InsulationApiClient,
    plant_id: str,
    period_start: str,
    period_end: str,
) -> Dict[str, Any]:
    return get_success_data(
        client.file_emissions_report(
            plant_id,
            f.emissions_report_payload(period_start, period_end),
            environmental_compliance_headers(),
        )
    )


def posture_review(
    client: InsulationApiClient,
    plant_id: str,
    decision: str,
    override_reason: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.posture_review(
            plant_id,
            f.posture_review_payload(decision, override_reason),
            environmental_compliance_headers(),
        )
    )


def freeze_plant_via_exceedance(
    client: InsulationApiClient,
    plant_id: str,
    period_start: str = "2026-08-01T00:00:00Z",
    period_end: str = "2026-08-03T00:00:00Z",
    clock: str = "2026-08-04T00:00:00Z",
) -> Dict[str, Any]:
    """Drive melt_posture to FROZEN through an over-allowance report (PRD 3.9).

    The caller must have already produced cured runs inside the period whose
    booked masses exceed the plant's allowance.
    """
    set_clock(client, clock)
    return file_emissions_report(client, plant_id, period_start, period_end)
