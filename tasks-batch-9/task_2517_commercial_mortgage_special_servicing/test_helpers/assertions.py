"""Domain assertions for the CMBS Special Servicing API."""

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    ARA_PERCENTAGE_DECIMALS,
    FULL_COMMON_FIELDS,
    IMMUTABLE_COMMON_FIELDS,
    MONEY_DECIMALS,
    MONEY_TOLERANCE,
    PERCENTAGE_TOLERANCE,
    RATE_TOLERANCE,
)
from .types import Json, JsonList


# --------------------------------------------------------------------------
# Money and rate precision
# --------------------------------------------------------------------------
def assert_money(actual, expected, label: str = "amount") -> None:
    """Assert a money field equals the expected value to the cent."""
    assert actual is not None, f"{label} must be present"
    assert actual == pytest.approx(expected, abs=MONEY_TOLERANCE), (
        f"{label}: expected {expected:.2f}, got {actual}"
    )


def assert_money_scale(actual, label: str = "amount") -> None:
    """Assert a money field carries no more than two decimal places."""
    assert actual is not None, f"{label} must be present"
    quantized = round(float(actual), MONEY_DECIMALS)
    assert float(actual) == pytest.approx(quantized, abs=1e-9), (
        f"{label} must be expressed to two decimal places, got {actual}"
    )


def assert_ara_percentage(actual, expected, label: str = "ara_percentage") -> None:
    """Assert an ARA percentage equals the expected value at four decimals."""
    assert actual is not None, f"{label} must be present"
    assert actual == pytest.approx(expected, abs=PERCENTAGE_TOLERANCE), (
        f"{label}: expected {expected:.4f}, got {actual}"
    )
    quantized = round(float(actual), ARA_PERCENTAGE_DECIMALS)
    assert float(actual) == pytest.approx(quantized, abs=1e-9), (
        f"{label} must be expressed to four decimal places, got {actual}"
    )


def assert_rate_pct(actual, expected, label: str = "rate_pct") -> None:
    """Assert a stored rate equals the expected value at six decimals."""
    assert actual is not None, f"{label} must be present"
    assert actual == pytest.approx(expected, abs=RATE_TOLERANCE), (
        f"{label}: expected {expected:.6f}, got {actual}"
    )


# --------------------------------------------------------------------------
# Common fields
# --------------------------------------------------------------------------
def assert_common_fields(row: Json, entity: str = "row") -> None:
    """Assert the four common fields the PRD gives to a versioned row."""
    for field in FULL_COMMON_FIELDS:
        assert field in row, f"{entity} must expose '{field}'"
    assert is_valid_uuid(row["id"]), f"{entity}.id must be a UUID: {row['id']}"
    assert is_iso8601_timestamp(row["created_at"]), (
        f"{entity}.created_at must be ISO-8601: {row['created_at']}"
    )
    assert is_iso8601_timestamp(row["updated_at"]), (
        f"{entity}.updated_at must be ISO-8601: {row['updated_at']}"
    )
    assert isinstance(row["version"], int), f"{entity}.version must be an integer"
    assert row["version"] >= 1, f"{entity}.version starts at 1, got {row['version']}"


def assert_immutable_common_fields(row: Json, entity: str = "row") -> None:
    """Assert the reduced common-field set: id and created_at only."""
    for field in IMMUTABLE_COMMON_FIELDS:
        assert field in row, f"{entity} must expose '{field}'"
    assert is_valid_uuid(row["id"]), f"{entity}.id must be a UUID: {row['id']}"
    assert is_iso8601_timestamp(row["created_at"]), (
        f"{entity}.created_at must be ISO-8601: {row['created_at']}"
    )
    assert "updated_at" not in row, f"{entity} must not carry updated_at"
    assert "version" not in row, f"{entity} must not carry version"


def assert_id_has_no_prefix(row_id: str) -> None:
    """Assert an entity id is a bare UUID with no prefix."""
    assert is_valid_uuid(row_id), f"id must be a bare UUID, got {row_id}"


# --------------------------------------------------------------------------
# Envelope
# --------------------------------------------------------------------------
def assert_request_id_format(meta: Json) -> None:
    """Assert meta.api_request_id carries the declared 'req_' prefix."""
    request_id = meta.get("api_request_id")
    assert isinstance(request_id, str), "meta.api_request_id must be a string"
    assert request_id.startswith("req_"), (
        f"meta.api_request_id must start with 'req_', got {request_id}"
    )


def assert_millisecond_timestamp(value: str, label: str = "timestamp") -> None:
    """Assert a timestamp carries exactly three fractional-second digits and Z."""
    assert isinstance(value, str), f"{label} must be a string"
    assert value.endswith("Z"), f"{label} must end with 'Z', got {value}"
    assert "." in value, f"{label} must carry fractional seconds, got {value}"
    fraction = value.split(".")[-1][:-1]
    assert len(fraction) == 3, (
        f"{label} must carry exactly three fractional digits, got {value}"
    )


# --------------------------------------------------------------------------
# Versioning
# --------------------------------------------------------------------------
def assert_version_is(row: Json, expected: int, entity: str = "row") -> None:
    assert row.get("version") == expected, (
        f"{entity}.version: expected {expected}, got {row.get('version')}"
    )


def assert_version_advanced_by(before: Json, after: Json, delta: int, entity: str = "row") -> None:
    assert after["version"] == before["version"] + delta, (
        f"{entity}.version should advance by {delta}: "
        f"{before['version']} -> {after['version']}"
    )


# --------------------------------------------------------------------------
# Status
# --------------------------------------------------------------------------
def assert_status(row: Json, expected: str, field: str = "status") -> None:
    assert row.get(field) == expected, (
        f"{field}: expected {expected}, got {row.get(field)}"
    )


def assert_fields_null(row: Json, *fields: str) -> None:
    for field in fields:
        assert row.get(field) is None, f"{field} must be null, got {row.get(field)}"


def assert_fields_present(row: Json, *fields: str) -> None:
    for field in fields:
        assert field in row, f"{field} must be present in the response"


# --------------------------------------------------------------------------
# Collections
# --------------------------------------------------------------------------
def ids_of(rows: JsonList) -> list:
    return [row["id"] for row in rows]


def assert_ordered_by(rows: JsonList, field: str, descending: bool = False) -> None:
    values = [row[field] for row in rows]
    expected = sorted(values, reverse=descending)
    assert values == expected, (
        f"rows must be ordered by {field} "
        f"{'DESC' if descending else 'ASC'}: {values}"
    )


def find_by_id(rows: JsonList, row_id: str) -> Json:
    for row in rows:
        if row.get("id") == row_id:
            return row
    raise AssertionError(f"row {row_id} not present in {ids_of(rows)}")


def assert_contains_id(rows: JsonList, row_id: str) -> None:
    assert row_id in ids_of(rows), f"expected {row_id} among {ids_of(rows)}"


def assert_excludes_id(rows: JsonList, row_id: str) -> None:
    assert row_id not in ids_of(rows), f"{row_id} must not appear in {ids_of(rows)}"


# --------------------------------------------------------------------------
# Ledger identities
# --------------------------------------------------------------------------
def assert_controlling_class_identity(trust: Json) -> None:
    """Assert notional == original controlling class balance - total ARA - realized loss."""
    expected = (
        float(trust["original_controlling_class_balance_usd"])
        - float(trust["total_ara_usd"])
        - float(trust["realized_loss_usd"])
    )
    assert_money(
        trust["controlling_class_notional_usd"],
        round(expected, MONEY_DECIMALS),
        "controlling_class_notional_usd",
    )
