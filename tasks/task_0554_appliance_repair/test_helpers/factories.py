"""Payload factories — one per creatable resource, input fields only.

Only fields the client supplies (source: input) appear here; computed and
system-managed fields are populated by the server.
"""


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Homeowner",
        "email": "homeowner@example.com",
        "phone": "555-0100",
        "address": "1 Test Street",
    }
    defaults.update(overrides)
    return defaults


def create_appliance_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "brand": "Kenmore",
        "model": "M1",
        "serial_number": "SN-1",
        "purchase_date": "2022-01-15",
    }
    defaults.update(overrides)
    return defaults


def create_warranty_contract_payload(appliance_id, coverage_type="EXTENDED", **overrides) -> dict:
    defaults = {
        "appliance_id": appliance_id,
        "coverage_type": coverage_type,
        "coverage_start": "2025-01-01",
        "coverage_end": "2027-01-01",
        "deductible_cents": 0,
        "coverage_cap_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_part_payload(**overrides) -> dict:
    defaults = {
        "part_number": "P1",
        "name": "Test Part",
        "unit_price_cents": 4500,
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    defaults = {"full_name": "Test Technician"}
    defaults.update(overrides)
    return defaults


def create_truck_stock_payload(technician_id, part_id, **overrides) -> dict:
    defaults = {
        "technician_id": technician_id,
        "part_id": part_id,
        "quantity_on_hand": 5,
    }
    defaults.update(overrides)
    return defaults


def create_service_zone_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Zone",
        "max_concurrent_appointments": 5,
    }
    defaults.update(overrides)
    return defaults


def create_service_request_payload(customer_id, appliance_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "appliance_id": appliance_id,
        "reported_issue": "appliance malfunction",
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(technician_id, zone_id, window_start, window_end, **overrides) -> dict:
    defaults = {
        "technician_id": technician_id,
        "zone_id": zone_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults


def create_diagnose_payload(labor_tasks, required_parts, **overrides) -> dict:
    defaults = {
        "labor_tasks": labor_tasks,
        "required_parts": required_parts,
    }
    defaults.update(overrides)
    return defaults


def create_revision_payload(labor_tasks, required_parts, expected_service_request_version, **overrides) -> dict:
    defaults = {
        "labor_tasks": labor_tasks,
        "required_parts": required_parts,
        "expected_service_request_version": expected_service_request_version,
    }
    defaults.update(overrides)
    return defaults


def create_recall_payload(brand, model, **overrides) -> dict:
    defaults = {
        "brand": brand,
        "model": model,
        "description": "safety hazard",
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(amount_cents, **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "method": "CARD",
    }
    defaults.update(overrides)
    return defaults
