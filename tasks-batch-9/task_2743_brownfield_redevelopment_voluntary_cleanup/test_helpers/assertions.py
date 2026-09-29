"""
Domain assertions.

Three families live here.

*Format helpers* absorb the freedom the contract leaves. It renders instants with
exactly three fractional digits, but a test naming an expected instant usually spells
it without them, so ``assert_instant`` compares two spellings as moments rather than
as strings and never turns a formatting difference into a false business failure.

*Envelope and row helpers* assert what the contract says about every response and
every persisted row — the two request-scoped meta fields, the four pagination
counters, the server-minted UUID, the timestamps, and the version that starts at 1.

*Invariant helpers* assert the two conserved quantities the contract promises: the
four obligation weight buckets summing to the total, and the allocations plus the
unfunded gap summing to the funding need.
"""

from decimal import Decimal
from typing import Any, Dict, Iterable, Optional, Sequence

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    PAGINATION_META_FIELDS,
    REQUEST_ID_PREFIX,
    REQUEST_META_FIELDS,
    TIMESTAMP_FRACTIONAL_DIGITS,
    round_half_up,
)

# ─── Instants and dates ───────────────────────────────────────────────────────


def canonical_instant(value: str) -> str:
    """
    Reduce an ISO 8601 UTC instant to a canonical second-precision spelling.

    ``2027-06-01T00:00:00.000Z``, ``2027-06-01T00:00:00Z`` and
    ``2027-06-01T00:00:00.000000Z`` all canonicalise to the same string, so a test can
    write the moment it means without pinning the fractional width of the rendering.
    """
    assert isinstance(value, str), f"Expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    assert text.endswith("Z"), f"Instant must be UTC and end with Z: {value!r}"
    text = text[:-1]
    if "." in text:
        head, frac = text.split(".", 1)
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
    """Assert the value is ISO 8601 UTC with exactly three fractional digits."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{label} is not an ISO 8601 UTC instant: {value!r}"
    assert "." in value, f"{label} must carry fractional seconds: {value!r}"
    fraction = value.split(".", 1)[1].rstrip("Z")
    assert len(fraction) == TIMESTAMP_FRACTIONAL_DIGITS, (
        f"{label} must carry exactly {TIMESTAMP_FRACTIONAL_DIGITS} fractional digits: {value!r}"
    )


def assert_date(actual: Optional[str], expected: Optional[str], label: str = "date") -> None:
    """Assert a calendar date field equals the expected YYYY-MM-DD spelling."""
    if expected is None:
        assert actual is None, f"{label} should be null, got {actual!r}"
        return
    assert actual == expected, f"{label}: expected {expected!r}, got {actual!r}"


# ─── Envelopes ────────────────────────────────────────────────────────────────


def assert_envelope_meta(body: Dict[str, Any]) -> None:
    """Assert the two request-scoped meta fields every response carries."""
    meta = body["meta"]
    for field in REQUEST_META_FIELDS:
        assert field in meta, f"meta is missing {field}"
    assert meta["api_request_id"].startswith(REQUEST_ID_PREFIX), (
        f"api_request_id must start with {REQUEST_ID_PREFIX!r}: {meta['api_request_id']!r}"
    )
    assert_iso8601_millis(meta["api_request_timestamp"], "meta.api_request_timestamp")


def assert_object_envelope(body: Dict[str, Any]) -> None:
    """A single-resource response declares itself an object and carries no counters."""
    assert body["response_type"] == "object", (
        f"single reads declare response_type 'object', got {body['response_type']!r}"
    )
    assert_envelope_meta(body)
    for field in PAGINATION_META_FIELDS:
        assert field not in body["meta"], (
            f"a single read must not carry the pagination field {field}"
        )


def assert_pagination_meta(
    meta: Dict[str, Any],
    expected_total: Optional[int] = None,
    expected_limit: Optional[int] = None,
    expected_offset: Optional[int] = None,
    expected_has_more: Optional[bool] = None,
) -> None:
    """Assert the four list counters, and any of them a test pins."""
    for field in PAGINATION_META_FIELDS:
        assert field in meta, f"a list response must carry meta.{field}"
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            f"total_count: expected {expected_total}, got {meta['total_count']}"
        )
    if expected_limit is not None:
        assert meta["limit"] == expected_limit, (
            f"limit: expected {expected_limit}, got {meta['limit']}"
        )
    if expected_offset is not None:
        assert meta["offset"] == expected_offset, (
            f"offset: expected {expected_offset}, got {meta['offset']}"
        )
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more, (
            f"has_more: expected {expected_has_more}, got {meta['has_more']}"
        )


def assert_error_envelope(body: Dict[str, Any]) -> None:
    """An error response carries only the two request meta fields alongside the code."""
    assert body["response_type"] == "error"
    assert set(body["data"].keys()) >= {"error_id", "message"}
    assert_envelope_meta(body)
    for field in PAGINATION_META_FIELDS:
        assert field not in body["meta"], (
            f"an error envelope must not carry the pagination field {field}"
        )


# ─── Rows ─────────────────────────────────────────────────────────────────────


def assert_common_fields(row: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """
    Assert the four properties every entity but the immutable finding carries.

    ``id`` is a server-minted UUID with no type prefix, ``created_at`` and
    ``updated_at`` are ISO 8601 UTC instants rendered to three fractional digits, and
    ``version`` is an integer that starts at 1.
    """
    assert is_valid_uuid(row["id"]), f"id must be a UUID with no prefix: {row['id']!r}"
    assert_iso8601_millis(row["created_at"], "created_at")
    assert_iso8601_millis(row["updated_at"], "updated_at")
    assert isinstance(row["version"], int), f"version must be an integer: {row['version']!r}"
    assert row["version"] >= 1, f"version starts at 1, got {row['version']}"
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"version: expected {expected_version}, got {row['version']}"
        )


def assert_immutable_row(row: Dict[str, Any]) -> None:
    """
    Assert the shape of the one entity the contract exempts from versioning.

    A contaminant finding carries only ``id`` and ``created_at``; it has no
    ``updated_at`` and no ``version`` because it is immutable and has no update
    endpoint.
    """
    assert is_valid_uuid(row["id"]), f"id must be a UUID: {row['id']!r}"
    assert_iso8601_millis(row["created_at"], "created_at")
    assert "updated_at" not in row, "an immutable finding carries no updated_at"
    assert "version" not in row, "an immutable finding carries no version"


def assert_fields(row: Dict[str, Any], **expected) -> None:
    """Assert each named field equals its expected value, reporting all mismatches."""
    wrong = {
        key: (row.get(key), value)
        for key, value in expected.items()
        if row.get(key) != value
    }
    assert not wrong, "field mismatches: " + ", ".join(
        f"{key}: expected {want!r}, got {got!r}" for key, (got, want) in wrong.items()
    )


def assert_null_fields(row: Dict[str, Any], *names: str) -> None:
    """Assert every named field is present and null."""
    for name in names:
        assert name in row, f"{name} should be present on the row"
        assert row[name] is None, f"{name} should be null, got {row[name]!r}"


def assert_created_at_ascending(rows: Sequence[Dict[str, Any]]) -> None:
    """Assert a list came back in ``created_at`` ascending order."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows are not in created_at ascending order: {stamps}"


