"""Tank reconciliation, compensating voids, processing-batch yields, and
reverse FK listings."""
import pytest

from test_helpers import (
    ApiErrorId,
    complete_visit,
    create_container,
    create_customer,
    create_manifest,
    create_truck,
    dispatch_manifest,
    get_success_data,
    make_driver_headers,
    manifest_visits,
    container_visits,
    set_clock,
    setup_completed_visit,
    setup_reconciled_manifest,
    start_visit,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import BILL, DISP, FOPS, PLANT, create_active_customer


# ---------------------------------------------------------------------------
# Corner: reverse FK — containers of a customer
# ---------------------------------------------------------------------------

def test_fk_reverse_containers_list(api, field_ops_headers):
    """PRD §3.3: "A `FieldOpsManager` places a container at a customer site"
    PRD §4: GET /api/customers/{id}/containers — "List containers of a
    customer"

    Design: Corner/endpoints/c_fk_reverse_containers_list
    """
    set_clock("2026-08-02T00:00:00Z")
    customer, _ = create_active_customer(name="FK House")
    c1 = create_container(customer["id"], capacity=300, fill_rate=100,
                          lock_code="LKF1")
    c2 = create_container(customer["id"], capacity=400, fill_rate=150,
                          lock_code="LKF2")
    resp = api.list_customer_containers(customer["id"], field_ops_headers)
    data = validate_success(resp, expected_status=200)
    ids = {row["id"] for row in data}
    assert ids == {c1["id"], c2["id"]}
    assert len(data) == 2


# ---------------------------------------------------------------------------
# Corner: reconcile with computed collected_gallons
# ---------------------------------------------------------------------------

def test_reconcile_computed_collected(api):
    """PRD §3.4: "Closing recomputes `collected_gallons` as the sum of
    `pump_gallons` across the manifest's visits in `COMPLETED` status — `VOID`
    visits excluded — at two decimal places."
    PRD §3.4: "the expected end level is `start_level_gallons` plus
    `collected_gallons` minus `spill_loss_gallons`, and the reconcile is
    rejected with `ERR_TANK_IMBALANCE` when the measured end level deviates
    from that expectation by more than 0.5 gallons in either direction."

    Two completions 200 + 300; end 490 / spill 10 -> |490 - (0+500-10)| == 0.

    Design: Corner/endpoints/c_reconcile_computed_collected
    """
    set_clock("2026-08-02T00:00:00Z")
    customer, _ = create_active_customer(name="Sum House")
    c1 = create_container(customer["id"], capacity=400, fill_rate=200,
                          lock_code="LKR1")
    c2 = create_container(customer["id"], capacity=400, fill_rate=200,
                          lock_code="LKR2")
    truck = create_truck(plate="T-C16", tank_capacity=2000)
    manifest = create_manifest(truck["id"], [c1["id"], c2["id"]],
                               service_date="2026-08-05")
    dispatch_manifest(manifest["id"], start_level=0)
    v1 = container_visits(c1["id"])[0]
    v2 = container_visits(c2["id"])[0]
    set_clock("2026-08-05T08:00:00Z")
    start_visit(v1["id"])
    complete_visit(v1["id"], pump_gallons=200.00, field_moisture_pct=5.0)
    start_visit(v2["id"])
    complete_visit(v2["id"], pump_gallons=300.00, field_moisture_pct=5.0)
    get_success_data(api.complete_manifest(manifest["id"], make_driver_headers("drv-1")))
    resp = api.reconcile_manifest(
        manifest["id"], {"end_level_gallons": 490, "spill_loss_gallons": 10}, DISP
    )
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "RECONCILED"
    assert data["collected_gallons"] == pytest.approx(500, abs=0.001)


# ---------------------------------------------------------------------------
# Difficulty: tank mass conservation with a compensating void
# ---------------------------------------------------------------------------

def _mass_setup(api):
    """Manifest 2026-08-05 dispatched with start_level 100; v1 pump 200.00,
    v2 pump 300.00; manifest completed (collected 500)."""
    set_clock("2026-08-02T00:00:00Z")
    customer, _ = create_active_customer(name="Mass House")
    c1 = create_container(customer["id"], capacity=400, fill_rate=200,
                          lock_code="LKM1")
    c2 = create_container(customer["id"], capacity=400, fill_rate=200,
                          lock_code="LKM2")
    truck = create_truck(plate="T-14", tank_capacity=2000)
    manifest = create_manifest(truck["id"], [c1["id"], c2["id"]],
                               service_date="2026-08-05")
    dispatch_manifest(manifest["id"], start_level=100)
    v1 = container_visits(c1["id"])[0]
    v2 = container_visits(c2["id"])[0]
    set_clock("2026-08-05T08:00:00Z")
    start_visit(v1["id"])
    complete_visit(v1["id"], pump_gallons=200.00, field_moisture_pct=5.0)
    start_visit(v2["id"])
    complete_visit(v2["id"], pump_gallons=300.00, field_moisture_pct=5.0)
    get_success_data(api.complete_manifest(manifest["id"], make_driver_headers("drv-1")))
    return manifest, v1, v2


def test_void_removes_gallons_and_imbalanced_reconcile_rejected(api):
    """PRD §3.5: "Voiding records the `void_reason` (again supplied as
    `reason`), moves the visit `COMPLETED` → `VOID`, recomputes the manifest's
    `collected_gallons` excluding the voided visit"
    PRD §3.4: "the reconcile is rejected with `ERR_TANK_IMBALANCE` when the
    measured end level deviates from that expectation by more than 0.5 gallons
    in either direction."

    After the void: collected == 200; |291 - (100 + 200 - 10)| == 1.0 > 0.5.

    Design: Difficulty/compensating_invariant/tank_mass_conservation_with_void
    """
    manifest, _, v2 = _mass_setup(api)
    get_success_data(
        api.void_pickup_visit(v2["id"], {"reason": "meter ticket lost"}, DISP)
    )
    manifest_after = get_success_data(api.get_manifest(manifest["id"], DISP))
    assert manifest_after["collected_gallons"] == pytest.approx(200, abs=0.001)
    resp = api.reconcile_manifest(
        manifest["id"], {"end_level_gallons": 291, "spill_loss_gallons": 10}, DISP
    )
    validate_error(resp, ApiErrorId.ERR_TANK_IMBALANCE, expected_status=422)


def test_reconcile_after_void_balances(api):
    """PRD §3.4: "The invariant is compensating: voiding a completed pickup
    removes its gallons from `collected_gallons`, so a reconcile performed
    after a void still balances."
    PRD §3.4: "Reconciliation is the dispatcher's final accounting and moves
    the manifest `COMPLETED` → `RECONCILED`, its terminal state."

    end 290 == start 100 + collected 200 - spill 10 exactly.

    Design: Difficulty/compensating_invariant/tank_mass_conservation_with_void
    """
    manifest, _, v2 = _mass_setup(api)
    get_success_data(
        api.void_pickup_visit(v2["id"], {"reason": "meter ticket lost"}, DISP)
    )
    resp = api.reconcile_manifest(
        manifest["id"], {"end_level_gallons": 290, "spill_loss_gallons": 10}, DISP
    )
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "RECONCILED"
    assert data["collected_gallons"] == pytest.approx(200, abs=0.001)


# ---------------------------------------------------------------------------
# Difficulty: batch estimated vs metered yield divergence
# ---------------------------------------------------------------------------

def _batch_divergence_setup(api):
    """Reconciled manifest, collected 1000 (single pickup pump 1000.00 field
    moisture 10.0, no sample graded — effective moisture falls back to field)."""
    return setup_reconciled_manifest(
        name="Diner Two", truck_plate="T-2",
        container_capacity=1200, container_fill_rate=1000, tank_capacity=2000,
        pump_gallons=1000.00, field_moisture_pct=10.0,
    )


def test_batch_intake_computes_weighted_moisture_and_est_yield(api, plant_headers):
    """PRD §3.9: "First, `weighted_moisture_pct`: the volume-weighted effective
    moisture across the manifest's `COMPLETED`, non-`VOID` pickups, where each
    pickup's effective moisture is its `lab_moisture_pct` when that pickup has
    a `GRADED` sample and its `field_moisture_pct` otherwise — the sum of each
    pickup's `pump_gallons` multiplied by its effective moisture, divided by the
    total pumped gallons, rounded half-up to two decimal places."
    PRD §3.9: "Second, `est_yield_gallons`: the input gallons multiplied by one
    minus the weighted moisture fraction, multiplied by the fixed yield
    coefficient 0.92, rounded half-up to two decimal places."

    1000.00 x (1 - 10.00/100) x 0.92 == 828.00.

    Design: Difficulty/dual_variant_calc/batch_estimated_vs_metered_yield_divergence
    """
    ctx = _batch_divergence_setup(api)
    batch = get_success_data(
        api.create_processing_batch(
            {"manifest_id": ctx["manifest"]["id"], "input_gallons": 1000},
            plant_headers,
        )
    )
    assert batch["weighted_moisture_pct"] == pytest.approx(10.00, abs=0.001)
    assert batch["est_yield_gallons"] == pytest.approx(828.00, abs=0.001)


def test_batch_metered_yield_diverges_from_estimate(api, plant_headers):
    """PRD §3.9: "Processing records the metered `actual_output_gallons` of
    saleable product and moves the batch `INTAKE` → `PROCESSED`, computing
    `yield_rate` as the metered output divided by `input_gallons`, rounded
    half-up to four decimal places. The metered yield supersedes the estimate:
    the formula-derived estimate at intake and the metered reality at process
    completion commonly diverge for the same batch."

    Metered 850.00: yield_rate == 0.85; estimate 828.00 != 850.00.

    Design: Difficulty/dual_variant_calc/batch_estimated_vs_metered_yield_divergence
    """
    ctx = _batch_divergence_setup(api)
    batch = get_success_data(
        api.create_processing_batch(
            {"manifest_id": ctx["manifest"]["id"], "input_gallons": 1000},
            plant_headers,
        )
    )
    processed = get_success_data(
        api.process_batch(batch["id"], {"actual_output_gallons": 850}, plant_headers)
    )
    assert processed["actual_output_gallons"] == pytest.approx(850, abs=0.001)
    assert processed["yield_rate"] == pytest.approx(0.85, abs=0.0001)
    assert processed["est_yield_gallons"] != pytest.approx(
        processed["actual_output_gallons"], abs=0.001
    ), "estimated and metered yields diverge by 22.00 gallons"


# ---------------------------------------------------------------------------
# Corner: volume-weighted moisture is not an arithmetic mean
# ---------------------------------------------------------------------------

def test_batch_weighted_moisture_volume_weighting(api, plant_headers):
    """PRD §3.9: "First, `weighted_moisture_pct`: the volume-weighted effective
    moisture across the manifest's `COMPLETED`, non-`VOID` pickups, where each
    pickup's effective moisture is its `lab_moisture_pct` when that pickup has
    a `GRADED` sample and its `field_moisture_pct` otherwise — the sum of each
    pickup's `pump_gallons` multiplied by its effective moisture, divided by the
    total pumped gallons, rounded half-up to two decimal places."

    600 gal @10% + 400 gal @5% -> (6000 + 2000)/1000 == 8.00 (not 7.50);
    est_yield 1000 x 0.92 x 0.92 == 846.40.

    Design: Corner/calculations/c_batch_weighted_moisture_volume_weighting
    """
    set_clock("2026-08-02T00:00:00Z")
    customer, _ = create_active_customer(name="Blend House")
    c1 = create_container(customer["id"], capacity=700, fill_rate=600,
                          lock_code="LKB1")
    c2 = create_container(customer["id"], capacity=500, fill_rate=400,
                          lock_code="LKB2")
    truck = create_truck(plate="T-C7", tank_capacity=1500)
    manifest = create_manifest(truck["id"], [c1["id"], c2["id"]],
                               service_date="2026-08-05")
    dispatch_manifest(manifest["id"], start_level=0)
    v1 = container_visits(c1["id"])[0]
    v2 = container_visits(c2["id"])[0]
    set_clock("2026-08-05T08:00:00Z")
    start_visit(v1["id"])
    complete_visit(v1["id"], pump_gallons=600.00, field_moisture_pct=10.0)
    start_visit(v2["id"])
    complete_visit(v2["id"], pump_gallons=400.00, field_moisture_pct=5.0)
    get_success_data(api.complete_manifest(manifest["id"], make_driver_headers("drv-1")))
    get_success_data(
        api.reconcile_manifest(
            manifest["id"], {"end_level_gallons": 1000, "spill_loss_gallons": 0}, DISP
        )
    )
    batch = get_success_data(
        api.create_processing_batch(
            {"manifest_id": manifest["id"], "input_gallons": 1000}, plant_headers
        )
    )
    assert batch["weighted_moisture_pct"] == pytest.approx(8.00, abs=0.001)
    assert batch["est_yield_gallons"] == pytest.approx(846.40, abs=0.001)
