"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _unique_email(prefix="user"):
    return f"{prefix}-{next(_counter)}@example.com"


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Customer",
        "email": _unique_email("cust"),
    }
    defaults.update(overrides)
    return defaults


def create_field_tech_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Tech",
        "home_zone": "Z-NORTH",
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "property_type": "MUNICIPAL_WHOLE_HOUSE",
        "service_zone": "Z-NORTH",
    }
    defaults.update(overrides)
    return defaults


def create_water_test_payload(account_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "hardness_gpg": 15,
        "iron_ppm": 0,
        "tds_ppm": 200,
        "household_size": 4,
    }
    defaults.update(overrides)
    return defaults


def create_system_payload(account_id, source_test_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "source_test_id": source_test_id,
        "acquisition_mode": "PURCHASE",
        "grain_capacity": 32000,
    }
    defaults.update(overrides)
    return defaults


def create_rental_contract_payload(account_id, system_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "system_id": system_id,
        "monthly_rate_cents": 4500,
        "term_months": 12,
        "start_date": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(tech_id, **overrides) -> dict:
    defaults = {
        "service_zone": "Z-NORTH",
        "route_date": "2026-06-01T00:00:00Z",
        "tech_id": tech_id,
        "capacity_stops": 4,
    }
    defaults.update(overrides)
    return defaults


def create_route_stop_payload(system_id, **overrides) -> dict:
    defaults = {
        "system_id": system_id,
        "stop_type": "INSPECTION",
        "window_start": "2026-06-01T09:00:00Z",
        "window_end": "2026-06-01T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_cartridge_schedule_payload(system_id, **overrides) -> dict:
    defaults = {
        "system_id": system_id,
        "cartridge_type": "RO_MEMBRANE",
        "interval_days": 180,
        "last_replaced_at": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_service_visit_payload(system_id, **overrides) -> dict:
    defaults = {
        "system_id": system_id,
        "visit_type": "REPAIR",
        "gallons_treated_reading": 0,
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(system_id, **overrides) -> dict:
    defaults = {
        "system_id": system_id,
        "defect_class": "VALVE_FAILURE",
        "reported_at": "2026-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(account_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "invoice_kind": "SERVICE_REPAIR",
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-01-02T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
