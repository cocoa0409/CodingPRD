"""Domain assertion helpers layered on top of the framework validators.

The framework already checks envelope shape and error identity. What is added
here is vocabulary: the tolerance conventions of PRD §2.6, the common-field
promise of PRD §2.4 including the account-signal exemption, and the two
conserved-counter invariants of PRD §2.10 that must hold after every write.
"""

from typing import Any, Dict, Iterable, List, Optional

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

# PRD §2.6 fixes scores at exactly two decimal places, so a hundredth of a point
# is the widest tolerance any comparison here needs.
SCORE_TOLERANCE = 0.01
RATIO_TOLERANCE = 0.0001


# ---------------------------------------------------------------------------
# Scalar comparisons
# ---------------------------------------------------------------------------


def assert_score(actual: Any, expected: float, field: str = "score") -> None:
    """Compare a two-decimal score from PRD §2.6."""
    assert actual is not None, f"{field} is missing"
    assert float(actual) == pytest.approx(expected, abs=SCORE_TOLERANCE), (
        f"{field}: expected {expected:.2f}, got {actual}"
    )


def assert_cents(actual: Any, expected: int, field: str = "amount_cents") -> None:
    """Compare an integer-cents money field from PRD §2.6."""
    assert actual is not None, f"{field} is missing"
    assert int(actual) == expected, f"{field}: expected {expected}, got {actual}"


def assert_field(data: Dict[str, Any], field: str, expected: Any) -> None:
    """Assert one field of a row equals an expected value."""
    assert field in data, f"{field} is missing from {sorted(data)}"
    assert data[field] == expected, (
        f"{field}: expected {expected!r}, got {data[field]!r}"
    )


def assert_fields(data: Dict[str, Any], expected: Dict[str, Any]) -> None:
    """Assert several exact-valued fields of a row at once."""
    for field, value in expected.items():
        assert_field(data, field, value)


def assert_scores(data: Dict[str, Any], expected: Dict[str, float]) -> None:
    """Assert several two-decimal score fields of a row at once."""
    for field, value in expected.items():
        assert field in data, f"{field} is missing from {sorted(data)}"
        assert_score(data[field], value, field)


def assert_cents_fields(data: Dict[str, Any], expected: Dict[str, int]) -> None:
    """Assert several integer-cents fields of a row at once."""
    for field, value in expected.items():
        assert field in data, f"{field} is missing from {sorted(data)}"
        assert_cents(data[field], value, field)


def assert_null(data: Dict[str, Any], *fields: str) -> None:
    """Assert every named field is present and null."""
    for field in fields:
        assert field in data, f"{field} is missing from {sorted(data)}"
        assert data[field] is None, f"{field}: expected null, got {data[field]!r}"


def assert_present(data: Dict[str, Any], *fields: str) -> None:
    """Assert every named field is present in the row, whatever its value."""
    missing = [field for field in fields if field not in data]
    assert not missing, f"missing fields {missing} in {sorted(data)}"


# ---------------------------------------------------------------------------
# Common fields (PRD §2.4)
# ---------------------------------------------------------------------------


def assert_common_fields(
    data: Dict[str, Any], expected_version: Optional[int] = None
) -> None:
    """Assert the `id`, `created_at`, `updated_at` and `version` of PRD §2.4."""
    assert is_valid_uuid(data.get("id")), f"id is not a bare UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at")), (
        f"created_at is not ISO 8601: {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at")), (
        f"updated_at is not ISO 8601: {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"version is not an integer: {data.get('version')!r}"
    )
    if expected_version is not None:
        assert data["version"] == expected_version, (
            f"version: expected {expected_version}, got {data['version']}"
        )


def assert_signal_common_fields(data: Dict[str, Any]) -> None:
    """Assert the reduced common-field set an account signal carries.

    PRD §2.4 exempts account signals from `updated_at` and `version`, so their
    absence is part of the contract rather than an omission.
    """
    assert is_valid_uuid(data.get("id")), f"id is not a bare UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at")), (
        f"created_at is not ISO 8601: {data.get('created_at')!r}"
    )
    assert "version" not in data, "an account signal must not carry version"
    assert "updated_at" not in data, "an account signal must not carry updated_at"


# ---------------------------------------------------------------------------
# Envelope and listing shape (PRD §2.2, §2.3)
# ---------------------------------------------------------------------------


