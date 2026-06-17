"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Defaults match the canonical fixture vocabulary so
the literal expected values in the test suite reproduce.
"""
from .constants import TEST_DEFAULTS, FILE_A, FILE_B


def create_bureau_payload(**overrides) -> dict:
    """POST /bureaus inputs (PRD §3.1). cooldown_buffer_min and
    shift_capacity_minutes are optional with server defaults 15 / 480."""
    defaults = {"name": "Test Bureau"}
    defaults.update(overrides)
    return defaults


def create_customer_payload(bureau_id, **overrides) -> dict:
    """POST /bureaus/customers inputs (PRD §3.1)."""
    defaults = {
        "bureau_id": bureau_id,
        "email": "customer@example.com",
        "display_name": "Test Customer",
    }
    defaults.update(overrides)
    return defaults


def create_material_payload(bureau_id, **overrides) -> dict:
    """POST /bureaus/materials inputs (PRD §3.1)."""
    defaults = {
        "bureau_id": bureau_id,
        "process": "SLA",
        "name": "Tough Resin",
        "density_g_per_cm3": TEST_DEFAULTS["DENSITY_G_PER_CM3"],
        "material_rate_cents_per_cm3": TEST_DEFAULTS["MATERIAL_RATE_CENTS_PER_CM3"],
        "machine_rate_cents_per_min": TEST_DEFAULTS["MACHINE_RATE_CENTS_PER_MIN"],
        "setup_fee_cents": TEST_DEFAULTS["SETUP_FEE_CENTS"],
        "min_wall_thickness_mm": TEST_DEFAULTS["MIN_WALL_THICKNESS_MM"],
        "max_overhang_deg": TEST_DEFAULTS["MAX_OVERHANG_DEG"],
    }
    defaults.update(overrides)
    return defaults


def create_machine_payload(bureau_id, **overrides) -> dict:
    """POST /bureaus/machines inputs (PRD §3.1)."""
    defaults = {
        "bureau_id": bureau_id,
        "process": "SLA",
        "label": "Form-A",
        "build_x_mm": TEST_DEFAULTS["BUILD_X_MM"],
        "build_y_mm": TEST_DEFAULTS["BUILD_Y_MM"],
        "build_z_mm": TEST_DEFAULTS["BUILD_Z_MM"],
    }
    defaults.update(overrides)
    return defaults


def create_spool_payload(bureau_id, material_id, **overrides) -> dict:
    """POST /bureaus/spools inputs (PRD §3.1)."""
    defaults = {
        "bureau_id": bureau_id,
        "material_id": material_id,
        "grams_total": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_print_file_payload(bureau_id, customer_id, geometry=None, **overrides) -> dict:
    """POST /bureaus/print-files inputs (PRD §3.2). `geometry` defaults to File A."""
    geo = dict(geometry or FILE_A)
    defaults = {
        "bureau_id": bureau_id,
        "customer_id": customer_id,
        "filename": "part.stl",
        **geo,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(bureau_id, customer_id, **overrides) -> dict:
    """POST /bureaus/orders inputs (PRD §3.3). lead_tier optional, default STANDARD."""
    defaults = {
        "bureau_id": bureau_id,
        "customer_id": customer_id,
        "lead_tier": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_order_line_payload(order_id, print_file_id, material_id, **overrides) -> dict:
    """POST /bureaus/order-lines inputs (PRD §3.3)."""
    defaults = {
        "order_id": order_id,
        "print_file_id": print_file_id,
        "material_id": material_id,
        "layer_height_mm": 0.10,
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_finishing_task_payload(order_line_id, **overrides) -> dict:
    """POST /bureaus/finishing-tasks inputs (PRD §3.4)."""
    defaults = {
        "order_line_id": order_line_id,
        "kind": "SUPPORT_REMOVAL",
        "addon_cents": 500,
        "station_start_min": 0,
        "station_duration_min": 10,
    }
    defaults.update(overrides)
    return defaults


def create_print_run_payload(order_line_id, machine_id, spool_id, **overrides) -> dict:
    """POST /bureaus/print-runs inputs (PRD §3.6)."""
    defaults = {
        "order_line_id": order_line_id,
        "machine_id": machine_id,
        "spool_id": spool_id,
        "start_min": 0,
        "duration_min": 24,
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(order_id, **overrides) -> dict:
    """POST /bureaus/shipments inputs (PRD §3.8)."""
    defaults = {
        "order_id": order_id,
        "carrier": "UPS",
        "tracking_number": "1Z999",
    }
    defaults.update(overrides)
    return defaults
