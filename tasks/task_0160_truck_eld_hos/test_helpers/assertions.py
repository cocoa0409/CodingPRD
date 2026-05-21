"""Entity assertions and domain invariant checkers.

Each `assert_{entity}(data)` walks the field set declared in PRD §3
for that entity. Common-fields entities carry id + created_at +
updated_at + version (PRD §2.4); the DutyEvent entity is append-only
and carries ONLY id + created_at — PRD §2.4: "The `DutyEvent`
resource is an immutable audit record and carries only `id` and
`created_at`; it has no `updated_at` and no `version`."
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    CYCLE_TYPES,
    DAILY_LOG_STATUSES,
    DUTY_STATUSES,
    EXEMPTION_STATUSES,
    VIOLATION_RULE_CODES,
    VIOLATION_STATUSES,
)


# ---------------------------------------------------------------------------
# Envelope checks
# ---------------------------------------------------------------------------
def assert_common_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: every common-fields resource carries id, created_at,
    updated_at, and version (monotonically increasing integer starting
    at 1)."""
    assert "id" in data, "common-fields row missing 'id'"
    assert is_valid_uuid(str(data["id"])), (
        f"id must be a UUID without prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing 'created_at'"
    assert is_iso8601_timestamp(str(data["created_at"])), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )
    assert "updated_at" in data, "missing 'updated_at'"
    assert is_iso8601_timestamp(str(data["updated_at"])), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing 'version'"
    assert isinstance(data["version"], int), (
        f"version must be int, got {type(data['version'])}"
    )
    assert data["version"] >= 1, (
        f"version must be >= 1, got {data['version']}"
    )


