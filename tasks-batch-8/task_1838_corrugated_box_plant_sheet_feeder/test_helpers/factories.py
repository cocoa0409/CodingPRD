"""Payload factories — one per entity, input fields only (PRD sections 3.1-3.8)."""

DEFAULTS = {
    "ACCOUNT_NAME": "Acme Foods",
    "SHIP_TO_CITY": "Fresno",
    "DISTANCE_MILES": 120.0,
    "CREDIT_LIMIT": 50000.00,
    "GRADE_CODE": "32C",
    "LINER_COMBO": "35/23/35",
    "FLUTE": "C",
    "ECT": 32,
    "BURST": 200,
    "BASIS_WEIGHT": 90.0,
    "SHIFT_DATE": "2026-08-10",
    "SHIFT_START": 480,
    "SHIFT_END": 960,
    "WEB_WIDTH": 87.0,
    "UNIT_PRICE": 60.00,
    "EXPIRES_ON": "2026-12-31",
    "PROGRAM_NAME": "Acme RSC program",
    "REORDER_POINT": 100,
    "REPLENISHMENT_QTY": 500,
    "SHIP_DATE": "2026-08-12",
}


def create_customer_account_payload(**overrides) -> dict:
    defaults = {
        "account_name": DEFAULTS["ACCOUNT_NAME"],
        "ship_to_city": DEFAULTS["SHIP_TO_CITY"],
        "distance_miles_from_plant": DEFAULTS["DISTANCE_MILES"],
        "credit_limit_dollars": DEFAULTS["CREDIT_LIMIT"],
    }
    defaults.update(overrides)
    return defaults


def create_board_grade_payload(**overrides) -> dict:
    defaults = {
        "grade_code": DEFAULTS["GRADE_CODE"],
        "liner_combo": DEFAULTS["LINER_COMBO"],
        "flute": DEFAULTS["FLUTE"],
        "ect_rating_lbs_per_in": DEFAULTS["ECT"],
        "burst_rating_psi": DEFAULTS["BURST"],
        "basis_weight_lbs_per_msf": DEFAULTS["BASIS_WEIGHT"],
    }
    defaults.update(overrides)
    return defaults


def create_box_order_payload(customer_id: str, board_grade_id: str, **overrides) -> dict:
    """Canonical order: DIE_CUT INTERNAL 29x36 in, qty 2000, min_ect 32,
    inks [BLACK, RED]."""
    defaults = {
        "customer_id": customer_id,
        "board_grade_id": board_grade_id,
        "routing_type": "DIE_CUT",
        "board_source": "INTERNAL",
        "quantity": 2000,
        "blank_width_in": 29.0,
        "blank_length_in": 36.0,
        "min_ect_required": 32,
        "ink_colors": ["BLACK", "RED"],
    }
    defaults.update(overrides)
    return defaults


def create_price_quote_payload(expected_order_version: int, **overrides) -> dict:
    defaults = {
        "unit_price_per_msf": DEFAULTS["UNIT_PRICE"],
        "expires_on": DEFAULTS["EXPIRES_ON"],
        "expected_order_version": expected_order_version,
    }
    defaults.update(overrides)
    return defaults


def create_work_shift_payload(**overrides) -> dict:
    defaults = {
        "machine_code": "CORRUGATOR",
        "shift_date": DEFAULTS["SHIFT_DATE"],
        "start_minute": DEFAULTS["SHIFT_START"],
        "end_minute": DEFAULTS["SHIFT_END"],
    }
    defaults.update(overrides)
    return defaults


def create_corrugator_run_payload(
    work_shift_id: str, board_grade_id: str, **overrides
) -> dict:
    defaults = {
        "work_shift_id": work_shift_id,
        "board_grade_id": board_grade_id,
        "start_minute": DEFAULTS["SHIFT_START"],
        "end_minute": 720,
        "web_width_in": DEFAULTS["WEB_WIDTH"],
    }
    defaults.update(overrides)
    return defaults


def create_attach_order_payload(box_order_id: str, outs: int) -> dict:
    return {"box_order_id": box_order_id, "outs": outs}


def create_converting_booking_payload(
    box_order_id: str, work_shift_id: str, **overrides
) -> dict:
    defaults = {
        "box_order_id": box_order_id,
        "work_shift_id": work_shift_id,
        "start_minute": DEFAULTS["SHIFT_START"],
        "end_minute": 600,
    }
    defaults.update(overrides)
    return defaults


def create_inventory_program_payload(
    customer_id: str, board_grade_id: str, **overrides
) -> dict:
    defaults = {
        "customer_id": customer_id,
        "board_grade_id": board_grade_id,
        "program_name": DEFAULTS["PROGRAM_NAME"],
        "routing_type": "SLOTTED",
        "blank_width_in": 24.0,
        "blank_length_in": 20.0,
        "reorder_point": DEFAULTS["REORDER_POINT"],
        "replenishment_qty": DEFAULTS["REPLENISHMENT_QTY"],
    }
    defaults.update(overrides)
    return defaults


def create_receipt_payload(qty: int) -> dict:
    return {"qty": qty}


def create_release_order_payload(qty: int, **overrides) -> dict:
    defaults = {"qty": qty, "requested_ship_date": DEFAULTS["SHIP_DATE"]}
    defaults.update(overrides)
    return defaults


def create_quality_claim_payload(box_order_id: str, **overrides) -> dict:
    defaults = {
        "box_order_id": box_order_id,
        "claim_type": "TRANSIT_DAMAGE",
        "defective_qty_claimed": 500,
    }
    defaults.update(overrides)
    return defaults


def create_resolve_claim_payload(**overrides) -> dict:
    defaults = {"outcome": "CREDIT", "defective_qty_verified": 400}
    defaults.update(overrides)
    return defaults


def create_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
