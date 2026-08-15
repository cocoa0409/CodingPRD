"""Entity assertions and domain invariant checkers.

Assertions are limited to fields the PRD guarantees on responses: the common
fields (id / created_at / updated_at / version), the status enum, and fields
the PRD prose explicitly records on the entity.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, context: str):
    assert is_valid_uuid(data.get("id", "")), f"{context}: id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{context}: created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{context}: updated_at must be ISO 8601"
    assert isinstance(
        data.get("version"), int
    ), f"{context}: version must be an integer"
    assert data["version"] >= 1, f"{context}: version starts at 1"


def assert_customer(data: dict):
    _assert_common(data, "Customer")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["brand_code"], str) and data["brand_code"]


def assert_color_standard(data: dict):
    _assert_common(data, "ColorStandard")
    assert data["status"] in ("DRAFT", "PENDING_BRAND", "ACTIVE", "SUPERSEDED")
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["ink_slot"], str) and data["ink_slot"]
    assert isinstance(data["tolerance_delta_e_milli"], int)
    assert data["substrate_class"] in ("COATED", "UNCOATED")


def assert_job(data: dict):
    _assert_common(data, "Job")
    assert data["status"] in (
        "QUOTED",
        "ENGINEERING",
        "PRESS_READY",
        "IN_PRODUCTION",
        "FINISHING",
        "FINISHED",
        "COMPLETE",
        "CANCELLED",
    )
    assert data["route_type"] in ("DIGITAL", "OFFSET")
    assert isinstance(data["quantity_ordered"], int) and data["quantity_ordered"] >= 1
    assert isinstance(data["provisional_subtotal_cents"], int)
    assert isinstance(data["provisional_total_cents"], int)
    for counter in (
        "reserved_sheets",
        "sheets_consumed_actual",
        "good_sheets_actual",
        "allocated_cartons",
    ):
        assert isinstance(
            data.get(counter), int
        ), f"Job: {counter} must be an integer counter"
        assert data[counter] >= 0, f"Job: {counter} must never go negative"


def assert_design_revision(data: dict):
    _assert_common(data, "DesignRevision")
    assert data["status"] in ("DRAFT", "SAMPLE_MADE", "BRAND_APPROVED", "SUPERSEDED")
    assert isinstance(data["job_id"], str)
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 1


def assert_imposition_plan(data: dict):
    _assert_common(data, "ImpositionPlan")
    assert data["status"] in ("DRAFT", "LOCKED", "SUPERSEDED")
    assert isinstance(data["job_id"], str)
    assert isinstance(data["design_revision_id"], str)
    assert isinstance(data["ups"], int)
    assert data["orientation"] in ("NORMAL", "ROTATED")
    assert isinstance(data["net_sheets"], int)
    assert isinstance(data["gross_sheets"], int)
    assert isinstance(data["layout_yield_milli_pct"], int)
    assert isinstance(data["realized_sheets_printed"], int)
    assert isinstance(data["realized_good_sheets"], int)
    # realized_waste_milli_pct stays null until a press booking completes
    assert data.get("realized_waste_milli_pct") is None or isinstance(
        data["realized_waste_milli_pct"], int
    )


def assert_press_approval(data: dict):
    _assert_common(data, "PressApproval")
    assert data["status"] in ("SUBMITTED", "APPROVED", "REJECTED", "INVALIDATED")
    assert isinstance(data["job_id"], str)
    assert isinstance(data["color_standard_id"], str)
    assert isinstance(data["ink_slot"], str)
    assert isinstance(data["measured_delta_e_milli"], int)
    assert isinstance(data["submission_index"], int) and data["submission_index"] >= 1


def assert_press(data: dict):
    _assert_common(data, "Press")
    assert data["status"] in ("ACTIVE", "DOWN")
    assert data["press_type"] in ("DIGITAL", "OFFSET")
    assert isinstance(data["press_code"], str) and data["press_code"]
    assert isinstance(data["max_sheets_per_booking"], int)


def assert_press_booking(data: dict):
    _assert_common(data, "PressBooking")
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")
    assert isinstance(data["job_id"], str)
    assert isinstance(data["press_id"], str)
    assert isinstance(data["planned_sheets"], int)


def assert_finishing_line(data: dict):
    _assert_common(data, "FinishingLine")
    assert data["status"] in ("ACTIVE", "DOWN")
    assert isinstance(data["line_code"], str) and data["line_code"]
    assert isinstance(data["supported_ops"], list)
    for op in data["supported_ops"]:
        assert op in ("COAT", "FOIL", "EMBOSS")
    assert isinstance(data["setup_buffer_minutes"], int)


def assert_finishing_booking(data: dict):
    _assert_common(data, "FinishingBooking")
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")
    assert isinstance(data["job_id"], str)
    assert isinstance(data["line_id"], str)
    assert data["operation"] in ("COAT", "FOIL", "EMBOSS")


def assert_board_stock(data: dict):
    _assert_common(data, "BoardStock")
    assert isinstance(data["substrate_code"], str) and data["substrate_code"]
    assert isinstance(data["caliper_pts"], int)
    assert isinstance(data["unit_cost_cents"], int)
    for field in ("received_sheets", "reserved_sheets", "consumed_sheets"):
        assert isinstance(data.get(field), int), f"BoardStock: {field} must be int"
    assert_inv_sheets(data)


def assert_kit_order(data: dict):
    _assert_common(data, "KitOrder")
    assert data["status"] in ("PLANNED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert isinstance(data["job_id"], str)
    assert isinstance(data["kit_name"], str)
    assert isinstance(data["components"], list) and len(data["components"]) >= 1
    assert isinstance(data["kits_planned"], int) and data["kits_planned"] >= 1
    assert isinstance(data["consumed_per_kit"], int)
    assert isinstance(data["allocated_cartons"], int)
    assert isinstance(data["kits_completed"], int)
    assert isinstance(data["consumed_cartons"], int)


def assert_retail_audit(data: dict):
    _assert_common(data, "RetailReadyAudit")
    assert data["status"] in ("DRAFT", "SUBMITTED", "CERTIFIED", "REJECTED")
    assert data["verdict"] in ("COMPLIANT", "NON_COMPLIANT")
    assert data["orientation"] in ("LENGTHWISE", "WIDTHWISE")
    assert isinstance(data["job_id"], str)
    for field in (
        "case_w_cin",
        "case_h_cin",
        "case_d_cin",
        "case_weight_g",
        "cases_per_layer",
        "layers",
        "case_count",
    ):
        assert isinstance(
            data.get(field), int
        ), f"RetailReadyAudit: {field} must be int"


def assert_invoice(data: dict):
    _assert_common(data, "Invoice")
    assert data["status"] in ("DRAFT", "FINALIZED", "SETTLED", "VOIDED")
    assert data["variant"] in ("PROVISIONAL", "FINAL")
    assert isinstance(data["job_id"], str)
    assert isinstance(data["lines"], list)
    for line in data["lines"]:
        assert line["code"] in (
            "PRINT",
            "BOARD",
            "FINISH_COAT",
            "FINISH_FOIL",
            "FINISH_EMBOSS",
            "KITTING",
            "MAKE_READY",
        )
        assert isinstance(line["amount_cents"], int)
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["make_ready_waived"], bool)
    assert isinstance(data["make_ready_line_cents"], int)
    assert isinstance(data["minimum_recovery_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["total_cents"] == data["subtotal_cents"] + data["minimum_recovery_cents"]


def assert_inv_sheets(stock: dict):
    """INV-SHEETS: received == available + reserved + consumed, available >= 0."""
    received = stock["received_sheets"]
    reserved = stock["reserved_sheets"]
    consumed = stock["consumed_sheets"]
    available = stock["available_sheets"]
    assert (
        received == available + reserved + consumed
    ), f"INV-SHEETS violated: received {received} != {available}+{reserved}+{consumed}"
    assert available >= 0, "available_sheets must never go negative"


def assert_inv_cartons(job: dict):
    """INV-CARTONS: good_cartons_actual == allocated_cartons + available_cartons."""
    good = job["good_cartons_actual"]
    allocated = job["allocated_cartons"]
    available = job["available_cartons"]
    assert (
        good == allocated + available
    ), f"INV-CARTONS violated: good {good} != allocated {allocated} + available {available}"
