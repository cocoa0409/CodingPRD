"""Payload factories — one per entity, input fields only."""


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Customer",
        "email": "test@example.com",
        "phone": "555-0000",
    }
    defaults.update(overrides)
    return defaults


def create_workbench_payload(**overrides) -> dict:
    defaults = {
        "bench_name": "Test Bench",
        "bench_type": "ASSEMBLY",
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(customer_id, **overrides) -> dict:
    defaults = {"customer_id": customer_id}
    defaults.update(overrides)
    return defaults


def add_frame_line_payload(expected_order_version, **overrides) -> dict:
    """Required: expected_order_version, artwork_label, nominal_width_in,
    nominal_height_in, molding_rate_per_ui. All other fields are optional with
    server-side defaults (mat_border_in=2, mat_layers=1, glass_type=REGULAR,
    mounting_type=NONE, conservation_package=false, is_fragile=false)."""
    defaults = {
        "expected_order_version": expected_order_version,
        "artwork_label": "Test Piece",
        "nominal_width_in": 8,
        "nominal_height_in": 10,
        "molding_rate_per_ui": 0.30,
    }
    defaults.update(overrides)
    return defaults


def measure_payload(measured_width_in, measured_height_in) -> dict:
    return {
        "measured_width_in": measured_width_in,
        "measured_height_in": measured_height_in,
    }


def create_task_payload(order_id, workbench_id, start_minute, end_minute) -> dict:
    return {
        "order_id": order_id,
        "workbench_id": workbench_id,
        "start_minute": start_minute,
        "end_minute": end_minute,
    }


def payment_payload(kind, amount) -> dict:
    return {"kind": kind, "amount": amount}