# ─── Numbers ──────────────────────────────────────────────────────────────────


def assert_decimal_places(value, places: int, label: str = "value") -> None:
    """Assert a number carries at most ``places`` decimal places."""
    assert value is not None, f"{label} should be a number, got null"
    as_decimal = Decimal(str(value))
    assert as_decimal == round_half_up(as_decimal, places), (
        f"{label} must carry at most {places} decimal places: {value!r}"
    )


def assert_money_cents(value, label: str = "amount") -> None:
    """Assert a money field is carried as an integer number of cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}"
    )


def assert_number(actual, expected, label: str = "value") -> None:
    """Compare two numbers by value, tolerating int/float/Decimal spellings."""
    assert actual is not None, f"{label} should be {expected}, got null"
    assert Decimal(str(actual)) == Decimal(str(expected)), (
        f"{label}: expected {expected}, got {actual}"
    )


# ─── Conserved quantities ─────────────────────────────────────────────────────


def assert_weight_conservation(protection: Dict[str, Any]) -> None:
    """
    Assert the four weight buckets exactly partition the total.

    Every obligation on the protection belongs to exactly one bucket, so the four
    always sum to ``obligations_total_weight`` however the duties have moved.
    """
    total = (
        protection["current_weight"]
        + protection["satisfied_weight"]
        + protection["at_risk_weight"]
        + protection["lapsed_weight"]
    )
    assert total == protection["obligations_total_weight"], (
        "weight buckets must sum to obligations_total_weight: "
        f"{protection['current_weight']} + {protection['satisfied_weight']} + "
        f"{protection['at_risk_weight']} + {protection['lapsed_weight']} = {total}, "
        f"total is {protection['obligations_total_weight']}"
    )


def assert_funding_conservation(assembly: Dict[str, Any]) -> None:
    """Assert the allocations plus the unfunded gap exactly equal the funding need."""
    allocated = sum(entry["allocated_cents"] for entry in assembly["allocations"])
    assert allocated + assembly["unfunded_gap_cents"] == assembly[
        "total_funding_need_cents"
    ], (
        "allocations plus the unfunded gap must equal the need: "
        f"{allocated} + {assembly['unfunded_gap_cents']} != "
        f"{assembly['total_funding_need_cents']}"
    )


# ─── Composite row shapes ─────────────────────────────────────────────────────


def assert_estimate_figures(plan: Dict[str, Any], expected: Dict[str, Any]) -> None:
    """
    Assert every cost figure the estimate writes, and that each is integer cents.

    ``expected`` is the dictionary the constants module's estimate helper returns.
    """
    for field in (
        "direct_cost_cents",
        "escalation_cents",
        "contingency_cents",
        "oversight_cents",
    ):
        assert_money_cents(plan[field], field)
    assert_money_cents(plan["total_estimate_cents"], "total_estimate_cents")
    assert_fields(
        plan,
        direct_cost_cents=expected["direct_cost_cents"],
        escalation_cents=expected["escalation_cents"],
        contingency_cents=expected["contingency_cents"],
        oversight_cents=expected["oversight_cents"],
        total_estimate_cents=expected["total_cents"],
    )
    assert_number(plan["contingency_pct"], expected["contingency_pct"], "contingency_pct")
    assert_decimal_places(plan["contingency_pct"], 2, "contingency_pct")
    assert (
        plan["direct_cost_cents"]
        + plan["escalation_cents"]
        + plan["contingency_cents"]
        + plan["oversight_cents"]
        == plan["total_estimate_cents"]
    ), "the four components must sum to total_estimate_cents"


def assert_placement_figures(policy: Dict[str, Any], expected: Dict[str, Any]) -> None:
    """Assert the whole cap derivation, including the unrounded ratio's rate tier."""
    for field in (
        "underwriting_estimate_cents",
        "attachment_point_cents",
        "buffer_layer_cents",
        "limit_cents",
        "premium_cents",
    ):
        assert_money_cents(policy[field], field)
    assert_fields(
        policy,
        attachment_point_cents=expected["attachment_point_cents"],
        buffer_layer_cents=expected["buffer_layer_cents"],
        limit_cents=expected["limit_cents"],
        premium_cents=expected["premium_cents"],
    )
    assert_number(policy["rate_applied"], expected["rate_applied"], "rate_applied")
    assert_decimal_places(policy["rate_applied"], 3, "rate_applied")
    assert (
        policy["attachment_point_cents"] - policy["underwriting_estimate_cents"]
        == policy["buffer_layer_cents"]
    ), "buffer_layer_cents is the attachment point less the underwriting estimate"


