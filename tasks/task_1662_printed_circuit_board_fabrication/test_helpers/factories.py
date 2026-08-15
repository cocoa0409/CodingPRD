"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
from . import constants as C

DEFAULTS = {
    "COMPANY_NAME": "Test Circuits",
    "CONTACT_EMAIL": "ops@test-circuits.example",
    "CREDIT_LIMIT_CENTS": 1_000_000,
    "LANE_CODE": "QT3",
    "SHIP_DATE": C.DEFAULT_SHIP_DATE,
    "MANUFACTURE_DATE": C.DEFAULT_MANUFACTURE_DATE,
}


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "company_name": DEFAULTS["COMPANY_NAME"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
        "tax_exempt": False,
    }
    defaults.update(overrides)
    return defaults


def create_lane_payload(**overrides) -> dict:
    defaults = {
        "lane_code": DEFAULTS["LANE_CODE"],
        "turn_days": 3,
        "capacity_boards_per_day": 500,
        "premium_multiplier": 1.50,
        "active": True,
    }
    defaults.update(overrides)
    return defaults


def create_fab_order_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "service_lane": "STANDARD",
        "board_x_mils": C.G1_BOARD_X_MILS,
        "board_y_mils": C.G1_BOARD_Y_MILS,
        "layer_count": 2,
        "surface_finish": "HASL",
        "quantity_boards": C.G1_QUANTITY_BOARDS,
        "requested_ship_date": DEFAULTS["SHIP_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_stackup_payload(**overrides) -> dict:
    defaults = {
        "revision": 1,
        "total_thickness_mils": 62,
        "dielectric_material": "FR4_TG170",
        "copper_weight_oz": 1,
        "impedance_controlled": False,
    }
    defaults.update(overrides)
    return defaults


def create_spec_line_payload(**overrides) -> dict:
    defaults = {
        "layer_name": "L1",
        "target_ohms": 50.0,
        "tolerance_plus_ohms": 5.0,
        "tolerance_minus_ohms": 5.0,
        "line_type": "SINGLE_ENDED",
        "coupon_required": True,
    }
    defaults.update(overrides)
    return defaults


def create_panel_array_payload(expected_fab_order_version, **overrides) -> dict:
    defaults = {
        "array_x": C.G1_ARRAY_X,
        "array_y": C.G1_ARRAY_Y,
        "panel_width_mils": C.G1_PANEL_WIDTH_MILS,
        "panel_height_mils": C.G1_PANEL_HEIGHT_MILS,
        "expected_fab_order_version": expected_fab_order_version,
    }
    defaults.update(overrides)
    return defaults


def create_drill_program_payload(**overrides) -> dict:
    defaults = {
        "revision": 1,
        "min_hole_mils": 8,
        "hole_count": 1200,
    }
    defaults.update(overrides)
    return defaults


def create_laminate_lot_payload(**overrides) -> dict:
    defaults = {
        "material_code": "FR4_TG170",
        "lot_code": "LOT-1",
        "manufacture_date": DEFAULTS["MANUFACTURE_DATE"],
        "panels_total": 100,
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(fab_order_id, panel_array_id, laminate_lot_id,
                               expected_laminate_lot_version, **overrides) -> dict:
    defaults = {
        "fab_order_id": fab_order_id,
        "panel_array_id": panel_array_id,
        "laminate_lot_id": laminate_lot_id,
        "panels_allocated": C.G1_PANELS_REQUIRED,
        "expected_laminate_lot_version": expected_laminate_lot_version,
    }
    defaults.update(overrides)
    return defaults


def create_coupon_payload(spec_line_id, **overrides) -> dict:
    defaults = {
        "spec_line_id": spec_line_id,
        "panel_ref": "P01",
    }
    defaults.update(overrides)
    return defaults


def create_measurement_payload(lab_slot_booking_id, **overrides) -> dict:
    defaults = {
        "measured_ohms": 52.0,
        "lab_slot_booking_id": lab_slot_booking_id,
    }
    defaults.update(overrides)
    return defaults


def create_lab_booking_payload(coupon_id, **overrides) -> dict:
    defaults = {
        "coupon_id": coupon_id,
        "station": "MICROSECTION_A",
        "starts_at": C.WINDOW_AT_DEFAULT_CLOCK[0],
        "ends_at": C.WINDOW_AT_DEFAULT_CLOCK[1],
    }
    defaults.update(overrides)
    return defaults


def create_etest_run_payload(**overrides) -> dict:
    defaults = {
        "fixture_id": "FX-1",
        "test_voltage": 250,
    }
    defaults.update(overrides)
    return defaults


def complete_etest_run_payload(**overrides) -> dict:
    defaults = {
        "outcome": "PASS",
        "boards_tested": C.G1_QUANTITY_BOARDS,
        "boards_failed": 0,
        "opens_found": 0,
        "shorts_found": 0,
    }
    defaults.update(overrides)
    return defaults


def create_defect_payload(panel_array_id, **overrides) -> dict:
    defaults = {
        "panel_array_id": panel_array_id,
        "defect_code": "OPEN",
        "severity": "MAJOR",
        "boards_affected": 1,
        "detected_at": C.CLOCK_DEFAULT_ISO,
        "source": "AOI",
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(**overrides) -> dict:
    defaults = {
        "actual_panels_run": C.G1_PANELS_REQUIRED,
    }
    defaults.update(overrides)
    return defaults
