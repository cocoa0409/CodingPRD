"""Domain assertions for the Home Electrification Rebates API.

These encode the invariants the PRD states globally — the audit-field contract
of §2.4, the two conservation identities of §2.7, and the pagination envelope of
§2.3 — plus small lookup helpers so test bodies stay about the rule under test.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# --------------------------------------------------------------------------- #
# Audit-field contract (§2.4)
# --------------------------------------------------------------------------- #

FULL_AUDIT_FIELDS = ("id", "created_at", "updated_at", "version")
APPEND_ONLY_AUDIT_FIELDS = ("id", "created_at")


def assert_full_audit_fields(entity: Dict[str, Any], label: str = "resource") -> None:
    """A versioned record carries id, created_at, updated_at and version."""
    for field in FULL_AUDIT_FIELDS:
        assert field in entity, f"{label} must expose '{field}': got keys {sorted(entity)}"
    assert is_valid_uuid(entity["id"]), f"{label}.id must be a UUID, got {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp, got {entity['created_at']!r}"
    )
    assert is_iso8601_timestamp(entity["updated_at"]), (
        f"{label}.updated_at must be an ISO 8601 UTC timestamp, got {entity['updated_at']!r}"
    )
    assert isinstance(entity["version"], int), f"{label}.version must be an integer"
    assert entity["version"] >= 1, f"{label}.version must start at 1 or more"


def assert_append_only_record(entity: Dict[str, Any], label: str = "record") -> None:
    """An append-only audit row carries id and created_at and nothing else audit-wise."""
    for field in APPEND_ONLY_AUDIT_FIELDS:
        assert field in entity, f"{label} must expose '{field}': got keys {sorted(entity)}"
    assert is_valid_uuid(entity["id"]), f"{label}.id must be a UUID, got {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp, got {entity['created_at']!r}"
    )
    assert "updated_at" not in entity, (
        f"{label} is append-only and must not carry 'updated_at'"
    )
    assert "version" not in entity, f"{label} is append-only and must not carry 'version'"


# --------------------------------------------------------------------------- #
# Conservation identities (§2.7)
# --------------------------------------------------------------------------- #


def assert_program_budget_conserved(program: Dict[str, Any]) -> None:
    """budget_total == available + reserved + committed; the clawback tally is separate."""
    total = program["budget_total_cents"]
    available = program["budget_available_cents"]
    reserved = program["budget_reserved_cents"]
    committed = program["budget_committed_cents"]
    assert available + reserved + committed == total, (
        "Program appropriation must be conserved: "
        f"available {available} + reserved {reserved} + committed {committed} "
        f"!= total {total}"
    )


def assert_household_cap_conserved(household: Dict[str, Any]) -> None:
    """rebate_cap == lifetime_cap_remaining + encumbered."""
    cap = household["rebate_cap_cents"]
    remaining = household["lifetime_cap_remaining_cents"]
    encumbered = household["encumbered_cents"]
    assert remaining + encumbered == cap, (
        "Household lifetime entitlement must be conserved: "
        f"remaining {remaining} + encumbered {encumbered} != cap {cap}"
    )


def assert_program_buckets(
    program: Dict[str, Any],
    available: Optional[int] = None,
    reserved: Optional[int] = None,
    committed: Optional[int] = None,
    clawed_back: Optional[int] = None,
) -> None:
    """Assert named budget buckets and re-check the conservation identity."""
    if available is not None:
        assert program["budget_available_cents"] == available, (
            f"budget_available_cents should be {available}, "
            f"got {program['budget_available_cents']}"
        )
    if reserved is not None:
        assert program["budget_reserved_cents"] == reserved, (
            f"budget_reserved_cents should be {reserved}, "
            f"got {program['budget_reserved_cents']}"
        )
    if committed is not None:
        assert program["budget_committed_cents"] == committed, (
            f"budget_committed_cents should be {committed}, "
            f"got {program['budget_committed_cents']}"
        )
    if clawed_back is not None:
        assert program["budget_clawed_back_cents"] == clawed_back, (
            f"budget_clawed_back_cents should be {clawed_back}, "
            f"got {program['budget_clawed_back_cents']}"
        )
    assert_program_budget_conserved(program)


def assert_household_cap(
    household: Dict[str, Any],
    remaining: Optional[int] = None,
    encumbered: Optional[int] = None,
    cap: Optional[int] = None,
) -> None:
    """Assert named cap balances and re-check the conservation identity."""
    if cap is not None:
        assert household["rebate_cap_cents"] == cap, (
            f"rebate_cap_cents should be {cap}, got {household['rebate_cap_cents']}"
        )
    if remaining is not None:
        assert household["lifetime_cap_remaining_cents"] == remaining, (
            f"lifetime_cap_remaining_cents should be {remaining}, "
            f"got {household['lifetime_cap_remaining_cents']}"
        )
    if encumbered is not None:
        assert household["encumbered_cents"] == encumbered, (
            f"encumbered_cents should be {encumbered}, got {household['encumbered_cents']}"
        )
    assert_household_cap_conserved(household)


# --------------------------------------------------------------------------- #
# Field-level helpers
# --------------------------------------------------------------------------- #


def assert_fields(entity: Dict[str, Any], label: str = "resource", **expected: Any) -> None:
    """Assert an exact value for each named field."""
    for field, want in expected.items():
        assert field in entity, f"{label} must expose '{field}': got keys {sorted(entity)}"
        assert entity[field] == want, (
            f"{label}.{field} should be {want!r}, got {entity[field]!r}"
        )


def assert_status(entity: Dict[str, Any], expected: str, label: str = "resource") -> None:
    assert entity["status"] == expected, (
        f"{label}.status should be {expected}, got {entity['status']}"
    )


def assert_version_is(entity: Dict[str, Any], expected: int, label: str = "resource") -> None:
    assert entity["version"] == expected, (
        f"{label}.version should be {expected}, got {entity['version']}"
    )


def assert_version_unchanged(before: Dict[str, Any], after: Dict[str, Any], label: str = "resource") -> None:
    assert after["version"] == before["version"], (
        f"{label}.version must not move: was {before['version']}, now {after['version']}"
    )


# --------------------------------------------------------------------------- #
# Collection helpers
# --------------------------------------------------------------------------- #


def find_by(items: Sequence[Dict[str, Any]], field: str, value: Any) -> Dict[str, Any]:
    """Return the single item whose `field` equals `value`."""
    matches = [item for item in items if item.get(field) == value]
    assert len(matches) == 1, (
        f"Expected exactly one item with {field}=={value!r}, found {len(matches)} "
        f"in {[item.get(field) for item in items]}"
    )
    return matches[0]


def find_measure_line(lines: Sequence[Dict[str, Any]], measure_code: str) -> Dict[str, Any]:
    """Return the project measure line (or quote line) for one measure code."""
    return find_by(lines, "measure_code", measure_code)


def assert_measure_codes_in_order(
    lines: Sequence[Dict[str, Any]], expected: List[str]
) -> None:
    actual = [line["measure_code"] for line in lines]
    assert actual == expected, f"Measure codes should read {expected}, got {actual}"


def assert_ids_in_order(items: Sequence[Dict[str, Any]], expected_ids: List[str]) -> None:
    actual = [item["id"] for item in items]
    assert actual == expected_ids, f"Ids should read {expected_ids}, got {actual}"


def assert_ascending(items: Sequence[Dict[str, Any]], field: str) -> None:
    values = [item[field] for item in items]
    assert values == sorted(values), f"Items should be sorted by {field} ascending, got {values}"


def assert_pagination_meta(
    meta: Dict[str, Any],
    total_count: Optional[int] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"meta.total_count should be {total_count}, got {meta['total_count']}"
        )
    if limit is not None:
        assert meta["limit"] == limit, f"meta.limit should be {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"meta.offset should be {offset}, got {meta['offset']}"
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"meta.has_more should be {has_more}, got {meta['has_more']}"
        )


# --------------------------------------------------------------------------- #
# Incentive-quote helpers (§3.5)
# --------------------------------------------------------------------------- #


def assert_quote_line(
    quote: Dict[str, Any],
    measure_code: str,
    raw_incentive_cents: Optional[int] = None,
    cost_share_cap_cents: Optional[int] = None,
    capped_line_cents: Optional[int] = None,
    allocated_cents: Optional[int] = None,
) -> Dict[str, Any]:
    """Assert the per-stage amounts the quote reports for one measure code."""
    line = find_measure_line(quote["lines"], measure_code)
    expected = {
        "raw_incentive_cents": raw_incentive_cents,
        "cost_share_cap_cents": cost_share_cap_cents,
        "capped_line_cents": capped_line_cents,
        "allocated_cents": allocated_cents,
    }
    for field, want in expected.items():
        if want is not None:
            assert line[field] == want, (
                f"Quote line {measure_code}.{field} should be {want}, got {line[field]}"
            )
    return line


def assert_quote_totals_match_lines(quote: Dict[str, Any]) -> None:
    """The reported total equals the sum of the per-line allocations."""
    line_sum = sum(line["allocated_cents"] for line in quote["lines"])
    assert quote["total_incentive_cents"] == line_sum, (
        f"total_incentive_cents {quote['total_incentive_cents']} should equal the "
        f"sum of allocated_cents {line_sum}"
    )


__all__ = [
    "FULL_AUDIT_FIELDS",
    "APPEND_ONLY_AUDIT_FIELDS",
    "assert_full_audit_fields",
    "assert_append_only_record",
    "assert_program_budget_conserved",
    "assert_household_cap_conserved",
    "assert_program_buckets",
    "assert_household_cap",
    "assert_fields",
    "assert_status",
    "assert_version_is",
    "assert_version_unchanged",
    "find_by",
    "find_measure_line",
    "assert_measure_codes_in_order",
    "assert_ids_in_order",
    "assert_ascending",
    "assert_pagination_meta",
    "assert_quote_line",
    "assert_quote_totals_match_lines",
]
