"""Composite setup helpers for multi-step test preconditions.

Uses get_success_data() (lenient validator) internally so setup failures
produce clear "Setup failed" errors instead of confusing assertion failures.

Every helper builds its preconditions from scratch via PRD-declared endpoints —
each test runs against a freshly restarted server with an empty database and
the logical clock at its default 2026-08-01T00:00:00Z (PRD §2.4).

Identity threading: CustomerRep is entity-backed (PRD §2.1), so every
ownership-gated CustomerRep call is made with
make_customer_rep_headers(customer["id"]).
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    allocation_adjustment_payload,
    create_customer_payload,
    create_equipment_payload,
    create_facility_payload,
    create_incident_payload,
    create_invoice_payload,
    create_lot_payload,
    create_product_payload,
    create_railcar_payload,
    create_spot_order_payload,
    create_track_payload,
    create_transfer_order_payload,
    create_weight_ticket_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["facility_admin_headers"]
YARD = TEST_USERS["yard_master_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]
OPERATOR = TEST_USERS["transfer_operator_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


# ─── Tier 0: logical clock ──────────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Advance the logical clock (PRD §2.4; FacilityAdmin only)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ─── Tier 1: single-resource creation ───────────────────────────────────────

def create_facility(**overrides):
    return get_success_data(
        api_client.create_facility(create_facility_payload(**overrides), ADMIN)
    )


def create_customer(**overrides):
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), ADMIN)
    )


def create_product(**overrides):
    return get_success_data(
        api_client.create_product(create_product_payload(**overrides), ADMIN)
    )


def create_track(**overrides):
    return get_success_data(
        api_client.create_track(create_track_payload(**overrides), ADMIN)
    )


def create_equipment(**overrides):
    return get_success_data(
        api_client.create_equipment(create_equipment_payload(**overrides), ADMIN)
    )


def create_lot(customer_id, product_id, **overrides):
    return get_success_data(
        api_client.create_lot(
            create_lot_payload(
                customer_id=customer_id, product_id=product_id, **overrides
            ),
            ADMIN,
        )
    )


def create_railcar(customer_id, product_id, lot_id, **overrides):
    return get_success_data(
        api_client.create_railcar(
            create_railcar_payload(
                customer_id=customer_id,
                product_id=product_id,
                lot_id=lot_id,
                **overrides,
            ),
            YARD,
        )
    )


def create_incident(**overrides):
    return get_success_data(
        api_client.create_incident(create_incident_payload(**overrides), SAFETY)
    )


def get_railcar(railcar_id):
    return get_success_data(api_client.get_railcar(railcar_id, YARD))


def get_track(track_id):
    return get_success_data(api_client.get_track(track_id, YARD))


def get_equipment(equipment_id):
    return get_success_data(api_client.get_equipment(equipment_id, OPERATOR))


def get_lot(lot_id):
    return get_success_data(api_client.get_lot(lot_id, ADMIN))


def get_transfer_order(transfer_order_id):
    return get_success_data(api_client.get_transfer_order(transfer_order_id, OPERATOR))


def arrive_car(railcar_id):
    """REGISTERED -> ARRIVED (PRD §3.3). Returns the updated railcar."""
    return get_success_data(api_client.arrive_railcar(railcar_id, YARD))


# ─── Tier 1b: spot orders ───────────────────────────────────────────────────

def create_spot_order_for_car(
    railcar_id,
    track_id,
    spot_number=1,
    window_start="2026-08-03T01:00:00Z",
    window_end="2026-08-03T05:00:00Z",
    headers=None,
):
    """Create a spot order carrying the car's current version (PRD §2.8 OCC
    guard). Returns the REQUESTED spot order."""
    car = get_railcar(railcar_id)
    return get_success_data(
        api_client.create_spot_order(
            railcar_id,
            create_spot_order_payload(
                expected_railcar_version=car["version"],
                track_id=track_id,
                spot_number=spot_number,
                window_start=window_start,
                window_end=window_end,
            ),
            headers or YARD,
        ),
        201,
    )


def schedule_spot_order(spot_order_id):
    """REQUESTED -> SCHEDULED. Returns the updated spot order (with
    switch_order_id set, PRD §3.4)."""
    return get_success_data(api_client.schedule_spot_order(spot_order_id, YARD))


def execute_spot_order(spot_order_id):
    """SCHEDULED -> EXECUTED; places the car (PRD §3.4)."""
    return get_success_data(api_client.execute_spot_order(spot_order_id, YARD))


# ─── Tier 1c: transfer orders and weight tickets ────────────────────────────

def create_transfer_for(railcar_id, equipment_id, quantity_planned_tons=10.0):
    return get_success_data(
        api_client.create_transfer_order(
            create_transfer_order_payload(
                railcar_id=railcar_id,
                equipment_id=equipment_id,
                quantity_planned_tons=quantity_planned_tons,
            ),
            OPERATOR,
        ),
        201,
    )


def activate_transfer(transfer_order_id):
    return get_success_data(api_client.activate_transfer_order(transfer_order_id, OPERATOR))


def pause_transfer(transfer_order_id):
    return get_success_data(api_client.pause_transfer_order(transfer_order_id, OPERATOR))


def create_draft_ticket(
    transfer_order_id,
    gross_weight_tons=24.0,
    tare_weight_tons=14.0,
    truck_max_payload_tons=40.0,
    truck_reference="TRK-1",
):
    return get_success_data(
        api_client.create_weight_ticket(
            transfer_order_id,
            create_weight_ticket_payload(
                truck_reference=truck_reference,
                gross_weight_tons=gross_weight_tons,
                tare_weight_tons=tare_weight_tons,
                truck_max_payload_tons=truck_max_payload_tons,
            ),
            OPERATOR,
        ),
        201,
    )


def certify_ticket(weight_ticket_id):
    return get_success_data(api_client.certify_weight_ticket(weight_ticket_id, OPERATOR))


# ─── Tier 1d: billing ───────────────────────────────────────────────────────

def create_invoice_for(customer_id, period_start="2026-08-01T00:00:00Z",
                       period_end="2026-08-31T23:59:59Z", headers=None):
    return get_success_data(
        api_client.create_invoice(
            create_invoice_payload(
                customer_id=customer_id,
                period_start=period_start,
                period_end=period_end,
            ),
            headers or BILLING,
        ),
        201,
    )


def list_all_charges(headers=None, **filters):
    """List charge entries (BillingClerk). Callers filter client-side on the
    charge-line fields the PRD §3.8 names (customer_id, railcar_id,
    invoice_id, charge_type, status)."""
    params = {"limit": 100}
    params.update(filters)
    data, _meta = validate_paginated(
        api_client.list_charges(headers or BILLING, params=params)
    )
    return data


def list_all_switch_orders(headers=None):
    data, _meta = validate_paginated(
        api_client.list_switch_orders(headers or YARD, params={"limit": 100})
    )
    return data


# ─── Tier 2: entity hierarchy — car driven to SPOTTED ───────────────────────

def setup_spotted_car(
    *,
    facility_overrides=None,
    customer_overrides=None,
    product_overrides=None,
    lot_rate=5000,
    quantity_loaded_tons=40.0,
    spot_capacity=1,
    window_start="2026-08-03T01:00:00Z",
    window_end="2026-08-03T05:00:00Z",
    clock_start="2026-08-03T00:00:00Z",
    clock_execute="2026-08-03T02:00:00Z",
    car_number="10001",
    track_name="T1",
    spot_number=1,
):
    """Facility + customer + product + lot + track + car, car walked
    REGISTERED -> ARRIVED -> SPOTTED via a scheduled+executed spot order
    (PRD §3.3/§3.4). Returns a dict with every entity and the switch order id."""
    set_clock(clock_start)
    facility = create_facility(**(facility_overrides or {}))
    customer = create_customer(**(customer_overrides or {}))
    product = create_product(**(product_overrides or {}))
    lot = create_lot(customer["id"], product["id"], sit_daily_rate_cents=lot_rate)
    track = create_track(name=track_name, spot_capacity=spot_capacity)
    car = create_railcar(
        customer["id"],
        product["id"],
        lot["id"],
        car_number=car_number,
        quantity_loaded_tons=quantity_loaded_tons,
    )
    car = arrive_car(car["id"])
    spot_order = create_spot_order_for_car(
        car["id"], track["id"], spot_number, window_start, window_end
    )
    scheduled = schedule_spot_order(spot_order["id"])
    set_clock(clock_execute)
    execute_spot_order(spot_order["id"])
    car = get_railcar(car["id"])
    return {
        "facility": facility,
        "customer": customer,
        "product": product,
        "lot": lot,
        "track": track,
        "car": car,
        "spot_order": scheduled,
        "switch_order_id": scheduled["switch_order_id"],
    }


def setup_active_transfer(
    *,
    quantity_planned_tons=10.0,
    equipment_overrides=None,
    **spotted_kwargs,
):
    """setup_spotted_car + equipment + a transfer order activated
    (PLANNED -> ACTIVE; equipment IN_USE, car IN_TRANSFER — PRD §3.5)."""
    ctx = setup_spotted_car(**spotted_kwargs)
    equipment = create_equipment(**(equipment_overrides or {}))
    transfer = create_transfer_for(
        ctx["car"]["id"], equipment["id"], quantity_planned_tons
    )
    transfer = activate_transfer(transfer["id"])
    ctx["equipment"] = equipment
    ctx["transfer"] = transfer
    return ctx


def setup_ready_for_release_car(
    *,
    requires_full_clean=False,
    wash_type="DETERGENT",
    quantity_loaded_tons=10.0,
    **kwargs,
):
    """Car driven to READY_FOR_RELEASE: full-quantity certification empties
    the car; when the product requires a full clean, one cleaning pass follows
    (PRD §3.6/§3.7)."""
    product_overrides = dict(kwargs.pop("product_overrides", {}) or {})
    product_overrides["requires_full_clean"] = requires_full_clean
    ctx = setup_active_transfer(
        quantity_planned_tons=quantity_loaded_tons,
        quantity_loaded_tons=quantity_loaded_tons,
        product_overrides=product_overrides,
        **kwargs,
    )
    # One ticket whose net equals the full load: net = gross - tare.
    tare = 14.0
    ticket = create_draft_ticket(
        ctx["transfer"]["id"],
        gross_weight_tons=round(quantity_loaded_tons + tare, 3),
        tare_weight_tons=tare,
        truck_max_payload_tons=max(40.0, quantity_loaded_tons),
    )
    certify_ticket(ticket["id"])
    if requires_full_clean:
        get_success_data(
            api_client.start_railcar_cleaning(ctx["car"]["id"], wash_type, OPERATOR)
        )
        get_success_data(api_client.pass_railcar_cleaning(ctx["car"]["id"], OPERATOR))
    ctx["ticket"] = ticket
    ctx["car"] = get_railcar(ctx["car"]["id"])
    return ctx
