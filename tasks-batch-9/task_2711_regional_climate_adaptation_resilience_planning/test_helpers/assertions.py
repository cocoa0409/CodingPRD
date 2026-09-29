"""Domain assertions expressed in the vocabulary of the PRD.

Each helper carries the descriptive failure message the tests rely on, so a red
run names the rule that broke rather than the raw comparison that failed.
"""

import re
from decimal import Decimal
from typing import Any, Dict, Iterable, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# PRD 2.4: "exactly three fractional digits ... 2026-08-01T00:00:00.000Z"
_MILLIS_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def assert_millisecond_utc_timestamp(value: Any, label: str) -> None:
    """PRD 2.4 stamps every timestamp with exactly three fractional digits."""
    assert isinstance(value, str), f"{label} should be an ISO 8601 string, got {value!r}"
    assert _MILLIS_UTC.match(value), (
        f"{label} must be an ISO 8601 UTC instant with exactly three fractional "
        f"digits, got {value!r}"
    )


def assert_identity_fields(row: Dict[str, Any], label: str) -> None:
    """PRD 2.4: server-minted UUID plus creation and update stamps and a version."""
    assert is_valid_uuid(row.get("id")), f"{label}.id should be a server-minted UUID, got {row.get('id')!r}"
    assert_millisecond_utc_timestamp(row.get("created_at"), f"{label}.created_at")
    assert_millisecond_utc_timestamp(row.get("updated_at"), f"{label}.updated_at")
    assert row.get("version") == 1 or isinstance(row.get("version"), int), (
        f"{label}.version should be an integer, got {row.get('version')!r}"
    )


def assert_fresh_version(row: Dict[str, Any], label: str) -> None:
    """PRD 2.4: `version` "starts at 1 on creation"."""
    assert row.get("version") == 1, (
        f"{label}.version should start at 1 on creation, got {row.get('version')!r}"
    )


def assert_link_carries_no_mutable_identity(row: Dict[str, Any]) -> None:
    """PRD 2.4: a link "has no `updated_at` and no `version`"."""
    assert is_valid_uuid(row.get("id")), f"link.id should be a server-minted UUID, got {row.get('id')!r}"
    assert_millisecond_utc_timestamp(row.get("created_at"), "link.created_at")
    assert "updated_at" not in row or row.get("updated_at") is None, (
        "a project-to-asset link has no updated_at, but the response carried "
        f"{row.get('updated_at')!r}"
    )
    assert "version" not in row or row.get("version") is None, (
        "a project-to-asset link has no version, but the response carried "
        f"{row.get('version')!r}"
    )


def assert_version_is(row: Dict[str, Any], expected: int, label: str) -> None:
    assert row.get("version") == expected, (
        f"{label}.version should read {expected} after the writes performed, got "
        f"{row.get('version')!r}"
    )


def assert_decimal(actual: Any, expected: str, label: str) -> None:
    """Compare a decimal-valued response field against its exact expected value."""
    assert actual is not None, f"{label} should be present, got None"
    assert Decimal(str(actual)) == Decimal(expected), (
        f"{label} should be exactly {expected}, got {actual!r}"
    )


def assert_approx(actual: Any, expected: float, label: str, abs_tol: float = 0.01) -> None:
    assert actual is not None, f"{label} should be present, got None"
    assert float(actual) == pytest.approx(expected, abs=abs_tol), (
        f"{label} should be {expected}, got {actual!r}"
    )


def assert_fields(row: Dict[str, Any], expected: Dict[str, Any], label: str) -> None:
    """Assert a batch of exact field values, reporting every mismatch at once."""
    mismatches = []
    for key, want in expected.items():
        got = row.get(key)
        if isinstance(want, Decimal) or (
            isinstance(want, float) and got is not None
        ):
            ok = Decimal(str(got)) == Decimal(str(want))
        else:
            ok = got == want
        if not ok:
            mismatches.append(f"{key}: expected {want!r}, got {got!r}")
    assert not mismatches, f"{label} field mismatches: " + "; ".join(mismatches)


