"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from datetime import datetime, timezone
from decimal import Decimal

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_instant(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp tolerating 'Z' and offset renderings."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def assert_common_fields(data: dict):
    """PRD §2.4: every entity carries id / created_at / updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_money_equals(actual, expected: str):
    """Compare a 2-decimal money/decimal figure against an exact literal.

    Decimal(str(...)) equality ignores trailing-zero rendering but still
    distinguishes cents (506.30 != 506.29) — PRD §2.5 pins 2-decimal half-up.
    """
    actual_dec = Decimal(str(actual))
    expected_dec = Decimal(str(expected))
    assert actual_dec == expected_dec, f"Expected {expected_dec}, got {actual_dec}"


def assert_timestamp_instant_equals(actual: str, expected_iso: str):
    """Assert two ISO timestamps denote the same instant (rendering-tolerant)."""
    assert _parse_instant(actual) == _parse_instant(expected_iso), (
        f"Expected instant {expected_iso}, got {actual}"
    )


def assert_substation(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "DECOMMISSIONED")
    assert isinstance(data["code"], str) and data["code"]


def assert_asset_class_policy(data: dict):
    assert_common_fields(data)
    assert data["asset_class"] in ("POWER_TRANSFORMER", "CIRCUIT_BREAKER", "RELAY")
    assert isinstance(data["interval_months"], int) and data["interval_months"] > 0


def assert_asset(data: dict):
    assert_common_fields(data)
    assert data["asset_class"] in ("POWER_TRANSFORMER", "CIRCUIT_BREAKER", "RELAY")
    assert data["status"] in ("IN_SERVICE", "OUT_OF_SERVICE", "DECOMMISSIONED")


def assert_outage_window(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "REQUESTED", "APPROVED", "REJECTED", "CANCELLED", "SWITCHING", "CLEARED", "RESTORED",
    )


def assert_switching_step(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("PENDING", "EXECUTED", "VERIFIED")
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1


def assert_test_event(data: dict):
    assert_common_fields(data)
    assert data["test_type"] in ("INSULATION_RESISTANCE", "OIL_MOISTURE", "RELAY_TIMING")
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "RETURNED")
    assert data["result"] in (None, "PASS", "MARGINAL", "FAIL")


def assert_defect(data: dict):
    assert_common_fields(data)
    assert data["severity"] in ("C1", "C2", "C3")
    assert data["status"] in ("OPEN", "WORK_ORDERED", "RESOLVED", "VERIFIED", "DEFERRED")
    assert isinstance(data["deferral_count"], int)


def assert_work_order(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "DRAFT", "SCHEDULED", "IN_PROGRESS", "COMPLETED", "VERIFIED", "CANCELLED",
    )


def assert_spare_unit(data: dict):
    assert_common_fields(data)
    assert data["unit_type"] in ("SPARE_TRANSFORMER", "MOBILE_SUBSTATION")
    assert data["status"] in ("AVAILABLE", "RESERVED", "DEPLOYED", "DECOMMISSIONED")


def assert_spare_reservation(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "CANCELLED", "FULFILLED")


def assert_relay_setting(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "REJECTED", "VERIFIED", "ACTIVE", "SUPERSEDED")


def assert_technician(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["employee_code"], str) and data["employee_code"]


def assert_certification(data: dict):
    assert_common_fields(data)
    assert data["cert_type"] in (
        "NETA_LEVEL_2", "NETA_LEVEL_3", "NETA_LEVEL_4", "SWITCHING_QUALIFIED",
    )
    assert data["status"] in ("ACTIVE", "EXPIRED", "REVOKED")


def assert_environmental_inspection(data: dict):
    assert_common_fields(data)
    assert data["method"] in ("SPCC_SIMPLE", "SPCC_WITH_FREEBOARD")
    assert data["status"] in ("DRAFT", "COMPLETED", "CLOSED")
    assert data["compliance"] in (None, "COMPLIANT", "DEFICIENT")
