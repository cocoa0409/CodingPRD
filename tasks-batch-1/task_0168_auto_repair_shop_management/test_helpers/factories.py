"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

_counter = itertools.count(1)


def _uniq() -> int:
    return next(_counter)


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Customer",
        "phone": "555-0000",
        "email": "customer@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "vin": f"VIN{_uniq():08d}",
        "make": "Honda",
        "model": "Civic",
        "model_year": 2020,
        "odometer_miles": 30000,
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    # skill_level is optional (default B) — omitted unless overridden.
    defaults = {"full_name": "Test Technician"}
    defaults.update(overrides)
    return defaults


def create_service_bay_payload(**overrides) -> dict:
    defaults = {"bay_name": f"Bay-{_uniq()}"}
    defaults.update(overrides)
    return defaults


def create_labor_operation_payload(**overrides) -> dict:
    defaults = {
        "op_code": f"OP-{_uniq()}",
        "description": "Test operation",
        "book_hours": 1.0,
        "default_rate_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_markup_tier_payload(tier_index, lower_bound_cents, markup_pct, **overrides) -> dict:
    # upper_bound_cents is optional (null = unbounded top tier).
    defaults = {
        "tier_index": tier_index,
        "lower_bound_cents": lower_bound_cents,
        "markup_pct": markup_pct,
    }
    defaults.update(overrides)
    return defaults


def create_repair_order_payload(customer_id, vehicle_id, **overrides) -> dict:
    # tax_rate (default 0.0) and comeback_of_ro_id are optional.
    defaults = {
        "customer_id": customer_id,
        "vehicle_id": vehicle_id,
    }
    defaults.update(overrides)
    return defaults


def schedule_payload(bay_id, scheduled_start, scheduled_end, **overrides) -> dict:
    defaults = {
        "bay_id": bay_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    defaults.update(overrides)
    return defaults


def create_labor_line_payload(labor_operation_id, **overrides) -> dict:
    # technician_id, billing_method (default FLAT_RATE), rate_cents,
    # is_warranty (default false) are optional.
    defaults = {"labor_operation_id": labor_operation_id}
    defaults.update(overrides)
    return defaults


def create_part_line_payload(part_number, quantity, unit_cost_cents, **overrides) -> dict:
    # markup_mode (default MARGINAL), has_core (default false),
    # core_deposit_cents (default 0), is_warranty (default false) are optional.
    defaults = {
        "part_number": part_number,
        "description": "Test part",
        "quantity": quantity,
        "unit_cost_cents": unit_cost_cents,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(technician_id, **overrides) -> dict:
    defaults = {"technician_id": technician_id}
    defaults.update(overrides)
    return defaults


def add_inspection_item_payload(point_name, **overrides) -> dict:
    # severity (default GREEN) and note are optional.
    defaults = {"point_name": point_name}
    defaults.update(overrides)
    return defaults


def create_recommended_job_payload(repair_order_id, labor_operation_id, **overrides) -> dict:
    # part_number, part_quantity (default 0), part_unit_cost_cents (default 0),
    # has_core (default false), core_deposit_cents (default 0),
    # severity (default YELLOW) are optional.
    defaults = {
        "repair_order_id": repair_order_id,
        "labor_operation_id": labor_operation_id,
    }
    defaults.update(overrides)
    return defaults
