"""
Domain assertions for FleetCare.

Two families live here.

*Format helpers* absorb differences that the PRD leaves free. The PRD renders
timestamps with exactly three fractional digits, but an expected instant written in
a test is usually spelled without them, so ``assert_instant`` compares the two as
instants rather than as strings and never turns a formatting difference into a
false business failure.

*Entity helpers* assert the rules the PRD states about a whole row — the four common
properties, the two decimal places on a score, the integer-cents discipline on money,
and the three standing identities.
"""

from decimal import Decimal
from typing import Any, Dict, Optional

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    DECIMAL_TOLERANCE,
    DOWNTIME_GRACE_MINUTES,
    DOWNTIME_RATE_CENTS_PER_HOUR,
    round_half_up,
    round_half_up_cents,
)

# ─── Timestamps ───────────────────────────────────────────────────────────────


def canonical_instant(value: str) -> str:
    """
    Reduce an ISO 8601 UTC instant to a canonical second-precision spelling.

    ``2026-08-15T08:00:00.000Z``, ``2026-08-15T08:00:00Z`` and
    ``2026-08-15T08:00:00.000000Z`` all canonicalise to the same string, so a test
    can write the instant it means without pinning the server's fractional width.
    """
    assert isinstance(value, str), f"Expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    assert text.endswith("Z"), f"Instant must be UTC and end with Z: {value!r}"
    text = text[:-1]
    if "." in text:
        head, frac = text.split(".", 1)
        # A non-zero fractional part is a real difference and must be preserved.
        frac = frac.rstrip("0")
        return f"{head}.{frac}Z" if frac else f"{head}Z"
    return f"{text}Z"


def assert_instant(actual: Optional[str], expected: Optional[str], label: str = "instant") -> None:
    """Assert two ISO 8601 UTC instants name the same moment."""
    if expected is None:
        assert actual is None, f"{label} should be null, got {actual!r}"
        return
    assert actual is not None, f"{label} should be {expected!r}, got null"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )


