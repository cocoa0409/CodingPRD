"""Payload factories — one per entity, input fields only."""
from .constants import CONTRACT_DEFAULTS, TEST_DEFAULTS


def create_district_payload(**overrides) -> dict:
    defaults = {
        "name": "Test District",
        "region_fuel_index_code": TEST_DEFAULTS["REGION_FUEL_INDEX_CODE"],
        "credit_limit_cents": TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
        "billing_dispute_window_days": TEST_DEFAULTS["BILLING_DISPUTE_WINDOW_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(district_id, **overrides) -> dict:
    defaults = {
        "district_id": district_id,
        "bid_reference": "BID-1",
        **CONTRACT_DEFAULTS,
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(contract_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "route_code": "R1",
        "school_site": TEST_DEFAULTS["ROUTE_SCHOOL_SITE"],
        "am_start_minute": 420,
        "am_end_minute": 480,
        "student_count": 40,
    }
    defaults.update(overrides)
    return defaults


def create_driver_payload(district_id, **overrides) -> dict:
    defaults = {
        "primary_district_id": district_id,
        "full_name": "Test Driver",
        "license_number": "L-000",
        "license_class": "B",
        "hourly_wage_cents": TEST_DEFAULTS["HOURLY_WAGE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_training_event_payload(driver_id, **overrides) -> dict:
    defaults = {
        "driver_id": driver_id,
        "category": "BEHIND_WHEEL",
        "minutes": 60,
        "occurred_on": "2026-04-01",
    }
    defaults.update(overrides)
    return defaults


def create_credential_payload(driver_id, **overrides) -> dict:
    defaults = {
        "driver_id": driver_id,
        "kind": "CDL_B",
        "issued_on": "2026-04-10",
        "expires_on": "2027-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_bus_payload(district_id, **overrides) -> dict:
    defaults = {
        "district_id": district_id,
        "fleet_number": "B-1",
        "capacity": TEST_DEFAULTS["BUS_CAPACITY"],
        "fuel_type": "DIESEL",
        "mpg_x10": TEST_DEFAULTS["BUS_MPG_X10"],
        "next_inspection_due": TEST_DEFAULTS["BUS_NEXT_INSPECTION_DUE"],
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(bus_id, **overrides) -> dict:
    defaults = {
        "bus_id": bus_id,
        "scheduled_date": "2026-05-10",
        "inspector_ref": "ST-1",
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(bus_id, **overrides) -> dict:
    defaults = {
        "bus_id": bus_id,
        "category": "REPAIR",
        "description": "Repair work",
    }
    defaults.update(overrides)
    return defaults


def create_service_day_payload(contract_id, service_date, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "service_date": service_date,
    }
    defaults.update(overrides)
    return defaults


def create_charter_trip_payload(contract_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "purpose": "Field trip",
        "trip_date": "2026-06-10",
        "pickup_minute": 600,
        "return_minute": 720,
        "estimated_hours_x10": 20,
        "estimated_miles": 40,
        "passenger_count": 20,
    }
    defaults.update(overrides)
    return defaults


def create_fuel_price_entry_payload(district_id, **overrides) -> dict:
    defaults = {
        "district_id": district_id,
        "effective_month": "2026-06",
        "avg_price_cents_per_gallon": 400,
        "source": "EIA",
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(contract_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "period_month": "2026-06",
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(district_id, **overrides) -> dict:
    defaults = {
        "district_id": district_id,
        "category": "ACCIDENT",
        "severity": "LOW",
        "description": "Incident narrative",
        "occurred_at": "2026-04-30T15:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_ridership_report_payload(assignment_id, service_day_id, **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "service_day_id": service_day_id,
        "boardings": 40,
        "alightings": 40,
        "first_pickup_actual_minute": 421,
        "last_dropoff_actual_minute": 479,
    }
    defaults.update(overrides)
    return defaults