def assert_created(response: Any) -> Dict[str, Any]:
    """Assert a 201 creation and return its `data` block."""
    validate_success(response, expected_status=201)
    body = response.json()
    assert body.get("response_type") == "object", (
        f"response_type: expected 'object', got {body.get('response_type')!r}"
    )
    return body["data"]


def assert_ok(response: Any) -> Dict[str, Any]:
    """Assert a 200 single-object response and return its `data` block."""
    validate_success(response, expected_status=200)
    body = response.json()
    assert body.get("response_type") == "object", (
        f"response_type: expected 'object', got {body.get('response_type')!r}"
    )
    return body["data"]


def assert_page(
    response: Any,
    expected_total: Optional[int] = None,
    expected_has_more: Optional[bool] = None,
    expected_limit: Optional[int] = None,
    expected_offset: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Assert a listing envelope and return the rows."""
    rows, meta = validate_paginated(response)
    assert response.json().get("response_type") == "array"
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            f"total_count: expected {expected_total}, got {meta['total_count']}"
        )
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more, (
            f"has_more: expected {expected_has_more}, got {meta['has_more']}"
        )
    if expected_limit is not None:
        assert meta["limit"] == expected_limit
    if expected_offset is not None:
        assert meta["offset"] == expected_offset
    return rows


def assert_created_at_ascending(rows: Iterable[Dict[str, Any]]) -> None:
    """Assert PRD §2.3's default ordering by `created_at` ascending."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows are not created_at ascending: {stamps}"


# ---------------------------------------------------------------------------
# Domain invariants (PRD §2.10)
# ---------------------------------------------------------------------------


def assert_capacity_conserved(csm: Dict[str, Any]) -> None:
    """Assert the CSM capacity identity of PRD §2.10.

    `capacity_units_available` must equal `capacity_units_total` minus
    `capacity_units_committed`, and neither derived figure may go negative.
    """
    total = csm["capacity_units_total"]
    committed = csm["capacity_units_committed"]
    available = csm["capacity_units_available"]
    assert committed >= 0, f"capacity_units_committed is negative: {committed}"
    assert available == total - committed, (
        "capacity identity broken: "
        f"available {available} != total {total} - committed {committed}"
    )


def assert_credit_ledger_non_negative(account: Dict[str, Any]) -> None:
    """Assert both remediation credit counters of PRD §2.10 are non-negative."""
    outstanding = account["remediation_credit_outstanding_cents"]
    settled = account["remediation_credit_settled_cents"]
    assert outstanding >= 0, (
        f"remediation_credit_outstanding_cents is negative: {outstanding}"
    )
    assert settled >= 0, f"remediation_credit_settled_cents is negative: {settled}"


def assert_credit_ledger(
    account: Dict[str, Any], outstanding_cents: int, settled_cents: int
) -> None:
    """Assert exact values for the two credit counters of PRD §2.10."""
    assert_credit_ledger_non_negative(account)
    assert_cents(
        account["remediation_credit_outstanding_cents"],
        outstanding_cents,
        "remediation_credit_outstanding_cents",
    )
    assert_cents(
        account["remediation_credit_settled_cents"],
        settled_cents,
        "remediation_credit_settled_cents",
    )


def assert_health_tier_matches_snapshot(account: Dict[str, Any]) -> None:
    """Assert `health_tier` follows the snapshot variant, per PRD §3.2."""
    snapshot = float(account["snapshot_health_score"])
    if snapshot < 50.00:
        expected = "RED"
    elif snapshot < 75.00:
        expected = "AMBER"
    else:
        expected = "GREEN"
    assert account["health_tier"] == expected, (
        f"health_tier {account['health_tier']!r} does not follow "
        f"snapshot_health_score {snapshot:.2f} (expected {expected})"
    )


def assert_variant_delta(summary: Dict[str, Any]) -> None:
    """Assert `variant_delta` is the snapshot figure minus the trailing one."""
    expected = float(summary["snapshot_health_score"]) - float(
        summary["trended_health_score"]
    )
    assert_score(summary["variant_delta"], round(expected, 2), "variant_delta")


def assert_sweep_counts(data: Dict[str, Any], **expected: int) -> None:
    """Assert named counters on the daily-sweep result of PRD §3.9."""
    for field, value in expected.items():
        assert field in data, f"{field} is missing from the sweep result"
        assert data[field] == value, (
            f"{field}: expected {value}, got {data[field]}"
        )


def data_of(response: Any) -> Dict[str, Any]:
    """Return the `data` block of a successful response."""
    return get_success_data(response)
