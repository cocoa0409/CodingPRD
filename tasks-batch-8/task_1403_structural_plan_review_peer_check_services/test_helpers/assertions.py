"""Entity assertions and domain invariant checkers (PRD §2.2, §2.5, §3)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def assert_timestamp_equals(actual, expected_iso, label="timestamp"):
    """Compare two ISO 8601 instants regardless of formatting differences."""
    assert actual is not None, f"{label}: expected {expected_iso}, got None"
    assert _parse_iso(actual) == _parse_iso(expected_iso), (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def assert_common_fields(data: dict):
    """PRD §2.5 common resource properties."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_jurisdiction(data: dict):
    assert_common_fields(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["ibc_edition"] in ("IBC_2018", "IBC_2021", "IBC_2024")
    assert data["asce7_edition"] in ("ASCE7_16", "ASCE7_22")
    assert data["fee_method"] in ("VALUATION", "SQUARE_FOOTAGE")
    assert isinstance(data["turnaround_days"], int)
    assert data["sla_mode"] in ("BUSINESS", "CALENDAR")


def assert_reviewer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["licenses"], list)
    for lic in data["licenses"]:
        assert lic["license_type"] in ("PE", "SE")
        assert isinstance(lic["state_code"], str)
        assert isinstance(lic["expires_on"], str)
    assert isinstance(data["active_assignment_count"], int)
    assert data["active_assignment_count"] >= 0


def assert_engagement(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "REGISTERED", "IN_PROGRESS", "APPROVED", "COMPLETED", "CANCELLED")
    assert data["building_type"] in (
        "RESIDENTIAL", "COMMERCIAL", "INDUSTRIAL", "ESSENTIAL_FACILITY")
    assert data["scope"] in ("FULL_REVIEW", "LATERAL_ONLY", "PEER_REVIEW")
    assert isinstance(data["declared_valuation_cents"], int)
    assert isinstance(data["floor_area_sqft"], int)
    assert isinstance(data["estimated_fee_cents"], int)
    assert isinstance(data["cycle_count"], int) and data["cycle_count"] >= 0
    assert isinstance(data["unresolved_comment_count"], int)
    assert isinstance(data["deferred_pending_count"], int)
    # Pinned snapshot (PRD §2.6)
    for field in ("pinned_state_code", "pinned_ibc_edition", "pinned_asce7_edition",
                  "pinned_fee_method", "pinned_turnaround_days", "pinned_sla_mode",
                  "pinned_free_resubmittal_cycles", "pinned_requires_se_seal",
                  "pinned_allows_deferred_submittals"):
        assert field in data, f"pinned snapshot field {field} missing"


def assert_cycle(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "OPEN", "IN_REVIEW", "COMMENTS_ISSUED", "APPROVED", "SUPERSEDED", "CANCELLED")
    assert isinstance(data["cycle_number"], int) and data["cycle_number"] >= 1
    assert is_iso8601_timestamp(data.get("received_at", ""))
    assert is_iso8601_timestamp(data.get("due_at", ""))


def assert_assignment(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "COMPLETED", "RELEASED")
    assert is_iso8601_timestamp(data.get("assigned_at", ""))


def assert_comment(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("OPEN", "ADDRESSED", "REOPENED", "VERIFIED", "WAIVED")
    assert data["severity"] in ("MINOR", "MAJOR", "CRITICAL")
    assert data["category"] in (
        "LOAD_PATH", "LATERAL_SYSTEM", "CALCULATION", "DETAILING",
        "DEFERRED_COORDINATION")
    assert isinstance(data["response_count"], int) and data["response_count"] >= 0


def assert_comment_response(data: dict):
    """PRD §2.5: immutable ledger entry carries only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "CommentResponse must not carry updated_at"
    assert "version" not in data, "CommentResponse must not carry version"
    assert isinstance(data.get("comment_id"), str)
    assert isinstance(data.get("responder_contact_id"), str)


def assert_deferred(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("REGISTERED", "SUBMITTED", "REJECTED", "APPROVED")
    assert data["item_type"] in (
        "TRUSS", "ANCHOR", "STEEL_CONNECTION", "CURTAIN_WALL", "OTHER_DELEGATED")


def assert_record(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "SEALED", "TRANSMITTED")
    assert isinstance(data["record_number"], str)
    assert isinstance(data["cycle_count_snapshot"], int)


def assert_engagement_invariants(data: dict):
    """Domain invariants that must hold on any engagement read (PRD §3)."""
    assert_engagement(data)
    assert data["unresolved_comment_count"] >= 0
    assert data["deferred_pending_count"] >= 0
    if data["status"] in ("REGISTERED", "IN_PROGRESS") or data.get("final_fee_cents") is None:
        # final fee stays null until the record is sealed (PRD §3.2)
        assert data["final_fee_cents"] is None or data["status"] in (
            "APPROVED", "COMPLETED")
