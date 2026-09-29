"""Domain assertion helpers.

Money is compared to the cent, sanction points to a tenth of a point. Helpers
that walk the ledger exist because the obligated amount is a replay of the
entry stream, so a test that checks a balance usually also wants to check the
entries that produced it.
"""

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytest

MONEY_TOLERANCE = 0.01
POINTS_TOLERANCE = 0.05

JsonDict = Dict[str, Any]

# The PRD pins the *instant* every derived timestamp carries, and pins a
# three-fractional-digit rendering only for `created_at` and
# `api_request_timestamp`. It says nothing about how many fractional digits the
# other derived instants (`filed_at`, `transit_deadline_utc`, `run_at`, ...)
# are rendered with, so an instant is compared as an instant rather than as a
# byte string: "2026-09-05T00:00:00Z" and "2026-09-05T00:00:00.000Z" denote the
# same instant and either rendering satisfies the PRD.
_INSTANT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$"
)


def _as_instant(value: Any) -> Optional[datetime]:
    """Parse an ISO 8601 UTC instant string, or return None if it is not one."""
    if not isinstance(value, str) or not _INSTANT_RE.match(value):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Scalar comparisons
# ---------------------------------------------------------------------------
def assert_money(actual: Any, expected: float, label: str) -> None:
    assert actual is not None, f"{label} is missing from the response"
    assert actual == pytest.approx(expected, abs=MONEY_TOLERANCE), (
        f"{label} should be {expected:.2f} but the API reported {actual}"
    )


def assert_points(actual: Any, expected: float, label: str = "sanction_points") -> None:
    assert actual is not None, f"{label} is missing from the response"
    assert actual == pytest.approx(expected, abs=POINTS_TOLERANCE), (
        f"{label} should be {expected} but the API reported {actual}"
    )


def assert_field(record: JsonDict, field: str, expected: Any, label: str = "") -> None:
    prefix = f"{label}." if label else ""
    assert field in record, f"{prefix}{field} is missing from the response"
    actual = record[field]
    want_instant = _as_instant(expected)
    got_instant = _as_instant(actual)
    if want_instant is not None and got_instant is not None:
        assert got_instant == want_instant, (
            f"{prefix}{field} should be the instant {expected!r} but the API "
            f"reported {actual!r}"
        )
        return
    assert actual == expected, (
        f"{prefix}{field} should be {expected!r} but the API reported "
        f"{actual!r}"
    )


def assert_fields(record: JsonDict, expected: JsonDict, label: str = "") -> None:
    for field, value in expected.items():
        assert_field(record, field, value, label)


# ---------------------------------------------------------------------------
# Movement state
# ---------------------------------------------------------------------------
def assert_movement_state(
    movement: JsonDict,
    transit_status: Optional[str] = None,
    custody_status: Optional[str] = None,
) -> None:
    """Check either or both of the two independent state dimensions."""
    if transit_status is not None:
        assert movement["transit_status"] == transit_status, (
            f"transit_status should be {transit_status} but the movement is in "
            f"{movement['transit_status']}"
        )
    if custody_status is not None:
        assert movement["custody_status"] == custody_status, (
            f"custody_status should be {custody_status} but the movement is in "
            f"{movement['custody_status']}"
        )


def assert_deadline(
    movement: JsonDict,
    anchor: Optional[str] = None,
    deadline: Optional[str] = None,
    transit_days_allowed: Optional[int] = None,
    extension_days_granted: Optional[int] = None,
) -> None:
    """Check the transit-deadline derivation chain on a movement."""
    if anchor is not None:
        assert_field(movement, "deadline_anchor_utc", anchor, "movement")
    if deadline is not None:
        assert_field(movement, "transit_deadline_utc", deadline, "movement")
    if transit_days_allowed is not None:
        assert_field(movement, "transit_days_allowed", transit_days_allowed, "movement")
    if extension_days_granted is not None:
        assert_field(
            movement, "extension_days_granted", extension_days_granted, "movement"
        )


