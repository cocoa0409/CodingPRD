"""Payload factories — one per entity, input fields only.

Only source: input fields appear here. Computed and system fields (on_hand,
stock_status, cash_on_hand_cents, version, etc.) are never sent.
"""

DEFAULTS = {
    "HOST_NAME": "Test Host Site",
    "HOST_EMAIL": "contact@example.com",
    "PRODUCT_NAME": "Test Product",
    "DRIVER_NAME": "Test Driver",
}


def create_host_site_payload(**overrides) -> dict:
    """Required: name, contact_email. Optional: commission_model,
    flat_commission_pct, monthly_guarantee_cents."""
    defaults = {
        "name": DEFAULTS["HOST_NAME"],
        "contact_email": DEFAULTS["HOST_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    """Required: sku, name, category, unit_cost_cents. Optional: shelf_life_days."""
    defaults = {
        "sku": "SKU-TEST",
        "name": DEFAULTS["PRODUCT_NAME"],
        "category": "SNACK",
        "unit_cost_cents": 30,
        "shelf_life_days": 0,
    }
    defaults.update(overrides)
    return defaults


def create_machine_payload(host_site_id: str, **overrides) -> dict:
    """Required: host_site_id, asset_tag, machine_type. Optional: cash_capacity_cents,
    cash_alert_threshold_pct, par_fill_threshold_pct."""
    defaults = {
        "host_site_id": host_site_id,
        "asset_tag": "ASSET-TEST",
        "machine_type": "SNACK_VENDOR",
    }
    defaults.update(overrides)
    return defaults


def create_slot_payload(product_id: str, **overrides) -> dict:
    """Required: product_id, slot_code, capacity, par_level, price_cents."""
    defaults = {
        "product_id": product_id,
        "slot_code": "A1",
        "capacity": 10,
        "par_level": 10,
        "price_cents": 100,
    }
    defaults.update(overrides)
    return defaults


def create_driver_payload(**overrides) -> dict:
    """Required: full_name, employee_code."""
    defaults = {
        "full_name": DEFAULTS["DRIVER_NAME"],
        "employee_code": "EMP-TEST",
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(driver_id: str, service_date: str, **overrides) -> dict:
    """Required: driver_id, service_date."""
    defaults = {
        "driver_id": driver_id,
        "service_date": service_date,
    }
    defaults.update(overrides)
    return defaults


def create_stop_payload(machine_id: str, window_start_min: int, window_end_min: int, **overrides) -> dict:
    """Required: machine_id, window_start_min, window_end_min."""
    defaults = {
        "machine_id": machine_id,
        "window_start_min": window_start_min,
        "window_end_min": window_end_min,
    }
    defaults.update(overrides)
    return defaults


def create_visit_payload(route_stop_id: str, counted_lines: list, expected_machine_version: int, **overrides) -> dict:
    """Required: route_stop_id, counted_lines, expected_machine_version."""
    defaults = {
        "route_stop_id": route_stop_id,
        "counted_lines": counted_lines,
        "expected_machine_version": expected_machine_version,
    }
    defaults.update(overrides)
    return defaults


def create_sale_payload(machine_id: str, slot_id: str, quantity: int, payment_method: str, **overrides) -> dict:
    """Required: machine_id, slot_id, quantity, payment_method. Optional: settlement_status."""
    defaults = {
        "machine_id": machine_id,
        "slot_id": slot_id,
        "quantity": quantity,
        "payment_method": payment_method,
    }
    defaults.update(overrides)
    return defaults


def create_statement_payload(host_site_id: str, period_start: str, period_end: str, **overrides) -> dict:
    """Required: host_site_id, period_start, period_end."""
    defaults = {
        "host_site_id": host_site_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    defaults.update(overrides)
    return defaults


def create_ticket_payload(**overrides) -> dict:
    """Required: issue_type. Optional: blocking."""
    defaults = {
        "issue_type": "JAM",
    }
    defaults.update(overrides)
    return defaults


def counted_line(slot_id: str, physical_count: int, refill_units: int) -> dict:
    """Build one counted_lines entry for a restock visit."""
    return {"slot_id": slot_id, "physical_count": physical_count, "refill_units": refill_units}
