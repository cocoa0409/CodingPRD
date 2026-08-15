"""Payload factories — one per entity, client-input fields only (PRD §3, §4)."""

_counter = {"n": 0}


def _next() -> int:
    _counter["n"] += 1
    return _counter["n"]


def create_vessel_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "vessel_name": f"FV Aurora {n}",
        "registration_number": f"REG-{n:03d}",
        "home_port": "Gloucester",
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "business_name": f"Resto Group {n}",
        "credit_limit_cents": 1000000,
    }
    defaults.update(overrides)
    return defaults


def create_catch_area_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "fao_code": f"FAO{n}",
        "name": f"Northeast Atlantic {n}",
        "region": "Atlantic",
    }
    defaults.update(overrides)
    return defaults


def create_species_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "species_code": f"SP{n}",
        "common_name": f"Species {n}",
        "labeling_name": f"Species {n}",
        "substitution_group": "GADOID",
        "fresh_shelf_life_hours": 72,
        "frozen_shelf_life_days": 30,
    }
    defaults.update(overrides)
    return defaults


def create_market_quote_payload(**overrides) -> dict:
    defaults = {
        "species_id": None,
        "grade": "GRADE_A",
        "quote_date": "2026-08-01",
        "price_per_kg_cents": 1200,
    }
    defaults.update(overrides)
    return defaults


def create_dock_ticket_payload(**overrides) -> dict:
    defaults = {
        "vessel_id": None,
        "catch_area_id": None,
        "landing_start_at": "2026-08-01T06:00:00Z",
        "landing_end_at": "2026-08-01T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_landing_line_payload(**overrides) -> dict:
    defaults = {
        "dock_ticket_id": None,
        "species_id": None,
        "declared_grade": "GRADE_A",
        "landed_weight_kg": 50.00,
        "expected_dock_ticket_version": None,
    }
    defaults.update(overrides)
    return defaults


def create_grade_assessment_payload(**overrides) -> dict:
    defaults = {
        "landing_line_id": None,
        "assessed_grade": "GRADE_A",
        "yield_pct": 1.00,
    }
    defaults.update(overrides)
    return defaults


def create_sales_order_payload(**overrides) -> dict:
    defaults = {
        "customer_id": None,
        "required_delivery_date": "2026-08-05",
    }
    defaults.update(overrides)
    return defaults


def create_order_line_payload(**overrides) -> dict:
    defaults = {
        "sales_order_id": None,
        "species_id": None,
        "requested_grade": "GRADE_A",
        "requested_qty_kg": 10.00,
    }
    defaults.update(overrides)
    return defaults


def create_allocation_payload(**overrides) -> dict:
    defaults = {
        "order_line_id": None,
        "inventory_lot_id": None,
        "qty_kg": 10.00,
        "transit_hours": 8,
        "expected_sales_order_version": None,
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(**overrides) -> dict:
    defaults = {
        "sales_order_id": None,
        "mode": "TRUCK",
        "temp_zone": "CHILLED",
        "booked_weight_kg": 10.00,
    }
    defaults.update(overrides)
    return defaults


def create_import_document_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "dock_ticket_id": None,
        "species_id": None,
        "doc_type": "HEALTH_CERT",
        "reference_number": f"HC-{n:03d}",
    }
    defaults.update(overrides)
    return defaults


def create_inspection_hold_payload(**overrides) -> dict:
    defaults = {
        "inventory_lot_id": None,
        "reason": "spot check",
    }
    defaults.update(overrides)
    return defaults


def create_substitution_approval_payload(**overrides) -> dict:
    defaults = {
        "order_line_id": None,
        "substitute_species_id": None,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
