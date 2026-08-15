"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be int"


def assert_job(data: dict):
    _assert_common_fields(data, "Job")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contract_value_cents"], int)
    assert data["billing_basis"] in ["WEIGHT", "COUNT"]
    assert isinstance(data["requires_aisc_hold"], bool)
    assert data["status"] in [
        "ESTIMATING", "AWARDED", "FABRICATING", "ERECTING", "COMPLETE",
    ]
    # The nine computed aggregates of PRD section 3.1
    assert isinstance(data["total_weight_lbs"], int)
    assert isinstance(data["erected_weight_lbs"], int)
    assert isinstance(data["pct_complete"], (int, float))
    assert isinstance(data["billed_to_date_cents"], int)
    assert isinstance(data["retainage_held_cents"], int)
    assert isinstance(data["pending_backcharge_cents"], int)
    assert isinstance(data["settled_backcharge_cents"], int)
    assert isinstance(data["retainage_releasable_cents"], int)


def assert_shop_drawing(data: dict):
    _assert_common_fields(data, "ShopDrawing")
    assert isinstance(data["job_id"], str) and data["job_id"]
    assert isinstance(data["drawing_number"], str) and data["drawing_number"]
    assert isinstance(data["revision"], int)
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED",
    ]
    assert "supersedes_id" in data, "supersedes_id must be present"
    assert data["supersedes_id"] is None or isinstance(data["supersedes_id"], str)
    if data["status"] != "DRAFT":
        assert isinstance(data.get("submitted_by_user_id"), str), \
            "submitted_by_user_id must be captured once submitted"
    if data["status"] in ["APPROVED", "REJECTED", "SUPERSEDED"]:
        assert isinstance(data.get("decided_by_user_id"), str), \
            "decided_by_user_id must be captured once decided"


def assert_mill_order(data: dict):
    _assert_common_fields(data, "MillOrder")
    assert isinstance(data["job_id"], str) and data["job_id"]
    assert data["material_grade"] in ["A36", "A572", "A992"]
    assert isinstance(data["ordered_weight_lbs"], int)
    assert data["ordered_weight_lbs"] > 0
    assert isinstance(data["unit_price_per_cwt_cents"], int)
    assert data["unit_price_per_cwt_cents"] > 0
    assert data["billing_mode"] in ["NOMINAL", "ACTUAL"]
    assert data["status"] in ["PLACED", "RECEIVED"]
    if data["status"] == "RECEIVED":
        assert isinstance(data["received_weight_lbs"], int)
        assert isinstance(data["invoice_amount_cents"], int)


def assert_erection_sequence(data: dict):
    _assert_common_fields(data, "ErectionSequence")
    assert isinstance(data["job_id"], str) and data["job_id"]
    assert isinstance(data["seq_number"], int)
    assert data["status"] in ["PLANNED", "RELEASED", "ERECTED"]


def assert_piece(data: dict):
    _assert_common_fields(data, "Piece")
    assert isinstance(data["job_id"], str) and data["job_id"]
    assert isinstance(data["piece_mark"], str) and data["piece_mark"]
    assert isinstance(data["weight_lbs"], int)
    assert data["weight_lbs"] > 0
    assert isinstance(data["drawing_id"], str) and data["drawing_id"]
    assert isinstance(data["sequence_id"], str) and data["sequence_id"]
    assert "load_id" in data, "load_id must be present"
    assert data["load_id"] is None or isinstance(data["load_id"], str)
    assert isinstance(data["stale_revision"], bool)
    assert data["status"] in [
        "DETAILED", "IN_SHOP", "AWAITING_INSPECTION", "REWORK", "INSPECTED",
        "READY_TO_SHIP", "SHIPPED", "ERECTED",
    ]


def assert_welder(data: dict):
    _assert_common_fields(data, "Welder")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["qual_process"] in ["SMAW", "FCAW", "GMAW"]
    assert isinstance(data["qual_expires_on"], str) and data["qual_expires_on"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_weld(data: dict):
    _assert_common_fields(data, "Weld")
    assert isinstance(data["piece_id"], str) and data["piece_id"]
    assert isinstance(data["welder_id"], str) and data["welder_id"]
    assert data["process"] in ["SMAW", "FCAW", "GMAW"]
    assert isinstance(data["weld_date"], str) and data["weld_date"]
    assert isinstance(data["window_start"], str) and data["window_start"]
    assert isinstance(data["window_end"], str) and data["window_end"]
    assert isinstance(data["repair_count"], int)
    assert data["status"] in [
        "WELDED", "VISUAL_PASSED", "NDT_PASSED", "VISUAL_REJECTED",
        "NDT_REJECTED",
    ]


def assert_inspection(data: dict):
    _assert_common_fields(data, "Inspection")
    assert isinstance(data["job_id"], str) and data["job_id"]
    assert data["kind"] in ["FINAL_PIECE", "WELD_VISUAL", "WELD_NDT", "AISC_AUDIT"]
    assert data["status"] in ["SCHEDULED", "PASSED", "FAILED", "VOIDED"]
    if data["status"] != "SCHEDULED":
        assert isinstance(data.get("inspector_user_id"), str), \
            "inspector_user_id must be captured once submitted"


def assert_shipping_load(data: dict):
    _assert_common_fields(data, "ShippingLoad")
    assert isinstance(data["job_id"], str) and data["job_id"]
    assert isinstance(data["load_number"], str) and data["load_number"]
    assert isinstance(data["laydown_slot"], str) and data["laydown_slot"]
    assert isinstance(data["delivery_date"], str) and data["delivery_date"]
    assert isinstance(data["trailer_capacity_lbs"], int)
    assert data["trailer_capacity_lbs"] > 0
    assert isinstance(data["total_weight_lbs"], int)
    assert data["status"] in ["STAGING", "LOADING", "SHIPPED"]


def assert_field_fix(data: dict):
    _assert_common_fields(data, "FieldFix")
    assert isinstance(data["job_id"], str) and data["job_id"]
    assert isinstance(data["piece_id"], str) and data["piece_id"]
    assert isinstance(data["description"], str)
    assert isinstance(data["repair_lines"], list) and len(data["repair_lines"]) > 0
    assert data["status"] in ["PRICED", "APPROVED", "RESOLVED"]
    if data["status"] != "PRICED":
        assert isinstance(data["amount_cents"], int), \
            "amount_cents must be priced once approved"


def assert_backcharge(data: dict):
    _assert_common_fields(data, "Backcharge")
    assert isinstance(data["job_id"], str) and data["job_id"]
    assert isinstance(data["field_fix_id"], str) and data["field_fix_id"]
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ["PENDING", "ACCEPTED", "DISPUTED", "SETTLED"]
    if data["status"] == "SETTLED":
        assert isinstance(data.get("settled_amount_cents"), int), \
            "settled_amount_cents must be recorded at settle"


def assert_progress_billing(data: dict):
    _assert_common_fields(data, "ProgressBilling")
    assert isinstance(data["job_id"], str) and data["job_id"]
    assert isinstance(data["period_label"], str) and data["period_label"]
    assert isinstance(data["pct_complete_snapshot"], (int, float))
    assert isinstance(data["earned_cum_cents"], int)
    assert isinstance(data["retainage_cum_cents"], int)
    assert isinstance(data["retainage_booked_cents"], int)
    assert isinstance(data["net_due_cents"], int)
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "PAID", "VOIDED"]