def assert_pins_match(
    pins: Iterable[Dict[str, Any]], goals: Sequence[Dict[str, Any]]
) -> None:
    """
    Assert the captured goal pins name every goal on the parcel, in creation order.

    Each entry pairs a ``cleanup_goal_id`` with the goal's ``version`` at capture time,
    and the entries follow the goals' ``created_at`` ascending.
    """
    ordered = sorted(goals, key=lambda goal: goal["created_at"])
    pin_list = list(pins)
    assert [pin["cleanup_goal_id"] for pin in pin_list] == [
        goal["id"] for goal in ordered
    ], "pins must name every cleanup goal on the parcel in created_at ascending order"
    assert [pin["pinned_version"] for pin in pin_list] == [
        goal["version"] for goal in ordered
    ], "each pin must record the goal's version at capture time"


def assert_sweep_counters(result: Dict[str, Any], **expected) -> None:
    """Assert the six counters the ops-run checkpoint reports."""
    for field in (
        "swept_obligation_count",
        "at_risk_count",
        "lapsed_count",
        "stale_inquiry_count",
        "forfeited_protection_count",
        "frozen_site_count",
    ):
        assert field in result, f"the sweep must report {field}"
        assert isinstance(result[field], int), f"{field} must be an integer"
    assert_fields(result, **expected)


def ids_of(rows: Iterable[Dict[str, Any]]) -> list:
    """The ``id`` of every row in a list, in the order the list returned them."""
    return [row["id"] for row in rows]


def approx(value, tolerance=1e-9):
    """A float comparison for the rare read that exposes a non-decimal quantity."""
    return pytest.approx(value, abs=tolerance)