def assert_append_only_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: "The `DutyEvent` resource is an immutable audit
    record and carries only `id` and `created_at`; it has no
    `updated_at` and no `version`."""
    assert "id" in data, "append-only row missing 'id'"
    assert is_valid_uuid(str(data["id"])), (
        f"id must be a UUID, got {data['id']!r}"
    )
    assert "created_at" in data, "missing 'created_at'"
    assert is_iso8601_timestamp(str(data["created_at"])), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )
    assert "updated_at" not in data, (
        "DutyEvent must not expose 'updated_at' "
        f"(found: {data.get('updated_at')!r})"
    )
    assert "version" not in data, (
        "DutyEvent must not expose 'version' "
        f"(found: {data.get('version')!r})"
    )


def assert_status(data: Dict[str, Any], expected: str,
                  field: str = "status") -> None:
    actual = data.get(field)
    assert actual == expected, (
        f"Expected {field}={expected!r}, got {actual!r}"
    )


def assert_version_incremented_by(prior: Dict[str, Any],
                                  current: Dict[str, Any],
                                  delta: int = 1) -> None:
    """PRD §2.4: "`version` ... an integer that begins at 1 on creation
    and increments by 1 on every server-side mutation of the
    resource."""
    assert "version" in prior and "version" in current, (
        "both prior and current must carry version"
    )
    assert current["version"] == prior["version"] + delta, (
        f"Expected version {prior['version']} + {delta} = "
        f"{prior['version'] + delta}, got {current['version']}"
    )


# ---------------------------------------------------------------------------
# Carrier — PRD §3.1
# ---------------------------------------------------------------------------
def assert_carrier(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("dot_number"), str) and (
        5 <= len(data["dot_number"]) <= 8
    )
    assert data["dot_number"].isdigit(), (
        "PRD §3.1: dot_number is digits only"
    )
    assert isinstance(data.get("legal_name"), str)
    assert isinstance(data.get("safety_contact_user_id"), str)


# ---------------------------------------------------------------------------
# ELDDevice — PRD §3.1
# ---------------------------------------------------------------------------
def assert_eld_device(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("serial_number"), str)
    assert 6 <= len(data["serial_number"]) <= 32
    assert isinstance(data.get("firmware_version"), str)
    assert isinstance(data.get("certified_for_fmcsa"), bool)


# ---------------------------------------------------------------------------
# Vehicle — PRD §3.1
# ---------------------------------------------------------------------------
def assert_vehicle(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("vin"), str)
    assert len(data["vin"]) == 17, "PRD §3.1: VIN is 17 chars"
    assert all(c.isupper() or c.isdigit() for c in data["vin"]), (
        "PRD §3.1: VIN is uppercase alphanumeric"
    )
    for forbidden in ("I", "O", "Q"):
        assert forbidden not in data["vin"], (
            f"PRD §3.1: VIN excludes letter {forbidden}"
        )
    assert is_valid_uuid(str(data["carrier_id"]))
    assert is_valid_uuid(str(data["eld_device_id"]))


# ---------------------------------------------------------------------------
# Driver — PRD §3.1, §3.2, §3.3
# ---------------------------------------------------------------------------
def assert_driver(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("cdl_number"), str)
    assert 6 <= len(data["cdl_number"]) <= 20
    assert data["cdl_number"] == data["cdl_number"].upper(), (
        "PRD §3.1: cdl_number is uppercase alphanumeric"
    )
    assert isinstance(data.get("full_name"), str)
    assert is_valid_uuid(str(data["carrier_id"]))
    assert data["cycle_type"] in CYCLE_TYPES
    assert data["duty_status"] in DUTY_STATUSES
    # bound_vehicle_id / bound_eld_device_id may be null when unbound
    assert "bound_vehicle_id" in data
    assert "bound_eld_device_id" in data
    assert isinstance(data.get("home_terminal_timezone"), str)
    # last_34_hour_restart_completed_at may be null
    assert "last_34_hour_restart_completed_at" in data


# ---------------------------------------------------------------------------
# DutyEvent — PRD §3.3 (append-only)
# ---------------------------------------------------------------------------
def assert_duty_event(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert is_valid_uuid(str(data["driver_id"]))
    assert data["new_status"] in DUTY_STATUSES
    assert is_iso8601_timestamp(str(data["event_time"]))
    assert isinstance(data["latitude"], (int, float))
    assert -90 <= float(data["latitude"]) <= 90
    assert isinstance(data["longitude"], (int, float))
    assert -180 <= float(data["longitude"]) <= 180
    assert data["edit_state"] in {"ACTIVE", "SUPERSEDED"}


# ---------------------------------------------------------------------------
# DailyLog — PRD §3.7
# ---------------------------------------------------------------------------
def assert_daily_log(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(str(data["driver_id"]))
    # log_date is YYYY-MM-DD in driver's home_terminal_timezone (PRD §3.7)
    assert isinstance(data.get("log_date"), str)
    assert len(data["log_date"]) == 10 and data["log_date"][4] == "-" \
        and data["log_date"][7] == "-", (
            f"log_date must be YYYY-MM-DD, got {data['log_date']!r}"
        )
    assert data["status"] in DAILY_LOG_STATUSES
    assert isinstance(data.get("certification_count"), int)
    assert data["certification_count"] >= 0
    assert isinstance(data.get("total_driving_minutes"), int)
    assert data["total_driving_minutes"] >= 0
    assert isinstance(data.get("total_on_duty_minutes"), int)
    assert data["total_on_duty_minutes"] >= 0


def assert_integrity_hash_format(h: Any) -> None:
    """PRD §3.7: "lowercase hexadecimal SHA-256 (64 characters)"."""
    assert isinstance(h, str), f"integrity_hash must be a string, got {h!r}"
    assert len(h) == 64, (
        f"integrity_hash must be 64 hex chars, got len={len(h)}"
    )
    assert h == h.lower(), (
        f"integrity_hash must be lowercase, got {h!r}"
    )
    int(h, 16)  # raises if not hex


# ---------------------------------------------------------------------------
# Violation — PRD §3.4, §3.8
# ---------------------------------------------------------------------------
def assert_violation(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(str(data["driver_id"]))
    assert is_valid_uuid(str(data["triggering_duty_event_id"]))
    assert data["rule_code"] in VIOLATION_RULE_CODES
    assert is_iso8601_timestamp(str(data["detected_at"]))
    assert data["status"] in VIOLATION_STATUSES
    assert isinstance(data.get("overage_minutes"), int)
    assert data["overage_minutes"] >= 0


# ---------------------------------------------------------------------------
# AdverseConditionsExemption — PRD §3.6
# ---------------------------------------------------------------------------
def assert_adverse_conditions_exemption(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(str(data["driver_id"]))
    assert is_iso8601_timestamp(str(data["declared_at"]))
    assert isinstance(data.get("reason"), str)
    assert len(data["reason"]) >= 10, (
        "PRD §3.6: reason length is at least 10 characters"
    )
    assert data["status"] in EXEMPTION_STATUSES
    assert isinstance(data.get("extra_minutes_granted"), int)
    assert data["extra_minutes_granted"] == 120, (
        "PRD §3.6: extra_minutes_granted is a fixed value of 120"
    )
    assert isinstance(data.get("applies_to_log_date"), str)


__all__ = [
    "assert_common_fields", "assert_append_only_fields",
    "assert_status", "assert_version_incremented_by",
    "assert_carrier", "assert_eld_device", "assert_vehicle",
    "assert_driver", "assert_duty_event", "assert_daily_log",
    "assert_integrity_hash_format",
    "assert_violation", "assert_adverse_conditions_exemption",
]
