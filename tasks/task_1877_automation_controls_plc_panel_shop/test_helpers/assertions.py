"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into an aware datetime for comparison."""
    assert isinstance(value, str), f"expected ISO timestamp string, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_same_instant(actual: str, expected: str, label: str = "timestamp"):
    """Two ISO 8601 timestamps denote the same instant, regardless of spelling."""
    assert _parse_instant(actual) == _parse_instant(expected), (
        f"{label}: expected instant {expected}, got {actual}"
    )


def assert_common_fields(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, (
            "version must be an integer starting at 1"
        )
    else:
        assert "updated_at" not in data, "updated_at must be absent on this resource (PRD §2.4)"
        assert "version" not in data, "version must be absent on this resource (PRD §2.4)"


def assert_customer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["site_state_code"], str) and len(data["site_state_code"]) == 2
    assert isinstance(data["credit_hold"], bool)
    assert data["warranty_labor_tier"] in ("TIER_LOCAL", "TIER_REGIONAL", "TIER_NATIONAL")


def assert_job(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a UUID"
    assert isinstance(data["job_number"], str) and data["job_number"]
    assert data["status"] in (
        "OPEN", "DESIGN", "PROCUREMENT", "BUILD", "TEST", "READY_TO_SHIP",
        "SHIPPED", "COMMISSIONED", "CLOSED", "ON_HOLD",
    )
    assert isinstance(data["quoted_price_cents"], int) and data["quoted_price_cents"] >= 0
    assert isinstance(data["approved_co_delta_cents"], int)
    assert isinstance(data["contract_price_cents"], int)
    assert isinstance(data["warranty_months"], int) and 0 <= data["warranty_months"] <= 60


def assert_job_ledger_invariant(data: dict):
    """contract_price_cents == quoted_price_cents + approved_co_delta_cents (PRD §3.8)."""
    assert data["contract_price_cents"] == (
        data["quoted_price_cents"] + data["approved_co_delta_cents"]
    ), (
        f"ledger drift: contract {data['contract_price_cents']} != quoted "
        f"{data['quoted_price_cents']} + delta {data['approved_co_delta_cents']}"
    )


def assert_panel(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("job_id", "")), "job_id must be a UUID"
    assert isinstance(data["panel_tag"], str) and data["panel_tag"]
    assert data["status"] in (
        "DESIGN", "DESIGN_REVIEW", "DESIGN_APPROVED", "PROCUREMENT", "WIRING",
        "POINT_TO_POINT", "TEST_PASSED", "TEST_FAILED", "READY_FOR_LABEL",
        "LABELED", "SHIPPED", "COMMISSIONED",
    )
    assert data["enclosure_rating"] in ("NEMA_1", "NEMA_12", "NEMA_4", "NEMA_4X")
    assert isinstance(data["design_engineer_id"], str) and data["design_engineer_id"]
    assert isinstance(data["sccr_rating_ka"], int)


def assert_component(data: dict):
    assert_common_fields(data)
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert data["component_class"] in (
        "DISCONNECT", "BRANCH_PROTECTIVE", "CONTACTOR", "OVERLOAD", "CONTROL_POWER",
        "PLC_IO", "TERMINAL", "WIRE_DUCT", "PILOT_DEVICE", "POWER_SUPPLY",
    )
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert isinstance(data["lead_time_days"], int) and data["lead_time_days"] >= 0
    if data.get("sccr_ka") is not None:
        assert isinstance(data["sccr_ka"], int) and data["sccr_ka"] >= 1
    assert isinstance(data["active"], bool)


def assert_panel_component(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("panel_id", ""))
    assert is_valid_uuid(data.get("component_id", ""))
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["line_status"] in ("PENDING", "ORDERED", "RECEIVED", "SUBSTITUTED")
    assert isinstance(data["unit_cost_snapshot_cents"], int)
    assert isinstance(data["extended_cost_cents"], int)
    assert data["extended_cost_cents"] == data["quantity"] * data["unit_cost_snapshot_cents"], (
        "extended_cost_cents must equal quantity * unit_cost_snapshot_cents (PRD §3.2)"
    )


def assert_substitution_request(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("panel_id", ""))
    assert is_valid_uuid(data.get("original_line_id", ""))
    assert is_valid_uuid(data.get("proposed_component_id", ""))
    assert data["status"] in ("REQUESTED", "COUNTERED", "APPROVED", "REJECTED", "WITHDRAWN")


def assert_test_point(data: dict):
    # TestPoint carries id + created_at only — no updated_at, no version (PRD §2.4).
    assert_common_fields(data, with_version=False)
    assert is_valid_uuid(data.get("panel_id", ""))
    assert isinstance(data["point_label"], str) and data["point_label"]
    assert data["expected_signal"] in (
        "CONTINUITY", "VOLTAGE_24VDC", "VOLTAGE_120VAC", "ANALOG_4_20MA", "ISOLATION"
    )
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert data["result"] in ("UNTESTED", "PASS", "FAIL", "SKIPPED")


def assert_test_session(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("panel_id", ""))
    assert isinstance(data["technician_id"], str) and data["technician_id"]
    assert data["status"] in ("OPEN", "COMPLETED", "ABORTED")
    assert isinstance(data["pass_count"], int) and data["pass_count"] >= 0
    assert isinstance(data["fail_count"], int) and data["fail_count"] >= 0


def assert_program_version(data: dict):
    # ProgramVersion carries id + created_at only — no updated_at, no version (PRD §2.4).
    assert_common_fields(data, with_version=False)
    assert is_valid_uuid(data.get("panel_id", ""))
    assert isinstance(data["version_tag"], str) and data["version_tag"]
    assert data["status"] in ("DRAFT", "RELEASED", "SUPERSEDED", "ARCHIVED")
    assert isinstance(data["content_hash"], str) and len(data["content_hash"]) == 64
    assert isinstance(data["site_backup_taken"], bool)


def assert_startup_session(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("panel_id", ""))
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "NO_SHOW", "CANCELLED")
    assert data["support_mode"] in ("ONSITE", "REMOTE")
    assert isinstance(data["remote_access_granted"], bool)
    assert isinstance(data["engineer_id"], str) and data["engineer_id"]


def assert_change_order(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("job_id", ""))
    assert isinstance(data["co_number"], int) and data["co_number"] >= 1
    assert data["status"] in (
        "PROPOSED", "REVISED", "APPROVED", "REJECTED", "WITHDRAWN", "SUPERSEDED"
    )
    assert isinstance(data["price_delta_cents"], int)
    assert isinstance(data["computed_delta_cents"], int)


def assert_warranty_claim(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("job_id", ""))
    assert is_valid_uuid(data.get("panel_id", ""))
    assert data["status"] in ("FILED", "TRIAGED", "ACCEPTED", "DENIED", "SETTLED", "CLOSED")
    assert data["claimed_labor_hours"] >= 0


def assert_asbuilt_package(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("panel_id", ""))
    assert data["status"] in ("INCOMPLETE", "PENDING_REVIEW", "APPROVED", "RELEASED")
    for flag in ("has_wiring_diagram", "has_program_archive", "has_test_report",
                 "has_ul_label_photo"):
        assert isinstance(data[flag], bool), f"{flag} must be bool"
    assert isinstance(data["completeness_pct"], int) and 0 <= data["completeness_pct"] <= 100
