"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §2.9)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def assert_common_fields(data: dict):
    """The standard quartet of system-managed fields from PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), \
        f"version must be an integer, got {data.get('version')!r}"


def _parse_instant(value) -> datetime:
    """Parse an ISO 8601 timestamp into an aware datetime for instant compare."""
    assert isinstance(value, str), f"expected timestamp string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def assert_timestamp_equals(actual, expected_iso: str):
    """Two timestamps denote the same instant (clock-driven fields, PRD §2.5)."""
    assert _parse_instant(actual) == _parse_instant(expected_iso), \
        f"expected instant {expected_iso}, got {actual}"


def assert_error_envelope(response):
    """PRD §2.2 error envelope: response_type error, data.error_id + message."""
    body = response.json()
    assert body.get("response_type") == "error", \
        f"error envelope must carry response_type 'error', got {body.get('response_type')!r}"
    data = body.get("data") or {}
    assert isinstance(data.get("error_id"), str) and data["error_id"], \
        "error envelope must carry data.error_id"
    assert isinstance(data.get("message"), str) and data["message"], \
        "error envelope must carry a human-readable data.message"
    meta = body.get("meta") or {}
    assert isinstance(meta.get("api_request_id"), str), \
        "error envelope meta must carry api_request_id"
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", "")), \
        "error envelope meta must carry api_request_timestamp"
    return data


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

def assert_customer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["customer_kind"] in ("INDIVIDUAL", "FLIGHT_SCHOOL", "FLEET_OPERATOR")


def assert_aircraft(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["tail_number"], str) and data["tail_number"]
    assert isinstance(data["make_model"], str) and data["make_model"]
    assert isinstance(data["baseline_empty_weight_lb"], (int, float))
    assert isinstance(data["baseline_arm_in"], (int, float))
    assert isinstance(data["baseline_moment_lb_in"], (int, float))
    assert isinstance(data["cg_min_arm_in"], (int, float))
    assert isinstance(data["cg_max_arm_in"], (int, float))
    assert data["status"] in ("AVAILABLE", "IN_SHOP")


def assert_work_order(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("aircraft_id", ""))
    assert isinstance(data["scope_description"], str)
    assert isinstance(data["estimated_downtime_days"], int)
    assert isinstance(data["quoted_labor_hours"], (int, float))
    assert isinstance(data["bay_code"], str) and data["bay_code"]
    assert is_iso8601_timestamp(data.get("bay_window_start", ""))
    assert is_iso8601_timestamp(data.get("bay_window_end", ""))
    assert data["status"] in (
        "DRAFT", "PENDING_APPROVAL", "APPROVED", "PARTS_PENDING",
        "INSTALLATION", "TESTING", "COMPLETED", "CANCELLED",
    )
    assert data["inducted_at"] is None or is_iso8601_timestamp(data["inducted_at"])
    assert data["completed_at"] is None or is_iso8601_timestamp(data["completed_at"])
    assert data["actual_downtime_days"] is None or isinstance(data["actual_downtime_days"], int)
    assert data["downtime_overage_days"] is None or isinstance(data["downtime_overage_days"], int)
    assert isinstance(data["overage_acknowledged"], bool)
    assert isinstance(data["parts_pending_count"], int)
    assert isinstance(data["tasks_unverified_count"], int)
    assert isinstance(data["total_actual_labor_hours"], (int, float))
    assert isinstance(data["total_billed_labor_cents"], int)
    assert data["quoted_total_cents"] is None or isinstance(data["quoted_total_cents"], int)
    assert isinstance(data["warranty_term_months"], int)
    assert isinstance(data["software_subscription_months"], int)
    assert data["warranty_expires_at"] is None or is_iso8601_timestamp(data["warranty_expires_at"])
    assert data["subscription_expires_at"] is None or is_iso8601_timestamp(data["subscription_expires_at"])


def assert_panel_design(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("work_order_id", ""))
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert isinstance(data["layout_notes"], str)
    assert isinstance(data["equipment_list"], list)
    for line in data["equipment_list"]:
        assert isinstance(line["part_number"], str)
        assert isinstance(line["quantity"], int)
        assert isinstance(line["unit_price_cents"], int)
        assert isinstance(line["weight_lb"], (int, float))
        assert isinstance(line["arm_in"], (int, float))
        assert isinstance(line["lead_time_days"], int)
    assert isinstance(data["total_added_weight_lb"], (int, float))
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "APPROVED", "CHANGES_REQUESTED", "SUPERSEDED",
    )


def assert_equipment_order(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("work_order_id", ""))
    assert isinstance(data["seq"], int)
    assert data["source"] in ("DESIGN_RELEASE", "MANUAL")
    assert data["source_design_revision"] is None or isinstance(data["source_design_revision"], int)
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] > 0
    assert isinstance(data["lead_time_days"], int) and data["lead_time_days"] >= 0
    assert data["ordered_at"] is None or is_iso8601_timestamp(data["ordered_at"])
    assert data["promised_date"] is None or is_iso8601_timestamp(data["promised_date"])
    assert data["received_at"] is None or is_iso8601_timestamp(data["received_at"])
    assert isinstance(data["is_late"], bool)
    assert data["status"] in ("PLANNED", "ORDERED", "RECEIVED", "CANCELLED")


def assert_install_task(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("work_order_id", ""))
    assert data["task_kind"] in ("HARNESS_FABRICATION", "PANEL_ASSEMBLY", "INSTALLATION")
    assert isinstance(data["description"], str)
    assert isinstance(data["estimated_hours"], (int, float)) and data["estimated_hours"] > 0
    assert data["actual_hours"] is None or isinstance(data["actual_hours"], (int, float))
    assert data["performed_by_user_id"] is None or isinstance(data["performed_by_user_id"], str)
    assert data["verified_by_user_id"] is None or isinstance(data["verified_by_user_id"], str)
    assert data["billed_labor_cents"] is None or isinstance(data["billed_labor_cents"], int)
    assert data["status"] in ("PLANNED", "IN_PROGRESS", "COMPLETED", "VERIFIED", "VOIDED")


def assert_test_event(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("work_order_id", ""))
    assert data["test_kind"] in ("GROUND", "FLIGHT")
    assert is_iso8601_timestamp(data.get("scheduled_start", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end", ""))
    assert isinstance(data["attempt"], int) and data["attempt"] >= 1
    assert data["result"] in ("NONE", "PASS", "FAIL")
    assert data["status"] in ("SCHEDULED", "PASSED", "FAILED", "CANCELLED")


def assert_regulatory_package(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("work_order_id", ""))
    assert data["approval_path"] in ("STC", "FIELD_APPROVAL")
    assert data["stc_number"] is None or isinstance(data["stc_number"], str)
    assert data["faa_tracking_number"] is None or isinstance(data["faa_tracking_number"], str)
    assert data["decided_by_user_id"] is None or isinstance(data["decided_by_user_id"], str)
    assert data["status"] in ("DRAFT", "CONFORMITY_REVIEW", "FAA_SUBMITTED", "APPROVED")


def assert_weight_balance_revision(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("work_order_id", ""))
    assert data["method"] in ("INCREMENTAL", "FULL_REWEIGH")
    assert isinstance(data["added_items"], list)
    assert isinstance(data["removed_weight_lb"], (int, float))
    assert data["removed_arm_in"] is None or isinstance(data["removed_arm_in"], (int, float))
    assert isinstance(data["new_empty_weight_lb"], (int, float))
    assert isinstance(data["new_moment_lb_in"], (int, float))
    assert isinstance(data["new_arm_in"], (int, float))
    assert isinstance(data["cg_within_limits"], bool)
    assert data["status"] in ("COMPUTED", "ACCEPTED", "SUPERSEDED")


# ---------------------------------------------------------------------------
# Domain invariants (PRD §2.9 derived counters)
# ---------------------------------------------------------------------------

def assert_work_order_invariants(data: dict):
    """Aggregate counters and totals never drift negative."""
    assert data["parts_pending_count"] >= 0
    assert data["tasks_unverified_count"] >= 0
    assert data["total_actual_labor_hours"] >= 0
    assert data["total_billed_labor_cents"] >= 0
