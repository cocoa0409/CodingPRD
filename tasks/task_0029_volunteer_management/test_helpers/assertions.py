"""Entity assertions and domain invariant checkers.

Each `assert_<entity>` function validates the response shape against PRD
§1 (entity definitions) and §2.4 (common fields). Invariant helpers cover
PRD §3 calculations, side effects, and audit/sync emissions.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-field assertions
# ---------------------------------------------------------------------------
_COMMON_REQUIRED_FIELDS = ("id", "created_at", "updated_at", "version")
_APPEND_ONLY_REQUIRED_FIELDS = ("id", "created_at")


def _assert_common(data: Dict[str, Any]) -> None:
    """Common-fields entity (PRD §2.4): id + created_at + updated_at + version."""
    for f in _COMMON_REQUIRED_FIELDS:
        assert f in data, f"missing common field {f!r}: {data!r}"
    assert is_valid_uuid(str(data["id"])), f"id must be a UUID, got {data['id']!r}"
    assert is_iso8601_timestamp(str(data["created_at"])), (
        f"created_at must be ISO 8601 with three fractional digits, got "
        f"{data['created_at']!r}"
    )
    assert is_iso8601_timestamp(str(data["updated_at"])), (
        f"updated_at must be ISO 8601 with three fractional digits, got "
        f"{data['updated_at']!r}"
    )
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data['version']!r}"
    )


def _assert_append_only(data: Dict[str, Any]) -> None:
    """Append-only entity (PRD §2.4 exception): only id + created_at.

    PRD §2.4 explicitly states these entities have neither updated_at nor
    version. We do NOT assert their presence here, and tests must not
    require them.
    """
    for f in _APPEND_ONLY_REQUIRED_FIELDS:
        assert f in data, f"missing append-only field {f!r}: {data!r}"
    assert is_valid_uuid(str(data["id"])), f"id must be a UUID, got {data['id']!r}"
    assert is_iso8601_timestamp(str(data["created_at"])), (
        f"created_at must be ISO 8601 with three fractional digits"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_volunteer(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("id_number_hash"), str) and data["id_number_hash"]
    assert data.get("identity_verification_status") in {
        "PENDING", "VERIFIED", "REJECTED",
    }
    assert data.get("background_check_status") in {
        "NONE", "PENDING", "CLEARED", "FAILED",
    }
    # Geographic ranges are PRD §2.5.
    assert -90.0 <= float(data["home_lat"]) <= 90.0
    assert -180.0 <= float(data["home_lng"]) <= 180.0
    # Computed totals — PRD §3.1 begins each at 0.
    assert isinstance(data.get("total_completed_activities"), int)
    assert data["total_completed_activities"] >= 0
    assert isinstance(data.get("points_balance"), int)
    assert data["points_balance"] >= 0
    assert float(data["total_service_hours"]) >= 0
    assert float(data["archived_hours"]) >= 0


def assert_skill(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert isinstance(data.get("code"), str) and data["code"]
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("requires_certificate"), bool)
    assert data.get("sensitivity_level") in {"STANDARD", "SENSITIVE"}


def assert_volunteer_skill(data: Dict[str, Any]) -> None:
    _assert_append_only(data)
    assert is_valid_uuid(str(data["volunteer_id"]))
    assert is_valid_uuid(str(data["skill_id"]))
    assert data.get("review_status") in {
        "SELF_DECLARED", "UNDER_REVIEW", "APPROVED", "REJECTED",
    }


def assert_activity(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert is_valid_uuid(str(data["organizer_id"]))
    assert isinstance(data.get("title"), str) and data["title"]
    assert isinstance(data.get("description"), str) and data["description"]
    assert -90.0 <= float(data["location_lat"]) <= 90.0
    assert -180.0 <= float(data["location_lng"]) <= 180.0
    assert is_iso8601_timestamp(str(data["start_at"]))
    assert is_iso8601_timestamp(str(data["end_at"]))
    assert is_iso8601_timestamp(str(data["recruit_open_at"]))
    assert is_iso8601_timestamp(str(data["recruit_close_at"]))
    assert isinstance(data.get("required_skill_codes"), list)
    assert isinstance(data.get("position_quota"), int) and data["position_quota"] >= 1
    assert isinstance(data.get("filled_positions"), int)
    assert data["filled_positions"] >= 0
    assert data["filled_positions"] <= data["position_quota"], (
        f"filled_positions {data['filled_positions']} must not exceed "
        f"position_quota {data['position_quota']}"
    )
    assert data.get("difficulty") in {"EASY", "MEDIUM", "HARD"}
    assert data.get("hour_rule_type") in {
        "ACTUAL_DURATION", "FIXED_VALUE", "ROLE_COEFFICIENT",
    }
    assert isinstance(data.get("requires_sensitive_clearance"), bool)
    assert data.get("status") in {
        "DRAFT", "UNDER_REVIEW", "PUBLISHED", "RECRUITING",
        "RUNNING", "COMPLETED", "SHELVED", "REJECTED",
    }


def assert_activity_role(data: Dict[str, Any]) -> None:
    _assert_append_only(data)
    assert is_valid_uuid(str(data["activity_id"]))
    assert isinstance(data.get("role_label"), str) and data["role_label"]
    assert 0.5 <= float(data["coefficient"]) <= 3.0


def assert_application(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert is_valid_uuid(str(data["activity_id"]))
    assert is_valid_uuid(str(data["volunteer_id"]))
    assert data.get("status") in {
        "APPLIED", "APPROVED", "REJECTED", "WITHDRAWN",
        "CHECKED_IN", "ON_LEAVE", "COMPLETED", "NO_SHOW",
    }
    # distance_km is computed at apply time (PRD §3.4) — required, 2 decimals.
    assert "distance_km" in data
    assert float(data["distance_km"]) >= 0
    # Markers default to false (PRD §1 entity defaults).
    assert isinstance(data.get("late_marker", False), bool)
    assert isinstance(data.get("early_departure_marker", False), bool)
    # Computed numeric fields default to 0.
    assert float(data.get("credited_hours", 0)) >= 0
    assert float(data.get("adjusted_hours", 0)) >= 0
    assert int(data.get("points_awarded", 0)) >= 0


def assert_hour_adjustment(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert is_valid_uuid(str(data["application_id"]))
    assert isinstance(data.get("delta_hours"), (int, float))
    assert -8.0 <= float(data["delta_hours"]) <= 8.0
    assert isinstance(data.get("reason"), str)
    assert 10 <= len(data["reason"]) <= 500
    assert data.get("status") in {"PENDING", "APPROVED", "REJECTED"}


def assert_point_mall_item(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert isinstance(data.get("sku"), str) and data["sku"]
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("point_cost"), int) and 1 <= data["point_cost"] <= 100_000
    assert isinstance(data.get("stock"), int) and data["stock"] >= 0
    assert data.get("status") in {"ACTIVE", "OUT_OF_STOCK", "ARCHIVED"}


def assert_redemption_order(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert is_valid_uuid(str(data["volunteer_id"]))
    assert is_valid_uuid(str(data["item_id"]))
    assert isinstance(data.get("quantity"), int) and 1 <= data["quantity"] <= 10
    assert isinstance(data.get("total_points"), int) and data["total_points"] >= 1
    assert data.get("status") in {"PENDING", "FULFILLED", "CANCELLED"}


def assert_certificate_template(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert isinstance(data.get("code"), str) and data["code"]
    assert isinstance(data.get("title"), str) and data["title"]
    assert float(data["min_hours"]) > 0
    assert isinstance(data.get("min_completed_activities"), int)
    assert data["min_completed_activities"] >= 1
    assert data.get("status") in {"ACTIVE", "ARCHIVED"}


def assert_certificate(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert is_valid_uuid(str(data["template_id"]))
    assert is_valid_uuid(str(data["volunteer_id"]))
    serial = data.get("serial_number")
    assert isinstance(serial, str) and len(serial) == 12 and serial.isalnum(), (
        f"serial_number must be 12-char alphanumeric, got {serial!r}"
    )
    assert float(data["hours_at_issuance"]) >= 0
    assert isinstance(data.get("activities_at_issuance"), int)
    assert data["activities_at_issuance"] >= 0
    assert data.get("status") in {"ISSUED", "REVOKED", "REISSUED"}


def assert_audit_log(data: Dict[str, Any]) -> None:
    _assert_append_only(data)
    assert isinstance(data.get("actor_role"), str) and data["actor_role"]
    assert isinstance(data.get("actor_id"), str) and data["actor_id"]
    # PRD §2.10 constrains action_type to exactly six values.
    assert data.get("action_type") in {
        "HOUR_ADJUST_REQUEST", "HOUR_ADJUST_APPROVE", "HOUR_ADJUST_REJECT",
        "CERTIFICATE_ISSUE", "CERTIFICATE_REISSUE", "CERTIFICATE_REVOKE",
    }
    assert isinstance(data.get("target_entity"), str)
    assert isinstance(data.get("target_id"), str)
    assert isinstance(data.get("payload"), dict)


def assert_partner_sync_event(data: Dict[str, Any]) -> None:
    _assert_append_only(data)
    assert data.get("channel") in {"IM", "IDENTITY_PROVIDER", "PARTNER_ORG"}
    assert isinstance(data.get("event_type"), str) and data["event_type"]
    assert isinstance(data.get("payload"), dict)


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------
def find_audit_logs(
    items: List[Dict[str, Any]],
    *,
    action_type: Optional[str] = None,
    target_entity: Optional[str] = None,
    target_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for entry in items:
        if action_type is not None and entry.get("action_type") != action_type:
            continue
        if target_entity is not None and entry.get("target_entity") != target_entity:
            continue
        if target_id is not None and entry.get("target_id") != target_id:
            continue
        out.append(entry)
    return out


def find_partner_sync_events(
    items: List[Dict[str, Any]],
    *,
    channel: Optional[str] = None,
    event_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for entry in items:
        if channel is not None and entry.get("channel") != channel:
            continue
        if event_type is not None and entry.get("event_type") != event_type:
            continue
        out.append(entry)
    return out


def assert_volunteer_totals(
    volunteer: Dict[str, Any],
    *,
    expected_total_service_hours: Optional[float] = None,
    expected_points_balance: Optional[int] = None,
    expected_total_completed_activities: Optional[int] = None,
    expected_archived_hours: Optional[float] = None,
    tolerance: float = 1e-6,
) -> None:
    """Check Volunteer computed totals after a transaction (PRD §3.1, §3.7).

    Numeric comparisons use absolute tolerance for hours (2-decimal precision
    per PRD §2.5); points are integer-equal.
    """
    if expected_total_service_hours is not None:
        actual = float(volunteer["total_service_hours"])
        assert abs(actual - expected_total_service_hours) <= tolerance, (
            f"total_service_hours expected {expected_total_service_hours}, "
            f"got {actual}"
        )
    if expected_points_balance is not None:
        assert int(volunteer["points_balance"]) == expected_points_balance, (
            f"points_balance expected {expected_points_balance}, "
            f"got {volunteer['points_balance']}"
        )
    if expected_total_completed_activities is not None:
        assert (
            int(volunteer["total_completed_activities"])
            == expected_total_completed_activities
        ), (
            f"total_completed_activities expected "
            f"{expected_total_completed_activities}, got "
            f"{volunteer['total_completed_activities']}"
        )
    if expected_archived_hours is not None:
        actual = float(volunteer["archived_hours"])
        assert abs(actual - expected_archived_hours) <= tolerance, (
            f"archived_hours expected {expected_archived_hours}, got {actual}"
        )


def assert_two_decimal(value: float, message: str = "") -> None:
    """Assert numeric value carries at most two decimal places (PRD §2.5)."""
    rounded = round(value, 2)
    assert abs(value - rounded) < 1e-9, (
        f"{message or 'value'} must have at most 2 decimal places: got {value}"
    )


__all__ = [
    "assert_volunteer",
    "assert_skill",
    "assert_volunteer_skill",
    "assert_activity",
    "assert_activity_role",
    "assert_application",
    "assert_hour_adjustment",
    "assert_point_mall_item",
    "assert_redemption_order",
    "assert_certificate_template",
    "assert_certificate",
    "assert_audit_log",
    "assert_partner_sync_event",
    "find_audit_logs",
    "find_partner_sync_events",
    "assert_volunteer_totals",
    "assert_two_decimal",
]
