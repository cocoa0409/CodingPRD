"""Assertion helpers.

The single most important helper here is :func:`assert_instant_equals`.  The
PRD pins the canonical rendering of an instant to exactly three fractional
digits followed by ``Z``, and states that a client-supplied timestamp is
re-rendered in that canonical form on the way out rather than echoed back
byte-for-byte.  Two instants are therefore compared as instants, never as
strings; every timestamp assertion in the suite routes through here.
"""

from datetime import datetime, timezone
from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_instant(value: str) -> datetime:
    """Parse any ISO 8601 UTC rendering into a timezone-aware datetime."""
    assert isinstance(value, str) and value, f"Expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: Optional[str], expected: str, field: str = "instant"):
    """Compare two instants semantically, never as strings.

    ``2026-05-01T00:00:00Z`` and ``2026-05-01T00:00:00.000Z`` denote the same
    instant and must compare equal.
    """
    assert actual is not None, f"{field}: expected {expected}, got null"
    got = parse_instant(actual)
    want = parse_instant(expected)
    assert got == want, f"{field}: expected instant {expected}, got {actual}"


def assert_instant_is_null(actual, field: str = "instant"):
    assert actual is None, f"{field}: expected null, got {actual!r}"


def assert_instant_before(earlier: str, later: str, field: str = "instant"):
    assert parse_instant(earlier) < parse_instant(later), (
        f"{field}: expected {earlier} to be strictly before {later}"
    )


def assert_common_fields(data: dict, entity: str = "entity"):
    """Every persisted resource carries an id and a created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 instant"
    )


def assert_versioned_fields(data: dict, entity: str = "entity"):
    """Nineteen of the twenty-one entity kinds also carry updated_at and version."""
    assert_common_fields(data, entity)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 instant"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"
    assert data["version"] >= 1, f"{entity}.version starts at 1"


def assert_no_version_fields(data: dict, entity: str = "entity"):
    """MaintenanceVisit and InvoiceLine carry only id and created_at."""
    assert_common_fields(data, entity)
    assert "updated_at" not in data, f"{entity} must not expose updated_at"
    assert "version" not in data, f"{entity} must not expose version"


def assert_account(data: dict):
    assert_versioned_fields(data, "Account")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["billing_jurisdiction_code"] in (
        "JUR_ALPHA",
        "JUR_BRAVO",
        "JUR_CHARLIE",
        "JUR_DELTA",
    )
    assert "@" in data["contact_email"]
    assert data["membership_tier"] in ("NONE", "SELECT", "PREMIER")
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["lifetime_invoiced_cents"], int)
    assert isinstance(data["lifetime_paid_cents"], int)
    assert isinstance(data["credit_hold"], bool)


def assert_property(data: dict):
    assert_versioned_fields(data, "Property")
    assert data["service_zone"] in ("ZONE_1", "ZONE_2", "ZONE_3", "OUT_OF_AREA")
    assert 1 <= data["household_size"] <= 12


def assert_well_profile(data: dict):
    assert_versioned_fields(data, "WellProfile")
    assert data["well_type"] in ("DRILLED", "DRIVEN", "DUG")
    assert data["duty_cycle_class"] in ("LOW", "MODERATE", "HIGH")
    assert data["potability_status"] in ("UNKNOWN", "SAFE", "ADVISORY", "UNSAFE")
    assert data["treatment_media"] in ("NONE", "SEDIMENT", "CARBON", "SOFTENER_RESIN")


def assert_maintenance_visit(data: dict):
    assert_no_version_fields(data, "MaintenanceVisit")
    assert data["visit_kind"] in (
        "SALT_AND_FILTER",
        "FILTER_ONLY",
        "SALT_ONLY",
        "SERVICE_ONLY",
    )


def assert_invoice_line(data: dict):
    assert_no_version_fields(data, "InvoiceLine")
    assert isinstance(data["sequence_no"], int)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["description"], str) and data["description"]


def assert_money(actual, expected, field: str):
    """Money is carried in whole cents as integers."""
    assert isinstance(actual, int), f"{field} must be an integer number of cents"
    assert actual == expected, f"{field}: expected {expected} cents, got {actual}"


def assert_close(actual, expected, field: str, tolerance: float = 0.005):
    assert actual is not None, f"{field}: expected {expected}, got null"
    assert abs(float(actual) - float(expected)) <= tolerance, (
        f"{field}: expected {expected}, got {actual}"
    )


def assert_ids_equal(actual, expected, field: str):
    assert actual == expected, f"{field}: expected {expected}, got {actual}"


def ids_of(rows) -> list:
    return [row["id"] for row in rows]


def find_by_id(rows, row_id: str) -> dict:
    for row in rows:
        if row.get("id") == row_id:
            return row
    raise AssertionError(f"No row with id {row_id} in {ids_of(rows)}")


def find_where(rows, **criteria) -> dict:
    for row in rows:
        if all(row.get(key) == value for key, value in criteria.items()):
            return row
    raise AssertionError(f"No row matching {criteria} among {len(rows)} rows")


def assert_pagination_meta(meta: dict, limit: int, offset: int, total_count: int):
    assert meta.get("limit") == limit, f"meta.limit: expected {limit}, got {meta.get('limit')}"
    assert meta.get("offset") == offset, (
        f"meta.offset: expected {offset}, got {meta.get('offset')}"
    )
    assert meta.get("total_count") == total_count, (
        f"meta.total_count: expected {total_count}, got {meta.get('total_count')}"
    )
    expected_has_more = (offset + limit) < total_count
    assert meta.get("has_more") is expected_has_more, (
        f"meta.has_more: expected {expected_has_more}, got {meta.get('has_more')}"
    )
