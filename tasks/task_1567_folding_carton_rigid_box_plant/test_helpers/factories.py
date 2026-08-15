"""Payload factories — one per entity, input fields only.

Defaults follow the shared fixture legend: blanks 900x600 cin with rotation
allowed, substrate SBS18 at 18pt, press sheet 4800x3600 with gutter 30,
edge margin 60, gripper 90, ink slot BRAND_RED with tolerance 200 milli.
"""
from . import constants as C


def create_customer_payload(**overrides) -> dict:
    defaults = {"name": "Acme Brand", "brand_code": "ACM"}
    defaults.update(overrides)
    return defaults


def create_color_standard_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "ink_slot": C.FIXTURE_INK_SLOT,
        "l_target": 5300,
        "a_target": 6800,
        "b_target": 3200,
        "tolerance_delta_e_milli": C.FIXTURE_TOLERANCE_DELTA_E_MILLI,
        "substrate_class": "COATED",
    }
    defaults.update(overrides)
    return defaults


def create_job_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "quantity_ordered": 3000,
        "blank_w_cin": C.FIXTURE_BLANK_W_CIN,
        "blank_h_cin": C.FIXTURE_BLANK_H_CIN,
        "grain_rotation_allowed": True,
        "substrate_code": C.FIXTURE_SUBSTRATE_CODE,
        "caliper_pts": C.FIXTURE_CALIPER_PTS,
        "finish_coat": True,
        "finish_foil": False,
        "finish_emboss": False,
        "required_ink_slots": [C.FIXTURE_INK_SLOT],
        "requires_retail_compliance": False,
    }
    defaults.update(overrides)
    return defaults


def create_design_revision_payload(job_id, expected_job_version, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "expected_job_version": expected_job_version,
        "cad_ref": "CAD-1",
        "blank_w_cin": C.FIXTURE_BLANK_W_CIN,
        "blank_h_cin": C.FIXTURE_BLANK_H_CIN,
        "grain_rotation_allowed": True,
    }
    defaults.update(overrides)
    return defaults


def create_imposition_plan_payload(job_id, design_revision_id, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "design_revision_id": design_revision_id,
        "sheet_w_cin": C.FIXTURE_SHEET_W_CIN,
        "sheet_h_cin": C.FIXTURE_SHEET_H_CIN,
        "gutter_cin": C.FIXTURE_GUTTER_CIN,
        "edge_margin_cin": C.FIXTURE_EDGE_MARGIN_CIN,
        "gripper_cin": C.FIXTURE_GRIPPER_CIN,
    }
    defaults.update(overrides)
    return defaults


def create_press_approval_payload(job_id, color_standard_id, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "color_standard_id": color_standard_id,
        "ink_slot": C.FIXTURE_INK_SLOT,
        "measured_delta_e_milli": 100,
    }
    defaults.update(overrides)
    return defaults


def create_press_payload(**overrides) -> dict:
    defaults = {
        "press_code": "P-OFF-1",
        "press_type": "OFFSET",
        "max_sheet_w_cin": 5000,
        "max_sheet_h_cin": 4000,
        "max_sheets_per_booking": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_press_booking_payload(job_id, press_id, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "press_id": press_id,
        "planned_sheets": 130,
        "start_utc": C.WINDOW_PRESS_START,
        "end_utc": C.WINDOW_PRESS_END,
    }
    defaults.update(overrides)
    return defaults


def create_finishing_line_payload(**overrides) -> dict:
    defaults = {
        "line_code": "L-C1",
        "supported_ops": ["COAT", "FOIL", "EMBOSS"],
        "setup_buffer_minutes": 0,
    }
    defaults.update(overrides)
    return defaults


def create_finishing_booking_payload(job_id, line_id, operation, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "line_id": line_id,
        "operation": operation,
        "start_utc": C.WINDOW_FINISH_START,
        "end_utc": C.WINDOW_FINISH_END,
    }
    defaults.update(overrides)
    return defaults


def create_board_stock_payload(**overrides) -> dict:
    defaults = {
        "substrate_code": C.FIXTURE_SUBSTRATE_CODE,
        "caliper_pts": C.FIXTURE_CALIPER_PTS,
        "sheet_w_cin": C.FIXTURE_SHEET_W_CIN,
        "sheet_h_cin": C.FIXTURE_SHEET_H_CIN,
        "unit_cost_cents": C.FIXTURE_STOCK_UNIT_COST_CENTS,
        "received_sheets": C.FIXTURE_STOCK_SHEETS,
    }
    defaults.update(overrides)
    return defaults


def create_kit_order_payload(job_id, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "kit_name": "Club pack",
        "components": [{"description": "carton", "units_per_kit": 3}],
        "kits_planned": 10,
    }
    defaults.update(overrides)
    return defaults


def create_retail_audit_payload(job_id, **overrides) -> dict:
    """Defaults sit exactly on the compliant pallet envelope used in the PRD:
    footprint 8*1524 == 12192, height 6*2540 == 15240, count 48 == 8*6,
    weight 672000 <= 680389."""
    defaults = {
        "job_id": job_id,
        "retailer_code": "CLUB-A",
        "orientation": "LENGTHWISE",
        "case_w_cin": 1524,
        "case_h_cin": 2540,
        "case_d_cin": 9000,
        "case_weight_g": 14000,
        "cases_per_layer": 8,
        "layers": 6,
        "case_count": 48,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(job_id, **overrides) -> dict:
    defaults = {"job_id": job_id}
    defaults.update(overrides)
    return defaults
