"""Payload factories — one per entity, input fields only (PRD §3/§4)."""
import itertools

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_shop_payload(**overrides) -> dict:
    defaults = {"name": "FP Shop"}
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Acme Hydraulics",
        "email": f"ops{_seq()}@acme.com",
        "credit_limit_cents": 10_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    defaults = {"full_name": f"Tech {_seq()}", "skills": ["CYLINDER_REPAIR"]}
    defaults.update(overrides)
    return defaults


def create_seal_kit_payload(**overrides) -> dict:
    defaults = {
        "kit_code": f"SK-80-NBR-{_seq()}",
        "bore_min_mm": 60,
        "bore_max_mm": 100,
        "pressure_class_max": "CLASS_5000",
        "fluid_compat": ["MINERAL_OIL", "WATER_GLYCOL"],
        "price_cents": 18500,
        "material": "NBR",
    }
    defaults.update(overrides)
    return defaults


def create_cylinder_payload(customer_id, seal_kit_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "serial_number": f"CYL-{_seq():03d}",
        "bore_mm": 80,
        "stroke_mm": 500,
        "rod_diameter_mm": 45,
        "pressure_class": "CLASS_3000",
        "fluid_type": "MINERAL_OIL",
        "seal_kit_id": seal_kit_id,
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(cylinder_id, **overrides) -> dict:
    defaults = {
        "cylinder_id": cylinder_id,
        "tier": "EXPEDITE",
        "promised_hours": 30,
        "complaint": "leaking rod seal",
    }
    defaults.update(overrides)
    return defaults


def create_teardown_report_payload(work_order_id, **overrides) -> dict:
    defaults = {
        "work_order_id": work_order_id,
        "rod_needed": True,
        "rod_cut_length_mm": 500,
        "tube_needed": False,
        "honing_passes": 1,
        "estimated_labor_hours": 2.5,
        "findings_notes": "rod scored",
    }
    defaults.update(overrides)
    return defaults


def create_inventory_item_payload(**overrides) -> dict:
    defaults = {
        "material": "CHROME_ROD",
        "diameter_mm": 45,
        "length_mm": 1000,
        "cost_per_mm_cents": 42,
    }
    defaults.update(overrides)
    return defaults


def create_stock_reservation_payload(work_order_id, **overrides) -> dict:
    defaults = {
        "work_order_id": work_order_id,
        "material": "CHROME_ROD",
        "diameter_mm": 45,
        "cut_length_mm": 400,
    }
    defaults.update(overrides)
    return defaults


def create_test_bay_payload(**overrides) -> dict:
    defaults = {"name": f"BAY-{_seq()}"}
    defaults.update(overrides)
    return defaults


def create_pressure_test_payload(work_order_id, test_bay_id, **overrides) -> dict:
    defaults = {
        "work_order_id": work_order_id,
        "test_bay_id": test_bay_id,
        "window_start": "2026-08-02T10:00:00Z",
        "window_end": "2026-08-02T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def record_result_payload(**overrides) -> dict:
    defaults = {
        "measured_hold_psi": 4500,
        "duration_min": 10,
        "leakage_drops": 0,
        "passed": True,
    }
    defaults.update(overrides)
    return defaults


def create_exchange_unit_payload(**overrides) -> dict:
    defaults = {
        "bore_mm": 80,
        "stroke_mm": 500,
        "rod_diameter_mm": 45,
        "pressure_class": "CLASS_3000",
        "unit_price_cents": 250000,
    }
    defaults.update(overrides)
    return defaults


def hose_assembly(**overrides) -> dict:
    defaults = {
        "hose_type": "WIRE_BRAID_2SN",
        "length_m": 2.0,
        "fitting_price_cents": 1800,
        "crimp_spec_mm": 27.0,
    }
    defaults.update(overrides)
    return defaults


def create_field_service_job_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "site_address": "12 Quarry Rd",
        "distance_km": 60,
        "assemblies": [hose_assembly()],
    }
    defaults.update(overrides)
    return defaults


def cleanliness_payload(**overrides) -> dict:
    """Default sample meets all three default ISO 4406 targets."""
    defaults = {"c4_count": 200000, "c6_count": 60000, "c14_count": 8000}
    defaults.update(overrides)
    return defaults
