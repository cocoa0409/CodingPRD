"""
Domain assertion helpers.

These wrap the generic helpers from ``prd_bench_local_runner.testing`` with the
invariants the PRD states explicitly: the four common fields of §2.4, the
envelope metadata of §2.2, the rounding disciplines of §2.6, the commitment
conservation identities of §2.11 and the pagination metadata of §2.3.
"""

from typing import Any, Dict, List, Optional, Sequence

import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .api_client import canonical_iso

# ─── Timestamps ───────────────────────────────────────────────────────────


def assert_iso_equal(actual: Optional[str], expected: Optional[str], field: str = "timestamp") -> None:
    """
    Compare two ISO 8601 UTC instants for equality of instant, not of spelling.

    PRD §2.4 stores timestamps with three fractional digits while PRD §2.5
    accepts client instants written without any, so both sides are canonicalised
    before comparison.
    """
    assert canonical_iso(actual) == canonical_iso(expected), (
        f"{field}: expected instant {expected!r}, got {actual!r}"
    )


def assert_three_fractional_digits(timestamp: str, field: str = "timestamp") -> None:
    """PRD §2.4: 'an ISO 8601 UTC timestamp with exactly three fractional-second digits'."""
    assert isinstance(timestamp, str), f"{field} must be a string, got {timestamp!r}"
    assert is_iso8601_timestamp(timestamp), f"{field} is not ISO 8601 UTC: {timestamp!r}"
    assert "." in timestamp, f"{field} carries no fractional part: {timestamp!r}"
    fraction = timestamp.split(".", 1)[1].rstrip("Z")
    assert len(fraction) == 3, (
        f"{field} must carry exactly three fractional-second digits, got {timestamp!r}"
    )


# ─── Envelope and common fields ───────────────────────────────────────────


