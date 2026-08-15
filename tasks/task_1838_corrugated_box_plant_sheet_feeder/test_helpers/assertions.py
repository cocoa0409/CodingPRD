"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the structural contract of a single resource
as described in PRD sections 2.4, 2.8 and 3.x.
"""
import pytest
from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

# Tight comparison tolerances: pinned precision is 2dp for money and 4dp for
# areas/MSF quantities (PRD 2.5); these tolerances catch a rounding error at
# the pinned digit while ignoring float representation noise.
MONEY_TOL = 0.001
MSF_TOL = 0.00001

BOX_ORDER_STATUSES = [
    "DRAFT", "QUOTED", "ACCEPTED", "SCHEDULED", "AWAITING_CONVERTING",
    "DIE_CUT_QUEUED", "SLOTTED_QUEUED", "CONVERTING", "PRODUCED",
    "INVOICED", "CANCELLED",
]


def assert_common_fields(data: dict):
    """PRD 2.4: every entity carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC: {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC: {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer: {data.get('version')!r}"
    )


def assert_customer_account(data: dict):
    assert_common_fields(data)
    assert isinstance(data["account_name"], str) and data["account_name"]
    assert isinstance(data["ship_to_city"], str) and data["ship_to_city"]
    assert data["distance_miles_from_plant"] > 0
    assert data["credit_limit_dollars"] >= 0
    assert data["credit_exposure_dollars"] >= 0
    assert_cost_precision(float(data["credit_exposure_dollars"]))


def assert_board_grade(data: dict):
    assert_common_fields(data)
    assert isinstance(data["grade_code"], str) and data["grade_code"]
    assert isinstance(data["liner_combo"], str) and data["liner_combo"]
    assert data["flute"] in ["B", "C", "E", "BC"]
    assert data["ect_rating_lbs_per_in"] > 0
    assert data["burst_rating_psi"] > 0
    assert data["basis_weight_lbs_per_msf"] > 0
    assert data["status"] in ["ACTIVE", "DISCONTINUED"]


def assert_work_shift(data: dict):
    assert_common_fields(data)
    assert data["machine_code"] in ["CORRUGATOR", "DIE_CUTTER", "FFG"]
    assert isinstance(data["shift_date"], str) and data["shift_date"]
    assert data["start_minute"] >= 0
    assert data["end_minute"] > data["start_minute"]
    assert data["capacity_minutes"] == data["end_minute"] - data["start_minute"]
    assert data["available_minutes"] == data["capacity_minutes"] - data["scheduled_minutes"]
    assert data["status"] in ["OPEN", "CANCELLED"]


def assert_corrugator_run(data: dict):
    assert_common_fields(data)
    assert data["end_minute"] > data["start_minute"]
    assert data["web_width_in"] > 0
    assert data["consumed_width_in"] >= 0
    assert data["trim_waste_in"] == pytest.approx(
        data["web_width_in"] - data["consumed_width_in"], abs=MSF_TOL
    )
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED"]


def assert_box_order(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("board_grade_id", ""))
    assert data["routing_type"] in ["DIE_CUT", "SLOTTED"]
    assert data["board_source"] in ["INTERNAL", "SHEET_FEEDER"]
    assert data["quantity"] > 0
    assert data["blank_width_in"] > 0
    assert data["blank_length_in"] > 0
    assert data["min_ect_required"] >= 0
    assert isinstance(data["ink_colors"], list)
    assert data["color_count"] == len(data["ink_colors"])
    assert data["area_sqft_per_box"] > 0
    assert data["status"] in BOX_ORDER_STATUSES


def assert_price_quote(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert data["unit_price_per_msf"] > 0
    assert isinstance(data["expires_on"], str) and data["expires_on"]
    assert data["billable_msf"] > 0
    assert data["freight_tier"] in ["LOCAL", "REGIONAL", "NATIONAL"]
    assert data["merchandise_total_dollars"] > 0
    assert data["discount_pct"] in (0.00, 0.02, 0.04)
    assert data["discount_dollars"] >= 0
    assert data["freight_charge_dollars"] >= 0
    assert data["quote_total_dollars"] == pytest.approx(
        data["merchandise_total_dollars"]
        - data["discount_dollars"]
        + data["freight_charge_dollars"],
        abs=MONEY_TOL,
    )
    assert data["status"] in ["OPEN", "ACCEPTED", "SUPERSEDED", "EXPIRED", "INVOICED"]


def assert_converting_booking(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("work_shift_id", ""))
    assert is_valid_uuid(data.get("box_order_id", ""))
    assert data["end_minute"] > data["start_minute"]
    assert isinstance(data["ink_colors"], list)
    assert data["status"] in ["QUEUED", "RUNNING", "COMPLETED", "CANCELLED"]


def assert_inventory_program(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("board_grade_id", ""))
    assert isinstance(data["program_name"], str) and data["program_name"]
    assert data["routing_type"] in ["DIE_CUT", "SLOTTED"]
    assert data["blank_width_in"] > 0
    assert data["blank_length_in"] > 0
    assert data["reorder_point"] >= 0
    assert data["replenishment_qty"] > 0
    assert data["on_hand_qty"] >= 0
    assert data["committed_qty"] >= 0
    assert data["available_qty"] == data["on_hand_qty"] - data["committed_qty"]
    assert data["status"] in ["ACTIVE", "SUSPENDED", "REPLENISHMENT_NEEDED"]


def assert_release_order(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert data["qty"] > 0
    assert isinstance(data["requested_ship_date"], str) and data["requested_ship_date"]
    assert data["status"] in ["PENDING", "APPROVED", "SHIPPED", "CANCELLED"]


def assert_quality_claim(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("box_order_id", ""))
    assert data["claim_type"] in ["TRANSIT_DAMAGE", "BOARD_WARP"]
    assert data["defective_qty_claimed"] > 0
    assert data["per_box_price_dollars"] > 0
    assert data["provisional_credit_dollars"] >= 0
    assert isinstance(data["filed_by_user_id"], str) and data["filed_by_user_id"]
    assert data["status"] in [
        "OPEN", "UNDER_REVIEW", "RESOLVED_CREDIT", "RESOLVED_REJECTED",
    ]


def assert_shift_minutes_invariant(shift: dict):
    """PRD 3.4: capacity_minutes == scheduled_minutes + available_minutes."""
    assert shift["capacity_minutes"] == shift["scheduled_minutes"] + shift["available_minutes"], (
        f"Shift minutes not conserved: capacity {shift['capacity_minutes']} != "
        f"scheduled {shift['scheduled_minutes']} + available {shift['available_minutes']}"
    )


def assert_program_stock_invariant(program: dict):
    """PRD 3.7: on_hand_qty == committed_qty + available_qty."""
    assert program["on_hand_qty"] == program["committed_qty"] + program["available_qty"], (
        f"Program stock not conserved: on_hand {program['on_hand_qty']} != "
        f"committed {program['committed_qty']} + available {program['available_qty']}"
    )


def assert_money(value, expected):
    """2dp money equality at the pinned precision (PRD 2.5)."""
    assert float(value) == pytest.approx(expected, abs=MONEY_TOL), (
        f"Expected money value {expected}, got {value}"
    )


def assert_msf(value, expected):
    """4dp area/MSF equality at the pinned precision (PRD 2.5)."""
    assert float(value) == pytest.approx(expected, abs=MSF_TOL), (
        f"Expected MSF/area value {expected}, got {value}"
    )
