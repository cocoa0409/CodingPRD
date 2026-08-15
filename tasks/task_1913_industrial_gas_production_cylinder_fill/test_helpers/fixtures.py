"""Composite setup helpers for multi-step test prerequisites.

Every helper builds state from scratch using only PRD-declared endpoints and
returns the PRD resource bodies. Setup calls use get_success_data() so failures
surface as clear "Setup step failed" errors. Each test runs against a freshly
restarted server (empty database, logical clock at the 2026-08-01T00:00:00Z
startup default per PRD §2.4).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_blend_order_payload,
    create_billing_run_payload,
    create_customer_payload,
    create_cylinder_payload,
    create_driver_payload,
    create_fill_lot_payload,
    create_installation_payload,
    create_plant_payload,
    create_rental_payload,
    create_route_payload,
    create_tank_payload,
)
from .test_users import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]
OP = TEST_USERS["production_operator_headers"]
LAB = TEST_USERS["lab_analyst_headers"]
QM = TEST_USERS["quality_manager_headers"]
LC = TEST_USERS["logistics_coordinator_headers"]
BC = TEST_USERS["billing_clerk_headers"]


# --- Tier 1: single-resource creation / state progression ---

def set_logical_clock(to_iso8601: str, headers=None):
    """Advance the plant logical clock (PRD §2.4). Returns the clock body."""
    res = api_client.set_clock({"to_iso8601": to_iso8601}, headers or PM)
    return get_success_data(res)


def create_test_plant(headers=None, **overrides):
    res = api_client.create_plant(create_plant_payload(**overrides), headers or PM)
    return get_success_data(res)


def create_test_tank(plant_id: str, headers=None, **overrides):
    res = api_client.create_tank(
        create_tank_payload(plant_id, **overrides), headers or PM
    )
    return get_success_data(res)


def create_test_cylinder(headers=None, **overrides):
    res = api_client.create_cylinder(create_cylinder_payload(**overrides), headers or OP)
    return get_success_data(res)


def create_test_customer(headers=None, **overrides):
    res = api_client.create_customer(
        create_customer_payload(**overrides), headers or BC
    )
    return get_success_data(res)


def create_test_driver(headers=None, **overrides):
    res = api_client.create_driver(create_driver_payload(**overrides), headers or LC)
    return get_success_data(res)


def create_test_route(headers=None, **overrides):
    res = api_client.create_route(create_route_payload(**overrides), headers or LC)
    return get_success_data(res)


def create_test_billing_run(headers=None, **overrides):
    res = api_client.create_billing_run(
        create_billing_run_payload(**overrides), headers or BC
    )
    return get_success_data(res)


def post_telemetry(payload: dict, headers=None):
    res = api_client.create_telemetry_reading(payload, headers or OP)
    return get_success_data(res)


def get_tank(tank_id: str, headers=None):
    return get_success_data(api_client.get_tank(tank_id, headers or OP))


def get_cylinder(cylinder_id: str, headers=None):
    return get_success_data(api_client.get_cylinder(cylinder_id, headers or OP))


def get_fill_lot(fill_lot_id: str, headers=None):
    return get_success_data(api_client.get_fill_lot(fill_lot_id, headers or OP))


def get_customer(customer_id: str, headers=None):
    return get_success_data(api_client.get_customer(customer_id, headers or BC))


def get_rental(rental_id: str, headers=None):
    return get_success_data(api_client.get_rental(rental_id, headers or BC))


def get_route(route_id: str, headers=None):
    return get_success_data(api_client.get_route(route_id, headers or LC))


def get_driver(driver_id: str, headers=None):
    return get_success_data(api_client.get_driver(driver_id, headers or LC))


def get_installation(installation_id: str, headers=None):
    return get_success_data(api_client.get_installation(installation_id, headers or LC))


def get_blend_order(blend_order_id: str, headers=None):
    return get_success_data(api_client.get_blend_order(blend_order_id, headers or BC))


# --- Tier 2/3: fill-lot production hierarchy and lifecycle ---

def setup_plant_with_tank(plant_overrides=None, tank_overrides=None):
    """OPERATING plant plus one IN_SERVICE tank. Returns (plant, tank)."""
    plant = create_test_plant(**(plant_overrides or {}))
    tank = create_test_tank(plant["id"], **(tank_overrides or {}))
    return plant, tank


def create_test_fill_lot(tank_id: str, headers=None, **overrides):
    res = api_client.create_fill_lot(
        create_fill_lot_payload(tank_id, **overrides), headers or OP
    )
    return get_success_data(res)


def setup_planned_lot(num_cylinders=1, tank_overrides=None, cylinder_overrides=None,
                      lot_overrides=None):
    """Plant + tank + PLANNED lot with N cylinders RESERVED into it.

    Returns dict(plant, tank, lot, cylinders).
    """
    plant, tank = setup_plant_with_tank(tank_overrides=tank_overrides)
    gas = (lot_overrides or {}).get("product_code", "O2")
    cylinders = [
        create_test_cylinder(service_gas=gas, **(cylinder_overrides or {}))
        for _ in range(num_cylinders)
    ]
    lot = create_test_fill_lot(tank["id"], **(lot_overrides or {}))
    for cyl in cylinders:
        get_success_data(
            api_client.assign_cylinder_to_lot(lot["id"], {"cylinder_id": cyl["id"]}, OP)
        )
    lot = get_fill_lot(lot["id"])
    return {"plant": plant, "tank": tank, "lot": lot, "cylinders": cylinders}


def start_fill_lot(lot_id: str, headers=None):
    return get_success_data(api_client.start_fill(lot_id, headers or OP))


def complete_fill_lot(lot_id: str, cylinders, residual_pressure_bar=15, headers=None):
    """Complete a FILLING lot with measured residuals for every cylinder."""
    residuals = [
        {"cylinder_id": c["id"], "residual_pressure_bar": residual_pressure_bar}
        for c in cylinders
    ]
    return get_success_data(
        api_client.complete_fill(lot_id, {"measured_residuals": residuals},
                                 headers or OP)
    )


def record_lot_analysis(lot_id: str, readings=None, headers=None):
    payload = {
        "subject_type": "FILL_LOT",
        "fill_lot_id": lot_id,
        "readings": readings if readings is not None
        else [{"analyte": "CO", "reading_ppm": 5}],
    }
    return get_success_data(api_client.create_purity_analysis(payload, headers or LAB))


def setup_awaiting_analysis_lot(num_cylinders=1, residual_pressure_bar=15,
                                tank_overrides=None, cylinder_overrides=None,
                                lot_overrides=None):
    """PLANNED -> FILLING -> AWAITING_ANALYSIS. Returns the setup dict."""
    ctx = setup_planned_lot(
        num_cylinders=num_cylinders, tank_overrides=tank_overrides,
        cylinder_overrides=cylinder_overrides, lot_overrides=lot_overrides,
    )
    start_fill_lot(ctx["lot"]["id"])
    complete_fill_lot(ctx["lot"]["id"], ctx["cylinders"],
                      residual_pressure_bar=residual_pressure_bar)
    ctx["lot"] = get_fill_lot(ctx["lot"]["id"])
    return ctx


def setup_released_lot(num_cylinders=1, readings=None, tank_overrides=None,
                       cylinder_overrides=None, lot_overrides=None):
    """Full fill lifecycle through a PASS analysis: cylinders FILLED, lot RELEASED.

    Returns dict(plant, tank, lot, cylinders, analysis).
    """
    ctx = setup_awaiting_analysis_lot(
        num_cylinders=num_cylinders, tank_overrides=tank_overrides,
        cylinder_overrides=cylinder_overrides, lot_overrides=lot_overrides,
    )
    analysis = record_lot_analysis(ctx["lot"]["id"], readings=readings)
    ctx["analysis"] = analysis
    ctx["lot"] = get_fill_lot(ctx["lot"]["id"])
    ctx["cylinders"] = [get_cylinder(c["id"]) for c in ctx["cylinders"]]
    return ctx


def setup_failed_lot(num_cylinders=1, fail_readings=None):
    """Lot through complete-fill, then a FAIL analysis: lot ANALYSIS_FAILED,
    cylinders QUARANTINED with the lot link kept. Returns the setup dict."""
    ctx = setup_awaiting_analysis_lot(num_cylinders=num_cylinders)
    readings = fail_readings or [{"analyte": "CO", "reading_ppm": 20}]
    ctx["analysis"] = record_lot_analysis(ctx["lot"]["id"], readings=readings)
    ctx["lot"] = get_fill_lot(ctx["lot"]["id"])
    ctx["cylinders"] = [get_cylinder(c["id"]) for c in ctx["cylinders"]]
    return ctx


# --- Tier 3: rentals ---

def create_test_rental(customer_id: str, cylinder_id: str, headers=None, **overrides):
    res = api_client.create_rental(
        create_rental_payload(customer_id, cylinder_id, **overrides), headers or BC
    )
    return get_success_data(res)


def setup_active_rental(daily_rate_cents=1000, planned_days=5, customer_overrides=None,
                        num_extra_filled=0):
    """Released lot with 1 (+extra) FILLED cylinders, ACTIVE customer, one rental
    checked out. Returns dict(ctx..., customer, rental)."""
    ctx = setup_released_lot(num_cylinders=1 + num_extra_filled)
    customer = create_test_customer(**(customer_overrides or {}))
    rental = create_test_rental(
        customer["id"], ctx["cylinders"][0]["id"],
        daily_rate_cents=daily_rate_cents, planned_days=planned_days,
    )
    ctx["customer"] = customer
    ctx["rental"] = rental
    return ctx


def return_test_rental(rental_id: str, return_condition="OK", headers=None):
    return get_success_data(
        api_client.return_rental(rental_id, {"return_condition": return_condition},
                                 headers or BC)
    )


# --- Tier 3: drivers and routes ---

def setup_assigned_route(driver_overrides=None, route_overrides=None):
    """QUALIFIED driver + PLANNED route -> DRIVER_ASSIGNED. Returns (driver, route)."""
    driver = create_test_driver(**(driver_overrides or {}))
    route = create_test_route(**(route_overrides or {}))
    get_success_data(api_client.assign_driver(route["id"], {"driver_id": driver["id"]}, LC))
    return driver, get_route(route["id"])


def setup_dispatched_route(driver_overrides=None, route_overrides=None):
    """Assigned route taken through dispatch. Returns (driver, route)."""
    driver, route = setup_assigned_route(driver_overrides, route_overrides)
    get_success_data(api_client.dispatch_route(route["id"], LC))
    return driver, get_route(route["id"])


# --- Tier 3: bulk installations and replenishment ---

def create_test_installation(customer_id: str, headers=None, **overrides):
    res = api_client.create_installation(
        create_installation_payload(customer_id, **overrides), headers or PM
    )
    return get_success_data(res)


def set_installation_status(installation_id: str, target_status: str, headers=None):
    return get_success_data(
        api_client.set_installation_status(
            installation_id, {"target_status": target_status}, headers or PM
        )
    )


def setup_active_installation(customer_overrides=None, installation_overrides=None):
    """Customer + installation walked PROPOSED -> INSTALLED -> ACTIVE.

    Returns dict(customer, installation).
    """
    customer = create_test_customer(**(customer_overrides or {}))
    installation = create_test_installation(customer["id"], **(installation_overrides or {}))
    set_installation_status(installation["id"], "INSTALLED")
    installation = set_installation_status(installation["id"], "ACTIVE")
    return {"customer": customer, "installation": installation}


def create_test_replenishment_order(installation_id: str, scheduled_delivery_at: str,
                                    expected_installation_version: int, headers=None):
    res = api_client.create_replenishment_order(
        {
            "installation_id": installation_id,
            "scheduled_delivery_at": scheduled_delivery_at,
            "expected_installation_version": expected_installation_version,
        },
        headers or LC,
    )
    return get_success_data(res)


# --- Tier 3: blend orders ---

def create_test_blend_order(customer_id: str, headers=None, **overrides):
    res = api_client.create_blend_order(
        create_blend_order_payload(customer_id, **overrides), headers or BC
    )
    return get_success_data(res)


def setup_approved_blend(num_tanks_per_product=1, customer_overrides=None,
                         blend_overrides=None):
    """Customer + blend order approved to APPROVED, with O2/N2 tanks available.

    Returns dict(customer, blend, tanks, plant).
    """
    plant = create_test_plant()
    tanks = {}
    for product in ("O2", "N2"):
        for _ in range(num_tanks_per_product):
            tank = create_test_tank(plant["id"], product_code=product)
            tanks.setdefault(product, []).append(tank)
    customer = create_test_customer(**(customer_overrides or {}))
    blend = create_test_blend_order(customer["id"], **(blend_overrides or {}))
    get_success_data(api_client.approve_blend_order(blend["id"], QM))
    blend = get_blend_order(blend["id"])
    return {"customer": customer, "blend": blend, "tanks": tanks, "plant": plant}


def setup_awaiting_analysis_blend(**kwargs):
    """Blend walked through start-blend and complete-blend to AWAITING_ANALYSIS."""
    ctx = setup_approved_blend(**kwargs)
    get_success_data(api_client.start_blend(ctx["blend"]["id"], OP))
    get_success_data(api_client.complete_blend(ctx["blend"]["id"], OP))
    ctx["blend"] = get_blend_order(ctx["blend"]["id"])
    return ctx


# --- Tier 5: billing runs ---

def finalize_test_billing_run(billing_run_id: str, headers=None):
    return get_success_data(api_client.finalize_billing_run(billing_run_id, headers or BC))


def post_test_billing_run(billing_run_id: str, headers=None):
    return get_success_data(api_client.post_billing_run(billing_run_id, headers or BC))


def post_test_payment(customer_id: str, amount_cents: int, headers=None):
    return get_success_data(
        api_client.post_payment(customer_id, {"amount_cents": amount_cents},
                                headers or BC)
    )
