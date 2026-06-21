"""Composite setup helpers (commercial fleet leasing).

Every helper builds its preconditions from scratch via PRD-declared endpoints
(the database is empty before each test). Setup calls use get_success_data()
so setup failures surface clearly. The returned dicts are the live entity
bodies (with server-assigned id and version).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    assess_repair_payload,
    create_driver_payload,
    create_fuel_card_payload,
    create_fuel_transaction_payload,
    create_ifta_return_payload,
    create_lease_payload,
    create_lessee_payload,
    create_maintenance_order_payload,
    create_repair_order_payload,
    create_settlement_payload,
    create_telematics_reading_payload,
    create_vehicle_payload,
)
from .test_users import TEST_USERS

FM = TEST_USERS["fleet_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
TG = TEST_USERS["telematics_gateway_headers"]


# -- primitives ---------------------------------------------------------------

def make_lessee(**overrides) -> dict:
    return get_success_data(
        api_client.create_lessee(create_lessee_payload(**overrides), FM)
    )


def make_vehicle(**overrides) -> dict:
    return get_success_data(
        api_client.create_vehicle(create_vehicle_payload(**overrides), FM)
    )


def make_driver(lessee_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_driver(create_driver_payload(lessee_id, **overrides), FM)
    )


def make_lease(lessee_id, vehicle_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_lease(
            create_lease_payload(lessee_id, vehicle_id, **overrides), FM
        )
    )


def read_vehicle(vehicle_id) -> dict:
    return get_success_data(api_client.get_vehicle(vehicle_id, FM))


def read_lease(lease_id) -> dict:
    return get_success_data(api_client.get_lease(lease_id, FM))


# -- Tier 1/2: lessee + vehicle + active lease --------------------------------

def setup_active_lease(*, vehicle_class="MEDIUM_DUTY", lease_overrides=None):
    """Lessee ACTIVE + Vehicle + Lease activated (vehicle ALLOCATED).

    Returns (lessee, vehicle, lease) where `lease` is the activated body
    (so lease["version"] is the post-activation version).
    """
    lessee = make_lessee()
    vehicle = make_vehicle(**{"class": vehicle_class})
    lease = make_lease(lessee["id"], vehicle["id"], **(lease_overrides or {}))
    activated = get_success_data(api_client.activate_lease(lease["id"], FM))
    return lessee, vehicle, activated


# -- Tier 3: assessed repair order --------------------------------------------

def setup_assessed_repair(*, estimate_cents, insurance_cap_cents,
                          waterfall_model="DEDUCTIBLE_FIRST",
                          collision_deductible_cents=100000,
                          vehicle_class="MEDIUM_DUTY"):
    """Active lease + RepairOrder ASSESSED with the given money inputs.

    Returns (lessee, vehicle, lease, repair).
    """
    lessee, vehicle, lease = setup_active_lease(
        vehicle_class=vehicle_class,
        lease_overrides={
            "waterfall_model": waterfall_model,
            "collision_deductible_cents": collision_deductible_cents,
        },
    )
    veh = read_vehicle(vehicle["id"])
    repair = get_success_data(
        api_client.create_repair_order(
            create_repair_order_payload(vehicle["id"], lease["id"], veh["version"]),
            FM,
        )
    )
    repair = get_success_data(
        api_client.assess_repair(
            repair["id"],
            assess_repair_payload(estimate_cents, insurance_cap_cents),
            FM,
        )
    )
    return lessee, vehicle, lease, repair


# -- Tier 4: settlement-ready (driven, returned, settlement opened) -----------

def setup_settlement_open(*, driven_odometer, vehicle_class="HEAVY_DUTY",
                          overage_model="CONTRACT_FLAT", contracted_miles=60000,
                          per_mile_overage_cents=25, harsh_events=10,
                          idle_minutes=100, jurisdiction="CA"):
    """Active lease driven to `driven_odometer` via one telematics reading,
    RETURN_INITIATED, then settlement opened (Lease PENDING_SETTLEMENT,
    settlement DRAFT). Returns (lessee, vehicle, lease, settlement).
    """
    lessee, vehicle, lease = setup_active_lease(
        vehicle_class=vehicle_class,
        lease_overrides={
            "overage_model": overage_model,
            "contracted_miles": contracted_miles,
            "per_mile_overage_cents": per_mile_overage_cents,
        },
    )
    get_success_data(
        api_client.create_telematics_reading(
            create_telematics_reading_payload(
                vehicle["id"],
                jurisdiction=jurisdiction,
                odometer_miles=driven_odometer,
                segment_miles=driven_odometer,
                harsh_events=harsh_events,
                idle_minutes=idle_minutes,
            ),
            TG,
        )
    )
    get_success_data(api_client.initiate_return(lease["id"], FM))
    settlement = get_success_data(
        api_client.create_settlement(create_settlement_payload(lease["id"]), FM)
    )
    return lessee, vehicle, lease, settlement


# -- fuel card with a posted transaction --------------------------------------

def setup_card_with_txn(*, gallons=120, vehicle_class="HEAVY_DUTY"):
    """Active lease + ACTIVE fuel card + one POSTED fuel transaction.

    Returns (lessee, vehicle, lease, card, txn).
    """
    lessee, vehicle, lease = setup_active_lease(vehicle_class=vehicle_class)
    card = get_success_data(
        api_client.create_fuel_card(create_fuel_card_payload(lease["id"]), FM)
    )
    txn = get_success_data(
        api_client.create_fuel_transaction(
            create_fuel_transaction_payload(card["id"], gallons=gallons), FM
        )
    )
    return lessee, vehicle, lease, card, txn


# -- maintenance order on an active vehicle -----------------------------------

def setup_scheduled_maintenance(*, vehicle_class="LIGHT_DUTY", mo_overrides=None):
    """Active lease (vehicle ALLOCATED) + one SCHEDULED MaintenanceOrder.

    Returns (lessee, vehicle, lease, maintenance_order).
    """
    lessee, vehicle, lease = setup_active_lease(vehicle_class=vehicle_class)
    mo = get_success_data(
        api_client.create_maintenance_order(
            create_maintenance_order_payload(vehicle["id"], **(mo_overrides or {})), FM
        )
    )
    return lessee, vehicle, lease, mo


# -- IFTA return open ----------------------------------------------------------

def setup_ifta_return_open(*, quarter="2026Q1"):
    """Lessee + IftaReturn DRAFT. Returns (lessee, ifta_return)."""
    lessee = make_lessee()
    ifta = get_success_data(
        api_client.create_ifta_return(
            create_ifta_return_payload(lessee["id"], quarter=quarter), CO
        )
    )
    return lessee, ifta
