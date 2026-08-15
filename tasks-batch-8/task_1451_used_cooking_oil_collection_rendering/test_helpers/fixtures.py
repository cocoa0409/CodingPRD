"""Composite setup helpers.

Each helper builds PRD-declared state from scratch (the harness restarts the
server before every test, so every test begins against an empty database).
Setup calls use get_success_data() so failures surface as clear setup errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    complete_visit_payload,
    create_complaint_payload,
    create_container_payload,
    create_contract_payload,
    create_customer_payload,
    create_quote_payload,
    create_theft_incident_payload,
    create_truck_payload,
    generate_settlement_payload,
    grade_sample_payload,
)
from .test_users import TEST_USERS, make_driver_headers

ADMIN = TEST_USERS["system_admin_headers"]
FOPS = TEST_USERS["field_ops_headers"]
DISP = TEST_USERS["dispatcher_headers"]
BILL = TEST_USERS["billing_headers"]
PLANT = TEST_USERS["plant_headers"]

DEFAULT_DRIVER = TEST_DEFAULTS["DRIVER_REF"]


def set_clock(to_iso8601: str):
    """Advance the logical clock (PRD §2.4)."""
    get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_customer(name="Test Site", address="1 Fry Way", max_gal=5000) -> dict:
    return get_success_data(
        api_client.create_customer(
            create_customer_payload(
                name=name, site_address=address, site_max_container_gal=max_gal
            ),
            FOPS,
        )
    )


def create_contract(customer_id, activate=True, **overrides) -> dict:
    contract = get_success_data(
        api_client.create_contract(
            customer_id, create_contract_payload(**overrides), FOPS
        )
    )
    if activate:
        contract = get_success_data(api_client.activate_contract(contract["id"], FOPS))
    return contract


def create_active_customer(name="Test Site", address="1 Fry Way", max_gal=5000,
                           contract_overrides=None) -> tuple:
    """Customer + ACTIVE contract (customer flips PROSPECT -> ACTIVE per PRD §3.1)."""
    customer = create_customer(name=name, address=address, max_gal=max_gal)
    contract = create_contract(customer["id"], activate=True,
                               **(contract_overrides or {}))
    return customer, contract


def create_container(customer_id, capacity=300, fill_rate=100, lock_code="LK1") -> dict:
    return get_success_data(
        api_client.create_container(
            customer_id,
            create_container_payload(
                capacity_gallons=capacity,
                est_fill_rate_gal_per_week=fill_rate,
                lock_code=lock_code,
            ),
            FOPS,
        )
    )


def create_truck(plate="T-1", tank_capacity=500) -> dict:
    return get_success_data(
        api_client.create_truck(
            create_truck_payload(plate=plate, tank_capacity_gallons=tank_capacity),
            DISP,
        )
    )


def create_manifest(truck_id, container_ids, service_date="2026-08-05",
                    driver_ref=DEFAULT_DRIVER) -> dict:
    return get_success_data(
        api_client.create_manifest(
            {
                "truck_id": truck_id,
                "driver_ref": driver_ref,
                "service_date": service_date,
                "container_ids": list(container_ids),
            },
            DISP,
        )
    )


def dispatch_manifest(manifest_id, start_level=0) -> dict:
    return get_success_data(
        api_client.dispatch_manifest(manifest_id, {"start_level_gallons": start_level}, DISP)
    )


def manifest_visits(manifest_id) -> list:
    return get_success_data(api_client.list_manifest_pickup_visits(manifest_id, DISP))


def container_visits(container_id) -> list:
    return get_success_data(api_client.list_container_pickup_visits(container_id, DISP))


def start_visit(visit_id, driver_ref=DEFAULT_DRIVER) -> dict:
    return get_success_data(
        api_client.start_pickup_visit(visit_id, make_driver_headers(driver_ref))
    )


def complete_visit(visit_id, pump_gallons=100.00, field_moisture_pct=5.0,
                   driver_ref=DEFAULT_DRIVER) -> dict:
    return get_success_data(
        api_client.complete_pickup_visit(
            visit_id,
            complete_visit_payload(
                pump_gallons=pump_gallons, field_moisture_pct=field_moisture_pct
            ),
            make_driver_headers(driver_ref),
        )
    )


def draw_and_grade_sample(visit_id, lab_moisture_pct=10.0, lab_impurity_pct=1.0,
                          driver_ref=DEFAULT_DRIVER) -> dict:
    """Draw -> submit -> grade. Returns the GRADED sample."""
    sample = get_success_data(
        api_client.create_sample(visit_id, make_driver_headers(driver_ref))
    )
    get_success_data(api_client.submit_sample(sample["id"], make_driver_headers(driver_ref)))
    return get_success_data(
        api_client.grade_sample(
            sample["id"],
            grade_sample_payload(
                lab_moisture_pct=lab_moisture_pct, lab_impurity_pct=lab_impurity_pct
            ),
            PLANT,
        )
    )


def publish_quote(index_code="YG_CBI", week_start="2026-08-03", price=100) -> dict:
    quote = get_success_data(
        api_client.create_quote(
            create_quote_payload(
                index_code=index_code, week_start=week_start,
                price_cents_per_gal=price,
            ),
            BILL,
        )
    )
    return get_success_data(api_client.publish_quote(quote["id"], BILL))


def generate_settlement(customer_id, period_start="2026-08-01",
                        period_end="2026-08-15") -> dict:
    return get_success_data(
        api_client.generate_settlement(
            generate_settlement_payload(
                customer_id=customer_id,
                period_start=period_start,
                period_end=period_end,
            ),
            BILL,
        )
    )


# ---------------------------------------------------------------------------
# Composite scenarios
# ---------------------------------------------------------------------------

def setup_dispatched_single_stop(
    name="Route House",
    container_capacity=300,
    container_fill_rate=100,
    truck_plate="T-1",
    tank_capacity=500,
    service_date="2026-08-05",
    clock_iso="2026-08-02T00:00:00Z",
    contract_overrides=None,
):
    """ACTIVE customer + contract, one container, truck, DRAFT manifest dispatched.

    Returns dict with keys: customer, contract, container, truck, manifest, visit.
    The visit is the manifest's single SCHEDULED PickupVisit.
    """
    set_clock(clock_iso)
    customer, contract = create_active_customer(
        name=name, contract_overrides=contract_overrides
    )
    container = create_container(customer["id"], capacity=container_capacity,
                                 fill_rate=container_fill_rate)
    truck = create_truck(plate=truck_plate, tank_capacity=tank_capacity)
    manifest = create_manifest(truck["id"], [container["id"]], service_date=service_date)
    manifest = dispatch_manifest(manifest["id"])
    visit = manifest_visits(manifest["id"])[0]
    return {
        "customer": customer,
        "contract": contract,
        "container": container,
        "truck": truck,
        "manifest": manifest,
        "visit": visit,
    }


def setup_completed_visit(
    name="Done House",
    container_capacity=300,
    container_fill_rate=100,
    truck_plate="T-1",
    tank_capacity=500,
    service_date="2026-08-05",
    pump_gallons=100.00,
    field_moisture_pct=5.0,
    setup_clock="2026-08-02T00:00:00Z",
    run_clock="2026-08-05T08:00:00Z",
    contract_overrides=None,
):
    """Dispatched manifest whose single visit has been started and completed.

    Returns the setup_dispatched_single_stop dict with the completed visit.
    """
    ctx = setup_dispatched_single_stop(
        name=name,
        container_capacity=container_capacity,
        container_fill_rate=container_fill_rate,
        truck_plate=truck_plate,
        tank_capacity=tank_capacity,
        service_date=service_date,
        clock_iso=setup_clock,
        contract_overrides=contract_overrides,
    )
    set_clock(run_clock)
    start_visit(ctx["visit"]["id"])
    ctx["visit"] = complete_visit(
        ctx["visit"]["id"], pump_gallons=pump_gallons,
        field_moisture_pct=field_moisture_pct,
    )
    return ctx


def setup_reconciled_manifest(
    name="Recon House",
    container_capacity=1200,
    container_fill_rate=1000,
    truck_plate="T-1",
    tank_capacity=2000,
    service_date="2026-08-05",
    pump_gallons=1000.00,
    field_moisture_pct=10.0,
    setup_clock="2026-08-02T00:00:00Z",
    run_clock="2026-08-05T08:00:00Z",
):
    """Manifest run to RECONCILED with one completed visit (no spill).

    Returns setup dict; manifest is in RECONCILED with collected == pump_gallons.
    """
    ctx = setup_completed_visit(
        name=name,
        container_capacity=container_capacity,
        container_fill_rate=container_fill_rate,
        truck_plate=truck_plate,
        tank_capacity=tank_capacity,
        service_date=service_date,
        pump_gallons=pump_gallons,
        field_moisture_pct=field_moisture_pct,
        setup_clock=setup_clock,
        run_clock=run_clock,
    )
    get_success_data(
        api_client.complete_manifest(ctx["manifest"]["id"], make_driver_headers(DEFAULT_DRIVER))
    )
    manifest = get_success_data(
        api_client.reconcile_manifest(
            ctx["manifest"]["id"],
            {"end_level_gallons": pump_gallons, "spill_loss_gallons": 0},
            DISP,
        )
    )
    ctx["manifest"] = manifest
    return ctx


def setup_provisional_settlement(
    name="Settle House",
    container_capacity=300,
    container_fill_rate=100,
    truck_plate="T-1",
    tank_capacity=500,
    service_date="2026-08-05",
    pump_gallons=100.00,
    field_moisture_pct=5.0,
    quote_weeks=(("2026-08-03", 100),),
    period_start="2026-08-01",
    period_end="2026-08-15",
    settle_clock="2026-08-15T00:00:00Z",
    setup_clock="2026-08-02T00:00:00Z",
    run_clock="2026-08-05T08:00:00Z",
    contract_overrides=None,
    grade=None,
):
    """Completed visit + published quotes + PROVISIONAL settlement.

    If `grade` is given as (lab_moisture_pct, lab_impurity_pct), the visit's
    sample is drawn and graded before settlement generation.
    Returns setup dict with extra key ``settlement``.
    """
    ctx = setup_completed_visit(
        name=name,
        container_capacity=container_capacity,
        container_fill_rate=container_fill_rate,
        truck_plate=truck_plate,
        tank_capacity=tank_capacity,
        service_date=service_date,
        pump_gallons=pump_gallons,
        field_moisture_pct=field_moisture_pct,
        setup_clock=setup_clock,
        run_clock=run_clock,
        contract_overrides=contract_overrides,
    )
    if grade is not None:
        ctx["sample"] = draw_and_grade_sample(
            ctx["visit"]["id"], lab_moisture_pct=grade[0], lab_impurity_pct=grade[1]
        )
    for week_start, price in quote_weeks:
        publish_quote(week_start=week_start, price=price,
                      index_code=(contract_overrides or {}).get("index_code", "YG_CBI"))
    set_clock(settle_clock)
    ctx["settlement"] = generate_settlement(
        ctx["customer"]["id"], period_start=period_start, period_end=period_end
    )
    return ctx
