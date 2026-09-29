"""
Domain assertions for the Ocean Cargo Insurance API.

These wrap the framework's structural helpers with the conventions this API
declares: money carried to two decimals, rates per mille to four, ratios to
six, identifiers as bare UUIDs, timestamps as ISO 8601 UTC, and a version that
starts at 1 and rises by exactly one per write.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from .api_client import ApiClient
from .test_users import UNDERWRITER
from .types import ApiResponse, Headers, JsonDict, JsonList


# ---------------------------------------------------------------------------
# Numeric comparisons
# ---------------------------------------------------------------------------
def assert_money(actual: Any, expected: float, label: str = "amount") -> None:
    """Assert a monetary field equals `expected` to the cent."""
    assert actual is not None, f"{label} is missing"
    assert round(float(actual), 2) == round(float(expected), 2), (
        f"{label}: expected {expected:.2f}, got {actual}"
    )


def assert_rate(actual: Any, expected: float, places: int = 4,
                label: str = "rate") -> None:
    """Assert a rate field equals `expected` at the declared precision."""
    assert actual is not None, f"{label} is missing"
    assert round(float(actual), places) == round(float(expected), places), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_ratio(actual: Any, expected: float, label: str = "ratio") -> None:
    """Assert a six-decimal ratio field equals `expected`."""
    assert_rate(actual, expected, places=6, label=label)


def assert_money_precision(value: Any, label: str = "amount") -> None:
    """Assert a monetary field carries no more than two decimal places."""
    assert value is not None, f"{label} is missing"
    as_float = float(value)
    assert round(as_float, 2) == as_float, (
        f"{label} carries more than two decimal places: {value}"
    )


# ---------------------------------------------------------------------------
# Instants
# ---------------------------------------------------------------------------
def parse_instant(value: Any, label: str = "instant") -> datetime:
    """
    Parse an ISO 8601 UTC timestamp into the moment it names.

    The API declares its timestamps as ISO 8601 UTC instants; the number of
    fractional digits a field is rendered with is a spelling detail, so two
    spellings of the same moment must compare equal.
    """
    assert value is not None, f"{label} is missing"
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def assert_instant(actual: Any, expected: Any, label: str = "instant") -> None:
    """Assert a timestamp field names exactly the expected instant."""
    assert parse_instant(actual, label) == parse_instant(expected, label), (
        f"{label}: expected {expected}, got {actual}"
    )


# ---------------------------------------------------------------------------
# Common properties
# ---------------------------------------------------------------------------
def assert_common_fields(row: JsonDict, expected_version: Optional[int] = None,
                         label: str = "row") -> None:
    """
    Assert the four properties every versioned row carries: a bare UUID `id`,
    ISO 8601 `created_at` and `updated_at`, and an integer `version`.
    """
    assert is_valid_uuid(row.get("id", "")), (
        f"{label}.id is not a bare UUID: {row.get('id')!r}"
    )
    assert is_iso8601_timestamp(row.get("created_at", "")), (
        f"{label}.created_at is not ISO 8601: {row.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(row.get("updated_at", "")), (
        f"{label}.updated_at is not ISO 8601: {row.get('updated_at')!r}"
    )
    assert isinstance(row.get("version"), int), (
        f"{label}.version must be an integer, got {row.get('version')!r}"
    )
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"{label}.version: expected {expected_version}, got {row['version']}"
        )


def assert_append_only_fields(row: JsonDict, label: str = "row") -> None:
    """
    Assert an append-only row carries only `id` and `created_at` from the common
    properties — no `updated_at` and no `version`.
    """
    assert is_valid_uuid(row.get("id", "")), (
        f"{label}.id is not a bare UUID: {row.get('id')!r}"
    )
    assert is_iso8601_timestamp(row.get("created_at", "")), (
        f"{label}.created_at is not ISO 8601: {row.get('created_at')!r}"
    )
    assert "updated_at" not in row, f"{label} must not carry updated_at"
    assert "version" not in row, f"{label} must not carry version"


def assert_fields_present(row: JsonDict, field_names: List[str],
                          label: str = "row") -> None:
    """Assert every named field is present in the row."""
    missing = [name for name in field_names if name not in row]
    assert not missing, f"{label} is missing fields: {missing}"


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
def read_certificate(api: ApiClient, certificate_id: str,
                     headers: Headers = UNDERWRITER) -> JsonDict:
    """Fetch a certificate."""
    return validate_success(api.get_certificate(certificate_id, headers))


def read_policy(api: ApiClient, policy_id: str,
                headers: Headers = UNDERWRITER) -> JsonDict:
    """Fetch an open cover."""
    return validate_success(api.get_open_policy(policy_id, headers))


def read_vessel(api: ApiClient, vessel_id: str,
                headers: Headers = UNDERWRITER) -> JsonDict:
    """Fetch a hull."""
    return validate_success(api.get_vessel(vessel_id, headers))


def read_port(api: ApiClient, port_id: str,
              headers: Headers = UNDERWRITER) -> JsonDict:
    """Fetch a port."""
    return validate_success(api.get_port(port_id, headers))


def read_claim_file(api: ApiClient, claim_id: str, headers: Headers) -> JsonDict:
    """Fetch a claim file."""
    return validate_success(api.get_claim_file(claim_id, headers))


def read_declaration(api: ApiClient, declaration_id: str,
                     headers: Headers) -> JsonDict:
    """Fetch a premium declaration."""
    return validate_success(api.get_premium_declaration(declaration_id, headers))


def read_survey_order(api: ApiClient, order_id: str, headers: Headers) -> JsonDict:
    """Fetch a survey order."""
    return validate_success(api.get_survey_order(order_id, headers))


def read_surveyor(api: ApiClient, surveyor_id: str, headers: Headers) -> JsonDict:
    """Fetch a panel surveyor."""
    return validate_success(api.get_surveyor(surveyor_id, headers))


def read_ga_event(api: ApiClient, ga_event_id: str, headers: Headers) -> JsonDict:
    """Fetch a general average event."""
    return validate_success(api.get_ga_event(ga_event_id, headers))


def read_ga_posting(api: ApiClient, posting_id: str, headers: Headers) -> JsonDict:
    """Fetch a general average security posting."""
    return validate_success(api.get_ga_security_posting(posting_id, headers))


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------
def assert_total_count(response: ApiResponse, expected: int,
                       label: str = "collection") -> JsonList:
    """Assert a listing reports `expected` matching rows. Returns the page."""
    rows, meta = validate_paginated(response)
    assert meta["total_count"] == expected, (
        f"{label}: expected total_count {expected}, got {meta['total_count']}"
    )
    return rows


def assert_ids_in_order(rows: JsonList, expected_ids: List[str],
                        label: str = "collection") -> None:
    """Assert the page carries exactly these identifiers, in this order."""
    actual = [row["id"] for row in rows]
    assert actual == expected_ids, (
        f"{label}: expected ids {expected_ids}, got {actual}"
    )


def assert_amounts(row: JsonDict, expectations: Dict[str, float],
                   label: str = "row") -> None:
    """Assert several monetary fields of one row in a single call."""
    for field_name, expected in expectations.items():
        assert_money(row.get(field_name), expected, f"{label}.{field_name}")


def collect_ids(rows: JsonList) -> List[str]:
    """Extract the identifiers of a page of rows."""
    return [row["id"] for row in rows]


def find_row(rows: JsonList, **match: Any) -> JsonDict:
    """Return the single row matching every keyword condition."""
    hits = [row for row in rows
            if all(row.get(key) == value for key, value in match.items())]
    assert len(hits) == 1, (
        f"Expected exactly one row matching {match}, found {len(hits)}"
    )
    return hits[0]


def data_of(response: ApiResponse) -> JsonDict:
    """Validate a successful write and return its data object."""
    return get_success_data(response)
