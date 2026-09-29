"""Entity-level and invariant-level assertion helpers.

Everything here checks a rule the PRD states about response shape, audit
fields, monetary precision, or the waiver-ledger identity of §2.9.
"""

from typing import Any, Dict, Iterable, List

import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
)

# ---------------------------------------------------------------------------
# Audit fields (PRD §2.4)
# ---------------------------------------------------------------------------


def assert_audit_fields(entity: Dict[str, Any], expected_version: int = None) -> None:
    """Every resource carries a prefix-free UUID `id`, an ISO 8601 `created_at`,
    an `updated_at` and an integer `version` starting at 1."""
    assert is_valid_uuid(entity["id"]), f"id is not a bare UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert is_iso8601_timestamp(entity["updated_at"]), entity["updated_at"]
    assert isinstance(entity["version"], int)
    assert entity["version"] >= 1
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_append_only_fields(entity: Dict[str, Any]) -> None:
    """A `NegotiationRound` carries only `id` and `created_at` — it has neither
    `updated_at` nor `version` (PRD §2.4)."""
    assert is_valid_uuid(entity["id"]), f"id is not a bare UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert "updated_at" not in entity, "NegotiationRound must not carry updated_at"
    assert "version" not in entity, "NegotiationRound must not carry version"


def assert_timestamp_with_millis(value: str) -> None:
    """ISO 8601 UTC instant with three fractional digits (PRD §2.2, §2.4)."""
    assert isinstance(value, str), value
    assert is_iso8601_timestamp(value), value
    assert len(value) == 24 and value.endswith("Z") and value[19] == ".", (
        f"expected an ISO 8601 UTC instant with three fractional digits: {value!r}"
    )


# ---------------------------------------------------------------------------
# Generic field comparison
# ---------------------------------------------------------------------------


def assert_fields(entity: Dict[str, Any], **expected: Any) -> None:
    """Assert each named field equals its expected value, with float fields
    compared at the four-decimal resolution PRD §2.7 allows."""
    for field, want in expected.items():
        assert field in entity, f"missing field {field!r} in {sorted(entity)}"
        got = entity[field]
        if isinstance(want, float):
            assert got == pytest.approx(want, abs=0.00005), (
                f"{field}: expected {want}, got {got}"
            )
        else:
            assert got == want, f"{field}: expected {want!r}, got {got!r}"


def assert_cents(actual: int, expected: int, label: str = "amount") -> None:
    """Monetary quantities are exact integers of cents (PRD §2.7)."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_pct(actual: Any, expected: float, label: str = "percentage") -> None:
    """Fractions carry up to four decimal places (PRD §2.7)."""
    assert actual == pytest.approx(expected, abs=0.00005), (
        f"{label}: expected {expected}, got {actual}"
    )


# ---------------------------------------------------------------------------
# List endpoints (PRD §2.3)
# ---------------------------------------------------------------------------


def assert_list_total(response, expected_total: int) -> List[Dict[str, Any]]:
    """`total_count` is the size of the full filtered result set before the
    window is applied (PRD §2.3). Returns the page of rows."""
    rows, meta = validate_paginated(response)
    assert meta["total_count"] == expected_total, (
        f"expected total_count {expected_total}, got {meta['total_count']}"
    )
    return rows


def assert_page(
    response,
    expected_total: int,
    expected_rows: int,
    expected_limit: int = None,
    expected_offset: int = None,
    expected_has_more: bool = None,
) -> List[Dict[str, Any]]:
    rows, meta = validate_paginated(response)
    assert meta["total_count"] == expected_total, meta
    assert len(rows) == expected_rows, f"expected {expected_rows} rows, got {len(rows)}"
    if expected_limit is not None:
        assert meta["limit"] == expected_limit, meta
    if expected_offset is not None:
        assert meta["offset"] == expected_offset, meta
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more, meta
    return rows


def rows_by_seq_index(rows: Iterable[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    return {row["seq_index"]: row for row in rows}


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------

QUALIFYING_RETURN_STATUSES = ("FILED", "ASSESSED", "SETTLED")


def assert_waiver_ledger_identity(
    agreement: Dict[str, Any], returns: Iterable[Dict[str, Any]]
) -> None:
    """PRD §2.9: summed across the agreement's qualifying returns, gross penalty
    plus gross interest equals the agreement's `waived_amount_cents` plus the
    summed payable penalty and payable interest. Only meaningful while the
    agreement's `status` is not `BREACHED`."""
    assert agreement["status"] != "BREACHED", (
        "the ledger identity is stated for agreements not in BREACHED status"
    )
    qualifying = [r for r in returns if r["status"] in QUALIFYING_RETURN_STATUSES]
    gross = sum(r["gross_penalty_cents"] + r["gross_interest_cents"] for r in qualifying)
    payable = sum(
        r["payable_penalty_cents"] + r["payable_interest_cents"] for r in qualifying
    )
    assert gross == agreement["waived_amount_cents"] + payable, (
        f"waiver ledger identity broken: gross={gross}, "
        f"waived={agreement['waived_amount_cents']}, payable={payable}"
    )


def assert_error_data_shape(error_data: Dict[str, Any]) -> None:
    """PRD §2.2: the error `data` object holds exactly `error_id` and `message`."""
    assert isinstance(error_data.get("error_id"), str)
    assert isinstance(error_data.get("message"), str)
    assert error_data["message"].strip() != ""
    assert set(error_data.keys()) == {"error_id", "message"}, (
        f"error data carries unexpected keys: {sorted(error_data)}"
    )


def assert_response_envelope(body: Dict[str, Any], expected_type: str) -> None:
    """PRD §2.2: `api_request_id` starts with `req_`, `api_request_timestamp` is
    an ISO 8601 UTC timestamp with three fractional digits."""
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), meta["api_request_id"]
    assert_timestamp_with_millis(meta["api_request_timestamp"])
    assert body["response_type"] == expected_type, body["response_type"]