def assert_all_null(row: Dict[str, Any], field_names: Iterable[str], label: str) -> None:
    non_null = {name: row.get(name) for name in field_names if row.get(name) is not None}
    assert not non_null, f"{label} should still read null for {non_null}"


def assert_project_dimensions(
    project: Dict[str, Any],
    screening: Optional[str] = None,
    analysis: Optional[str] = None,
    program: Optional[str] = None,
    implementation: Optional[str] = None,
) -> None:
    """PRD 3.5: a project carries four independent state dimensions on one row."""
    expected = {}
    if screening is not None:
        expected["screening_status"] = screening
    if analysis is not None:
        expected["analysis_status"] = analysis
    if program is not None:
        expected["program_status"] = program
    if implementation is not None:
        expected["implementation_status"] = implementation
    assert_fields(project, expected, "project")


def assert_program_conservation(program: Dict[str, Any]) -> None:
    """PRD 2.8: committed_cents plus available_cents equals authorized_cents."""
    committed = program["committed_cents"]
    available = program["available_cents"]
    authorized = program["authorized_cents"]
    assert committed + available == authorized, (
        "the capital program ledger must satisfy committed_cents + available_cents "
        f"== authorized_cents, got {committed} + {available} != {authorized}"
    )


def assert_pact_conservation(pact: Dict[str, Any]) -> None:
    """PRD 2.8: reserved_units plus free_units equals pledged_units."""
    reserved = pact["reserved_units"]
    free = pact["free_units"]
    pledged = pact["pledged_units"]
    assert reserved + free == pledged, (
        "the mutual aid pact ledger must satisfy reserved_units + free_units == "
        f"pledged_units, got {reserved} + {free} != {pledged}"
    )


def assert_success_envelope(body: Dict[str, Any], expected_response_type: str) -> None:
    """PRD 2.2 envelope: `data`, `meta.api_request_id`, `response_type`."""
    assert set(body.keys()) >= {"data", "meta", "response_type"}, (
        f"a success envelope must carry data, meta and response_type, got {sorted(body.keys())}"
    )
    assert body["response_type"] == expected_response_type, (
        f"response_type should read {expected_response_type!r}, got {body['response_type']!r}"
    )
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"].startswith("req_"), (
        f"meta.api_request_id must be a string beginning with 'req_', got {meta.get('api_request_id')!r}"
    )
    assert_millisecond_utc_timestamp(meta.get("api_request_timestamp"), "meta.api_request_timestamp")


def assert_error_envelope(body: Dict[str, Any], expected_error_id: str) -> None:
    """PRD 2.2: an error `data` holds only `error_id` and `message`."""
    assert body.get("response_type") == "error", (
        f"a failure must set response_type to 'error', got {body.get('response_type')!r}"
    )
    data = body.get("data") or {}
    assert set(data.keys()) == {"error_id", "message"}, (
        f"an error data object must hold only error_id and message, got {sorted(data.keys())}"
    )
    assert data["error_id"] == expected_error_id, (
        f"error_id should read {expected_error_id!r}, got {data['error_id']!r}"
    )
    assert isinstance(data["message"], str) and data["message"], (
        "an error message must be a non-empty string"
    )
    meta = body.get("meta") or {}
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, (
        "an error meta object contains only api_request_id and api_request_timestamp, "
        f"got {sorted(meta.keys())}"
    )


def assert_sorted_by_created_at(rows: Iterable[Dict[str, Any]]) -> None:
    """PRD 2.3: collections are always sorted by created_at ascending."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), (
        f"a collection must be sorted by created_at ascending, got {stamps}"
    )


def assert_iso8601(value: Any, label: str) -> None:
    assert value is not None and is_iso8601_timestamp(value), (
        f"{label} should be an ISO 8601 instant, got {value!r}"
    )