# ---------------------------------------------------------------------------
# Bond state
# ---------------------------------------------------------------------------
def assert_bond_amounts(
    bond: JsonDict,
    obligated: Optional[float] = None,
    available: Optional[float] = None,
    status: Optional[str] = None,
    open_movement_count: Optional[int] = None,
) -> None:
    if obligated is not None:
        assert_money(bond["obligated_amount"], obligated, "bond obligated_amount")
    if available is not None:
        assert_money(bond["available_amount"], available, "bond available_amount")
    if status is not None:
        assert_field(bond, "status", status, "bond")
    if open_movement_count is not None:
        assert_field(bond, "open_movement_count", open_movement_count, "bond")


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------
def assert_ledger_entry(
    entry: JsonDict,
    entry_type: Optional[str] = None,
    amount: Optional[float] = None,
    balance_after: Optional[float] = None,
    reason_code: Optional[str] = None,
) -> None:
    if entry_type is not None:
        assert_field(entry, "entry_type", entry_type, "ledger entry")
    if amount is not None:
        assert_money(entry["amount"], amount, "ledger entry amount")
    if balance_after is not None:
        assert_money(entry["balance_after"], balance_after, "ledger entry balance_after")
    if reason_code is not None:
        assert_field(entry, "reason_code", reason_code, "ledger entry")


def assert_ledger_stream(
    entries: List[JsonDict], expected: List[JsonDict]
) -> None:
    """Check an ordered run of ledger entries against a list of expectations."""
    assert len(entries) == len(expected), (
        f"expected {len(expected)} ledger entries but the audit trail holds "
        f"{len(entries)}: "
        f"{[(e.get('entry_type'), e.get('amount')) for e in entries]}"
    )
    for index, (entry, want) in enumerate(zip(entries, expected)):
        assert_ledger_entry(entry, **want)
        assert entry["entry_type"] == want.get("entry_type", entry["entry_type"]), (
            f"ledger entry {index} has the wrong type"
        )


def assert_ledger_nets_to_zero(entries: List[JsonDict], label: str) -> None:
    """A compensated stream must sum to exactly nothing."""
    total = sum(entry["amount"] for entry in entries)
    assert total == pytest.approx(0.0, abs=MONEY_TOLERANCE), (
        f"the ledger entries for {label} should net to 0.00 but they sum to "
        f"{total}: {[(e['entry_type'], e['amount']) for e in entries]}"
    )


# ---------------------------------------------------------------------------
# Append-only records
# ---------------------------------------------------------------------------
def assert_witness_record_shape(record: JsonDict, label: str) -> None:
    """Append-only witnesses expose id and created_at, never version fields."""
    assert "id" in record, f"{label} must expose an id"
    assert "created_at" in record, f"{label} must expose created_at"
    assert "version" not in record, (
        f"{label} is an append-only record and must not expose a version field"
    )
    assert "updated_at" not in record, (
        f"{label} is an append-only record and must not expose updated_at"
    )


# ---------------------------------------------------------------------------
# Petition arithmetic
# ---------------------------------------------------------------------------
def assert_petition_offer(
    petition: JsonDict,
    mitigation_pct: float,
    net_before_fee: float,
    processing_fee: float,
    offer_amount: float,
    prior_violation_count: Optional[int] = None,
    petition_round: Optional[int] = None,
) -> None:
    assert petition["mitigation_pct"] == pytest.approx(mitigation_pct, abs=0.001), (
        f"mitigation_pct should be {mitigation_pct} but the petition carries "
        f"{petition['mitigation_pct']}"
    )
    assert_money(petition["net_before_fee"], net_before_fee, "net_before_fee")
    assert_money(petition["processing_fee"], processing_fee, "processing_fee")
    assert_money(petition["offer_amount"], offer_amount, "offer_amount")
    if prior_violation_count is not None:
        assert_field(petition, "prior_violation_count", prior_violation_count, "petition")
    if petition_round is not None:
        assert_field(petition, "round", petition_round, "petition")


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------
def assert_ids(rows: List[JsonDict], expected_ids: List[str], label: str) -> None:
    """Order-insensitive identity check over a returned collection."""
    actual = sorted(row["id"] for row in rows)
    assert actual == sorted(expected_ids), (
        f"{label} should contain exactly {sorted(expected_ids)} but it contains "
        f"{actual}"
    )


def assert_ordered_values(
    rows: List[JsonDict], field: str, expected: List[Any], label: str
) -> None:
    actual = [row[field] for row in rows]
    assert actual == expected, (
        f"{label} should read {expected} in order on {field} but it reads {actual}"
    )
