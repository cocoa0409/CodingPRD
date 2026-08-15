"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


def assert_surgeon(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["specialty"], str) and len(data["specialty"]) > 0
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int)


def assert_supply_item(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 1
    assert "substitute_group" in data
    assert isinstance(data["consignment_flag"], bool)
    assert isinstance(data["on_hand_quantity"], int)
    assert data["status"] in ("ACTIVE", "DISCONTINUED")
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int)


def assert_preference_card(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["surgeon_id"], str)
    assert isinstance(data["procedure_name"], str) and len(data["procedure_name"]) > 0
    assert isinstance(data["version_number"], int) and data["version_number"] >= 1
    assert data["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED", "RETIRED")
    assert isinstance(data["estimated_cost_cents"], int)
    assert isinstance(data["flagged_audit_count"], int)
    assert "rolling_line_match_pct" in data
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int)


def assert_preference_card_line(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["card_id"], str)
    assert isinstance(data["supply_item_id"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["designation"] in ("OPEN", "HOLD")
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int)


def assert_surgical_case(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["surgeon_id"], str)
    assert isinstance(data["card_id"], str)
    assert isinstance(data["pinned_card_version_number"], int)
    assert isinstance(data["procedure_name"], str)
    assert isinstance(data["scheduled_start"], str)
    assert isinstance(data["expected_duration_min"], int) and data["expected_duration_min"] >= 1
    assert isinstance(data["room"], str)
    assert "consignment_budget_cents" in data
    assert data["status"] in ("SCHEDULED", "PICKING_RELEASED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert "standard_cost_cents" in data
    assert "actual_cost_cents" in data
    assert "waste_cost_cents" in data
    assert isinstance(data["pick_exception_count"], int)
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int)


def assert_pick_list(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["case_id"], str)
    assert isinstance(data["card_id"], str)
    assert isinstance(data["card_version_number"], int)
    assert data["status"] in (
        "GENERATED", "IN_PICKING", "PICKING_EXCEPTION", "STAGED",
        "DISPATCHED", "RETURNED", "CLOSED", "CANCELLED",
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int)


def assert_pick_list_line(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["pick_list_id"], str)
    assert isinstance(data["supply_item_id"], str)
    assert data["designation"] in ("OPEN", "HOLD")
    assert isinstance(data["qty_requested"], int)
    assert isinstance(data["qty_picked"], int)
    assert isinstance(data["qty_returned_unopened"], int)
    assert isinstance(data["unit_cost_cents"], int)
    assert data["status"] in ("PENDING", "PICKED", "SHORT", "SUBSTITUTED")
    assert "substituted_item_id" in data
    assert "short_reason_code" in data
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int)


def assert_usage_record(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["case_id"], str)
    assert isinstance(data["pick_list_line_id"], str)
    assert isinstance(data["supply_item_id"], str)
    assert isinstance(data["qty_opened"], int)
    assert isinstance(data["qty_used"], int)
    assert isinstance(data["qty_wasted"], int)
    assert isinstance(data["unit_cost_cents"], int)
    assert isinstance(data["waste_charge_cents"], int)
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int)


def assert_card_accuracy_audit(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["case_id"], str)
    assert isinstance(data["card_id"], str)
    assert isinstance(data["card_version_number"], int)
    assert isinstance(data["matched_line_count"], int)
    assert isinstance(data["total_line_count"], int)
    assert isinstance(data["line_match_pct"], (int, float))
    assert isinstance(data["spend_match_pct"], (int, float))
    assert isinstance(data["waste_pct"], (int, float))
    assert isinstance(data["waste_flag"], bool)
    assert data["status"] in ("GENERATED", "UNDER_REVIEW", "DISPUTED", "ACCEPTED")
    assert "dispute_comment" in data
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int)


def assert_product_request(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["surgeon_id"], str)
    assert isinstance(data["proposed_item_name"], str)
    assert isinstance(data["proposed_sku"], str)
    assert isinstance(data["estimated_unit_cost_cents"], int)
    assert isinstance(data["rationale"], str)
    assert "substitute_group" in data
    assert "consignment_flag" in data
    assert "replaces_item_id" in data
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED")
    assert "reviewing_officer_id" in data
    assert isinstance(data["endorser_ids"], list)
    assert isinstance(data["endorsements_count"], int)
    assert "rejection_reason" in data
    assert "created_item_id" in data
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int)


def assert_consignment_count(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["supply_item_id"], str)
    assert isinstance(data["counted_qty"], int)
    assert isinstance(data["system_qty_at_count"], int)
    assert isinstance(data["variance_qty"], int)
    assert isinstance(data["variance_value_cents"], int)
    assert data["status"] in ("RECORDED", "VERIFIED")
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int)


def assert_consignment_charge(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["case_id"], str)
    assert isinstance(data["usage_record_id"], str)
    assert isinstance(data["supply_item_id"], str)
    assert isinstance(data["qty_billed"], int)
    assert isinstance(data["unit_cost_cents"], int)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("PENDING", "CAPTURED", "VOIDED")
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int)


def assert_pct(value, expected: float, msg: str = ""):
    """Assert a 2dp percentage field equals the expected value."""
    assert abs(float(value) - expected) < 0.005, (
        f"Expected {expected}, got {value} {msg}"
    )