def assert_iso8601_millis(value: str, label: str = "timestamp") -> None:
    """Assert the value is an ISO 8601 UTC timestamp with three fractional digits."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{label} is not ISO 8601 UTC: {value!r}"
    assert "." in value, f"{label} must carry fractional seconds: {value!r}"
    fraction = value.split(".", 1)[1].rstrip("Z")
    assert len(fraction) == 3, (
        f"{label} must carry exactly three fractional digits: {value!r}"
    )


# ─── Common resource properties ───────────────────────────────────────────────


def assert_common_fields(row: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """
    Assert the four common properties every persisted row carries.

    ``id`` is a server-minted UUID, ``created_at`` and ``updated_at`` are ISO 8601
    UTC instants with three fractional digits, and ``version`` is an integer that
    starts at 1 and rises by exactly 1 per mutation.
    """
    assert "id" in row, "row is missing 'id'"
    assert is_valid_uuid(row["id"]), f"id is not a UUID: {row['id']!r}"
    assert_iso8601_millis(row["created_at"], "created_at")
    assert_iso8601_millis(row["updated_at"], "updated_at")
    assert isinstance(row["version"], int), f"version must be an int: {row['version']!r}"
    assert row["version"] >= 1, f"version starts at 1, got {row['version']}"
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"expected version {expected_version}, got {row['version']}"
        )


def assert_envelope_meta(body: Dict[str, Any]) -> None:
    """Assert the declared envelope ``meta`` shape on any response body."""
    meta = body["meta"]
    assert isinstance(meta["api_request_id"], str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_': {meta['api_request_id']!r}"
    )
    assert_iso8601_millis(meta["api_request_timestamp"], "api_request_timestamp")


def assert_error_envelope(body: Dict[str, Any], expected_error_id: str) -> None:
    """Assert an error body carries the declared envelope and nothing more in meta."""
    assert body["response_type"] == "error"
    assert_envelope_meta(body)
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta must carry only api_request_id and api_request_timestamp, "
        f"got {sorted(body['meta'].keys())}"
    )
    assert body["data"]["error_id"] == expected_error_id
    assert isinstance(body["data"]["message"], str)
    assert body["data"]["message"].strip()


def assert_pagination_meta(
    meta: Dict[str, Any], limit: int, offset: int, total_count: int, has_more: bool
) -> None:
    """Assert the four pagination fields the PRD requires on every list response."""
    assert meta["limit"] == limit, f"limit: expected {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"offset: expected {offset}, got {meta['offset']}"
    assert meta["total_count"] == total_count, (
        f"total_count: expected {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"has_more: expected {has_more}, got {meta['has_more']}"
    )


def assert_created_at_ascending(rows) -> None:
    """Assert a list response is ordered oldest row first."""
    stamps = [canonical_instant(r["created_at"]) for r in rows]
    assert stamps == sorted(stamps), f"rows are not created_at ascending: {stamps}"


# ─── Money and scores ─────────────────────────────────────────────────────────


def assert_money(actual: Any, expected: int, label: str = "amount") -> None:
    """Assert a monetary field is an integer number of cents equal to ``expected``."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r} "
        f"({type(actual).__name__})"
    )
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_two_decimals(actual: Any, expected, label: str = "value") -> None:
    """Assert a two-decimal score or percentage equals ``expected``."""
    assert actual is not None, f"{label} should be {expected}, got null"
    assert float(actual) == pytest.approx(float(expected), abs=DECIMAL_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_score_precision(actual: Any, label: str = "score") -> None:
    """Assert a derived score carries at most two decimal places."""
    as_decimal = Decimal(str(actual))
    assert -as_decimal.as_tuple().exponent <= 2, (
        f"{label} must carry at most two decimals, got {actual!r}"
    )


# ─── Derived credit arithmetic (§3.8) ─────────────────────────────────────────


def expected_credit_cents(minutes: int, coverage_tier: str) -> int:
    """
    Recompute a downtime credit from the tier tables.

    ``billable = max(0, minutes - grace)`` and the credit is
    ``round_half_up(billable / 60 * rate)``; the grace allowance is applied per
    event, never once per period.
    """
    grace = DOWNTIME_GRACE_MINUTES[coverage_tier]
    rate = DOWNTIME_RATE_CENTS_PER_HOUR[coverage_tier]
    billable = max(0, minutes - grace)
    return round_half_up_cents(Decimal(billable) / Decimal(60) * Decimal(rate))


def expected_pm_compliance_pct(completed: int, missed: int):
    """Recompute pm_compliance_pct, including the empty-history case of 100.00."""
    denominator = completed + missed
    if denominator == 0:
        return Decimal("100.00")
    return round_half_up(Decimal(100) * Decimal(completed) / Decimal(denominator), 2)


# ─── The three standing invariants (§2.11) ────────────────────────────────────


def assert_parts_allowance_identity(contract: Dict[str, Any], orders) -> None:
    """
    total == remaining + sum(allowance_draw_cents over ALLOCATED and INSTALLED orders).

    Cancelled orders are excluded because cancellation zeroes the draw and returns
    the money to the remaining balance.
    """
    drawn = sum(
        o["allowance_draw_cents"]
        for o in orders
        if o["status"] in ("ALLOCATED", "INSTALLED")
    )
    assert contract["parts_allowance_total_cents"] == (
        contract["parts_allowance_remaining_cents"] + drawn
    ), (
        "parts-allowance identity broken: total "
        f"{contract['parts_allowance_total_cents']} != remaining "
        f"{contract['parts_allowance_remaining_cents']} + draws {drawn}"
    )


def assert_technician_capacity_identity(technician: Dict[str, Any], assignments) -> None:
    """committed_minutes == sum(planned_minutes over RESERVED and CONFIRMED rows)."""
    held = sum(
        a["planned_minutes"]
        for a in assignments
        if a["status"] in ("RESERVED", "CONFIRMED")
    )
    assert technician["committed_minutes"] == held, (
        "technician-capacity identity broken: committed_minutes "
        f"{technician['committed_minutes']} != held minutes {held}"
    )


def assert_part_inventory_identity(part: Dict[str, Any], orders) -> None:
    """allocated_qty == sum(qty over that line's still-ALLOCATED orders)."""
    allocated = sum(o["qty"] for o in orders if o["status"] == "ALLOCATED")
    assert part["allocated_qty"] == allocated, (
        "parts-inventory identity broken: allocated_qty "
        f"{part['allocated_qty']} != summed ALLOCATED qty {allocated}"
    )
    assert part["on_hand_qty"] >= 0, "on_hand_qty may never be negative"
    assert part["refurb_on_hand_qty"] >= 0, "refurb_on_hand_qty may never be negative"


# ─── Convenience row assertions ───────────────────────────────────────────────


def assert_fields(row: Dict[str, Any], **expected) -> None:
    """Assert a set of scalar fields on a row, reporting every mismatch at once."""
    problems = []
    for field, want in expected.items():
        got = row.get(field, "<missing>")
        if got != want:
            problems.append(f"{field}: expected {want!r}, got {got!r}")
    assert not problems, "; ".join(problems)


def assert_null_fields(row: Dict[str, Any], *fields: str) -> None:
    """Assert each named field is null on the row."""
    for field in fields:
        assert row.get(field, "<missing>") is None, (
            f"{field} should be null, got {row.get(field)!r}"
        )
