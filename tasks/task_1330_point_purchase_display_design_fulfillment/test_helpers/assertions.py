"""Entity assertions and domain invariant checkers (PRD §2.4, §3).

Every primary resource carries id/created_at/updated_at/version; the program
recap is the one exception and carries only id/created_at (PRD §2.4).
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), \
        f"version must be an integer, got {data.get('version')!r}"


def assert_client(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["contact_email"], str) and len(data["contact_email"]) > 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_program(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("client_id", ""))
    assert isinstance(data["retailer_name"], str) and len(data["retailer_name"]) > 0
    assert isinstance(data["program_name"], str) and len(data["program_name"]) > 0
    assert isinstance(data["store_count"], int) and data["store_count"] >= 1
    assert isinstance(data["program_revenue_cents"], int) \
        and data["program_revenue_cents"] >= 0
    assert data["status"] in (
        "DRAFT", "DESIGN", "PRODUCTION", "FULFILLMENT", "CLOSED", "CANCELLED")


def assert_compliance_rule(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert data["dimension"] in (
        "MAX_WIDTH_IN", "MAX_HEIGHT_IN", "MAX_DEPTH_IN",
        "ALLOWED_MATERIAL", "MAX_WEIGHT_LB")
    assert isinstance(data["limit_value"], str)
    assert isinstance(data["active"], bool)


def assert_design(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data["design_code"], str) and len(data["design_code"]) > 0
    for dim in ("width_in", "height_in", "depth_in", "weight_lb"):
        assert isinstance(data[dim], (int, float)) and data[dim] > 0, \
            f"{dim} must be a positive number, got {data.get(dim)!r}"
    assert isinstance(data["material"], str) and len(data["material"]) > 0
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 1
    assert data["compliance_result"] in ("PASS", "FAIL")
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "COMPLIANCE_REVIEW", "APPROVED", "REJECTED", "LOCKED")


def assert_production_run(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert is_valid_uuid(data.get("design_id", ""))
    assert isinstance(data["overage_pct"], (int, float)) and data["overage_pct"] >= 0
    assert data["status"] in ("PLANNED", "AUTHORIZED", "PRODUCED", "CANCELLED")
    if data["status"] in ("AUTHORIZED", "PRODUCED"):
        # Costing fields are fixed at authorization time (PRD §3.3).
        assert isinstance(data["production_quantity"], int) \
            and data["production_quantity"] >= 1
        assert isinstance(data["unit_cost_cents"], int) \
            and data["unit_cost_cents"] > 0
        assert isinstance(data["total_cost_cents"], int)
        assert data["total_cost_cents"] == \
            data["production_quantity"] * data["unit_cost_cents"]


def assert_store(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data["store_number"], str) and len(data["store_number"]) > 0
    assert isinstance(data["address"], str) and len(data["address"]) > 0


def assert_kit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("production_run_id", ""))
    assert is_valid_uuid(data.get("store_id", ""))
    assert data["status"] in ("PENDING", "KITTED", "SHIPPED", "DELIVERED", "DAMAGED")


def assert_shipment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("kit_id", ""))
    assert is_iso8601_timestamp(data.get("ship_window_start", ""))
    assert is_iso8601_timestamp(data.get("ship_window_end", ""))
    assert data["status"] in (
        "SCHEDULED", "APPOINTMENT_SET", "SHIPPED", "DELIVERED", "FAILED")
    for optional_ts in ("appointment_at", "shipped_at", "delivered_at"):
        if data.get(optional_ts) is not None:
            assert is_iso8601_timestamp(data[optional_ts]), \
                f"{optional_ts} must be ISO 8601 when present, got {data[optional_ts]!r}"


def assert_damage_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("kit_id", ""))
    assert isinstance(data["reported_by"], str) and len(data["reported_by"]) > 0
    assert isinstance(data["replacement_quantity"], int) \
        and data["replacement_quantity"] >= 1
    assert data["status"] in ("REPORTED", "APPROVED", "REJECTED", "FULFILLED")
    if data["status"] in ("APPROVED", "FULFILLED"):
        # Replacement cost is computed on approval (PRD §3.5).
        assert isinstance(data["replacement_cost_cents"], int) \
            and data["replacement_cost_cents"] >= 0


def assert_field_service_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("store_id", ""))
    assert is_valid_uuid(data.get("program_id", ""))
    assert data["issue_type"] in (
        "ASSEMBLY_HELP", "MISSING_PARTS", "INSTRUCTION_CLARIFICATION")
    assert data["status"] in ("OPEN", "DISPATCHED", "RESOLVED")


def assert_program_recap(data: dict):
    """Recap is minted once at close and immutable: only id + created_at as
    system fields; updated_at and version are absent (PRD §2.4, §3.7)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert "updated_at" not in data, "recap must not carry updated_at"
    assert "version" not in data, "recap must not carry version"
    assert is_valid_uuid(data.get("program_id", ""))
    for total in ("total_produced", "total_delivered", "total_damaged",
                  "total_cost_cents"):
        assert isinstance(data[total], int) and data[total] >= 0, \
            f"{total} must be a non-negative integer, got {data.get(total)!r}"
    for roi in ("roi_pct_provisional", "roi_pct_final"):
        assert isinstance(data[roi], (int, float)), \
            f"{roi} must be numeric, got {data.get(roi)!r}"
    assert is_iso8601_timestamp(data.get("generated_at", "")), \
        f"generated_at must be ISO 8601, got {data.get('generated_at')!r}"
