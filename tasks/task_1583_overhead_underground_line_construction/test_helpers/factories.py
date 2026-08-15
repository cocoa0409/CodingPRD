"""Payload factories — one per creatable resource, input fields only.

Field names and optionality follow the PRD §3 narratives and §4 endpoint table.
"""


def create_contract_payload(**overrides) -> dict:
    defaults = {
        "utility_name": "City Power",
        "contract_number": "C-1",
        "effective_start": "2026-08-01T00:00:00Z",
        "effective_end": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_bid_item_payload(**overrides) -> dict:
    defaults = {
        "item_code": "OH-MISC",
        "description": "Miscellaneous line work",
        "unit": "EACH",
        "unit_price": 10.00,
        "estimated_quantity": 100,
    }
    defaults.update(overrides)
    return defaults


def create_work_package_payload(**overrides) -> dict:
    defaults = {
        "name": "Feeder rebuild",
        "location": "Rte 9 MP 3-5",
        "requires_outage": False,
    }
    defaults.update(overrides)
    return defaults


def create_crew_payload(**overrides) -> dict:
    defaults = {
        "crew_code": "CR-1",
        "crew_type": "OVERHEAD",
        "base_rate_per_hour": 55.00,
    }
    defaults.update(overrides)
    return defaults


def create_equipment_payload(**overrides) -> dict:
    defaults = {
        "equipment_code": "EQ-1",
        "kind": "BUCKET_TRUCK",
        "daily_rate": 120.00,
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(crew_id, equipment_id, **overrides) -> dict:
    defaults = {
        "crew_id": crew_id,
        "equipment_id": equipment_id,
        "start_date": "2026-08-03",
        "end_date": "2026-08-07",
    }
    defaults.update(overrides)
    return defaults


def create_production_entry_payload(bid_item_id, work_date, quantity_reported,
                                    expected_assignment_version, **overrides) -> dict:
    defaults = {
        "bid_item_id": bid_item_id,
        "work_date": work_date,
        "quantity_reported": quantity_reported,
        "expected_assignment_version": expected_assignment_version,
    }
    defaults.update(overrides)
    return defaults


def create_stock_item_payload(**overrides) -> dict:
    defaults = {
        "material_code": "MAT-1",
        "description": "Utility stock material",
        "uom": "EACH",
        "initial_on_hand": 0,
    }
    defaults.update(overrides)
    return defaults


def create_material_issue_payload(stock_item_id, quantity_issued, **overrides) -> dict:
    defaults = {
        "stock_item_id": stock_item_id,
        "quantity_issued": quantity_issued,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(production_entry_id, standard_code="UTIL-OH-1.0",
                              **overrides) -> dict:
    defaults = {
        "production_entry_id": production_entry_id,
        "standard_code": standard_code,
    }
    defaults.update(overrides)
    return defaults


def create_outage_request_payload(circuit_id, window_start, window_end, **overrides) -> dict:
    defaults = {
        "circuit_id": circuit_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults


def create_storm_activation_payload(crew_id, **overrides) -> dict:
    defaults = {
        "crew_id": crew_id,
        "kind": "STANDBY",
        "activation_date": "2026-08-05",
    }
    defaults.update(overrides)
    return defaults


def create_safety_event_payload(**overrides) -> dict:
    defaults = {
        "kind": "OBSERVATION",
        "severity": "POSITIVE",
        "description": "Routine field observation",
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(period_start, period_end, expected_work_package_version,
                           **overrides) -> dict:
    defaults = {
        "period_start": period_start,
        "period_end": period_end,
        "expected_work_package_version": expected_work_package_version,
    }
    defaults.update(overrides)
    return defaults