def assert_envelope(response) -> Dict[str, Any]:
    """
    PRD §2.2: 'The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`.'
    """
    body = response.json()
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str), "meta.api_request_id must be a string"
    assert meta["api_request_id"].startswith("req_"), (
        f"meta.api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert_three_fractional_digits(meta["api_request_timestamp"], "meta.api_request_timestamp")
    return body


def assert_common_fields(data: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """
    PRD §2.4: every resource carries ``id`` (a bare UUID), ``created_at``,
    ``updated_at`` and ``version``.
    """
    assert is_valid_uuid(data["id"]), (
        f"id must be a bare UUID with no prefix, got {data['id']!r}"
    )
    assert_three_fractional_digits(data["created_at"], "created_at")
    assert_three_fractional_digits(data["updated_at"], "updated_at")
    assert isinstance(data["version"], int), "version must be an integer"
    if expected_version is not None:
        assert data["version"] == expected_version, (
            f"expected version {expected_version}, got {data['version']}"
        )


def assert_created_fresh(data: Dict[str, Any]) -> None:
    """PRD §2.4: 'version ... starts at 1' and 'At creation it equals `created_at`'."""
    assert_common_fields(data, expected_version=1)
    assert_iso_equal(data["updated_at"], data["created_at"], "updated_at")


# ─── Field comparison ─────────────────────────────────────────────────────


def assert_fields(data: Dict[str, Any], **expected: Any) -> None:
    """
    Assert a set of field values on a resource payload.

    Integers and strings are compared exactly. Floats are compared with
    ``pytest.approx(abs=0.01)`` because the PRD's ratio and score fields carry
    limited decimal precision (PRD §2.6).
    """
    for field, want in expected.items():
        assert field in data, f"missing field {field!r} in {sorted(data)}"
        got = data[field]
        if isinstance(want, float):
            assert got == pytest.approx(want, abs=0.01), (
                f"{field}: expected {want}, got {got}"
            )
        else:
            assert got == want, f"{field}: expected {want!r}, got {got!r}"


def assert_nulls(data: Dict[str, Any], *fields: str) -> None:
    """Assert every named field is present and null."""
    for field in fields:
        assert field in data, f"missing field {field!r} in {sorted(data)}"
        assert data[field] is None, f"{field}: expected null, got {data[field]!r}"


def assert_ratio(actual: Any, expected: float, field: str = "ratio") -> None:
    """PRD §2.6: ratios are held to four decimal places, rounded half up."""
    assert actual is not None, f"{field}: expected {expected}, got null"
    assert float(actual) == pytest.approx(expected, abs=0.00005), (
        f"{field}: expected {expected:.4f}, got {actual}"
    )


def assert_score(actual: Any, expected: float, field: str = "mission_impact_score") -> None:
    """PRD §2.6: 'Round half up to two decimal places governs `mission_impact_score`'."""
    assert actual is not None, f"{field}: expected {expected}, got null"
    assert float(actual) == pytest.approx(expected, abs=0.005), (
        f"{field}: expected {expected:.2f}, got {actual}"
    )


def assert_integer_cents(data: Dict[str, Any], *fields: str) -> None:
    """
    PRD §2.6: 'Money is carried in integer cents everywhere the field name ends
    in `_cents`, and those fields are exchanged as JSON integers, never as
    strings and never as decimals.'
    """
    for field in fields:
        value = data[field]
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{field} must be a JSON integer, got {type(value).__name__} {value!r}"
        )


# ─── Loan invariants (PRD §2.11) ──────────────────────────────────────────


def assert_commitment_conservation(loan: Dict[str, Any]) -> None:
    """
    PRD §2.11: 'the sum of `disbursed_principal_cents`,
    `undrawn_commitment_cents` and `cancelled_commitment_cents` must always
    equal `principal_cents`.'
    """
    total = (
        loan["disbursed_principal_cents"]
        + loan["undrawn_commitment_cents"]
        + loan["cancelled_commitment_cents"]
    )
    assert total == loan["principal_cents"], (
        "commitment conservation violated: "
        f"{loan['disbursed_principal_cents']} + {loan['undrawn_commitment_cents']} + "
        f"{loan['cancelled_commitment_cents']} == {total} != {loan['principal_cents']}"
    )


def assert_outstanding_identity(loan: Dict[str, Any]) -> None:
    """
    PRD §2.11: '`outstanding_principal_cents` is always
    `disbursed_principal_cents` reduced by `principal_repaid_cents` and reduced
    again by `forgiven_principal_cents`.'
    """
    expected = (
        loan["disbursed_principal_cents"]
        - loan["principal_repaid_cents"]
        - loan["forgiven_principal_cents"]
    )
    assert loan["outstanding_principal_cents"] == expected, (
        "outstanding principal identity violated: expected "
        f"{expected}, got {loan['outstanding_principal_cents']}"
    )


def assert_free_commitment(loan: Dict[str, Any], expected: int) -> None:
    """
    PRD §2.11: 'The quantity every sizing rule calls the free commitment is
    therefore `undrawn_commitment_cents` less `reserved_draw_cents`.'
    """
    free = loan["undrawn_commitment_cents"] - loan["reserved_draw_cents"]
    assert free == expected, f"free commitment: expected {expected}, got {free}"


def assert_loan_ledger(loan: Dict[str, Any], **expected: Any) -> None:
    """Assert named loan ledger figures and then re-check both §2.11 identities."""
    assert_fields(loan, **expected)
    assert_commitment_conservation(loan)
    assert_outstanding_identity(loan)


# ─── Pagination (PRD §2.3) ────────────────────────────────────────────────


def assert_pagination_meta(
    meta: Dict[str, Any],
    total_count: Optional[int] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    """PRD §2.3: list responses report `limit`, `offset`, `total_count` and `has_more`."""
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"total_count: expected {total_count}, got {meta['total_count']}"
        )
    if limit is not None:
        assert meta["limit"] == limit, f"limit: expected {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"offset: expected {offset}, got {meta['offset']}"
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"has_more: expected {has_more}, got {meta['has_more']}"
        )


def assert_id_order(rows: List[Dict[str, Any]], expected_ids: Sequence[str]) -> None:
    """Assert a list projection returns exactly these ids in exactly this order."""
    got = [row["id"] for row in rows]
    assert got == list(expected_ids), f"expected order {list(expected_ids)}, got {got}"
