"""Domain assertion helpers for the water-utility high-bill service."""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import validate_paginated, validate_success

from .constants import LEDGER_FORBIDDEN_FIELDS


# ---------------------------------------------------------------------------
# Field-level helpers
# ---------------------------------------------------------------------------
def assert_fields(record: Dict[str, Any], **expected: Any) -> None:
    """Assert every named field of a record equals its expected value."""
    for field, value in expected.items():
        assert field in record, f"expected field {field!r} on {sorted(record)}"
        assert record[field] == value, (
            f"{field}: expected {value!r}, got {record[field]!r}"
        )


def assert_null_fields(record: Dict[str, Any], *fields: str) -> None:
    """Assert every named field is present and null."""
    for field in fields:
        assert field in record, f"expected field {field!r} on {sorted(record)}"
        assert record[field] is None, f"{field}: expected null, got {record[field]!r}"


# ---------------------------------------------------------------------------
# Money and charge helpers (PRD §3.2, §3.6)
# ---------------------------------------------------------------------------
def assert_bill_charges(
    bill: Dict[str, Any],
    consumption_gallons: Optional[int] = None,
    water_charge_cents: Optional[int] = None,
    sewer_charge_cents: Optional[int] = None,
    total_charge_cents: Optional[int] = None,
    adjusted_total_cents: Optional[int] = None,
) -> None:
    """Assert the charge picture of a bill, ignoring the figures not supplied."""
    expected = {
        "consumption_gallons": consumption_gallons,
        "water_charge_cents": water_charge_cents,
        "sewer_charge_cents": sewer_charge_cents,
        "total_charge_cents": total_charge_cents,
        "adjusted_total_cents": adjusted_total_cents,
    }
    assert_fields(bill, **{k: v for k, v in expected.items() if v is not None})


def assert_credit_breakdown(adjustment: Dict[str, Any], **expected: Any) -> None:
    """Assert the six-step credit breakdown of a leak adjustment."""
    assert_fields(adjustment, **expected)


def assert_account_state(
    account: Dict[str, Any],
    balance_cents: Optional[int] = None,
    credit_status: Optional[str] = None,
    service_status: Optional[str] = None,
    open_investigation_hold_count: Optional[int] = None,
    open_rebill_count: Optional[int] = None,
) -> None:
    """Assert the two state dimensions and the interlock counters of an account."""
    expected = {
        "balance_cents": balance_cents,
        "credit_status": credit_status,
        "service_status": service_status,
        "open_investigation_hold_count": open_investigation_hold_count,
        "open_rebill_count": open_rebill_count,
    }
    assert_fields(account, **{k: v for k, v in expected.items() if v is not None})


# ---------------------------------------------------------------------------
# Ledger helpers (PRD §2.9)
# ---------------------------------------------------------------------------
def assert_append_only_shape(entry: Dict[str, Any]) -> None:
    """Assert a ledger entry carries no mutable audit fields."""
    assert "id" in entry, "a ledger entry must carry an id"
    assert "created_at" in entry, "a ledger entry must carry created_at"
    for field in LEDGER_FORBIDDEN_FIELDS:
        assert field not in entry, f"a ledger entry must not carry {field!r}"


def ledger_entries(
    api, account_id: str, headers: Dict[str, str], **filters: Any
) -> List[Dict[str, Any]]:
    """Return one account's ledger entries, honouring the declared filters."""
    params = {"limit": 100, **filters}
    entries, _meta = validate_paginated(
        api.list_account_ledger_entries(account_id, headers, params)
    )
    return entries


def bill_ledger_entries(
    api, bill_id: str, headers: Dict[str, str], **filters: Any
) -> List[Dict[str, Any]]:
    """Return one bill's ledger entries, honouring the declared filters."""
    params = {"limit": 100, **filters}
    entries, _meta = validate_paginated(
        api.list_bill_ledger_entries(bill_id, headers, params)
    )
    return entries


def entries_of_kind(
    entries: List[Dict[str, Any]], source_kind: str
) -> List[Dict[str, Any]]:
    """Filter a ledger listing down to one ``source_kind``."""
    return [entry for entry in entries if entry.get("source_kind") == source_kind]


def assert_source_kinds(entries: List[Dict[str, Any]], expected: List[str]) -> None:
    """Assert the ordered sequence of ``source_kind`` values on a ledger listing."""
    actual = [entry.get("source_kind") for entry in entries]
    assert actual == expected, f"ledger source kinds: expected {expected}, got {actual}"


def assert_no_entry_of_kind(entries: List[Dict[str, Any]], source_kind: str) -> None:
    """Assert no ledger entry of the given ``source_kind`` was written."""
    matches = entries_of_kind(entries, source_kind)
    assert not matches, f"expected no {source_kind} entry, found {len(matches)}"


def assert_single_entry(
    entries: List[Dict[str, Any]], source_kind: str, **expected: Any
) -> Dict[str, Any]:
    """Assert exactly one entry of a ``source_kind`` exists and check its fields."""
    matches = entries_of_kind(entries, source_kind)
    assert len(matches) == 1, (
        f"expected exactly one {source_kind} entry, found {len(matches)}"
    )
    entry = matches[0]
    assert_append_only_shape(entry)
    if expected:
        assert_fields(entry, **expected)
    return entry


def assert_balance_is_ledger_sum(account: Dict[str, Any], entries: List[Dict[str, Any]]) -> None:
    """Assert ``balance_cents`` equals the sum of every entry's ``amount_cents``."""
    total = sum(entry["amount_cents"] for entry in entries)
    assert account["balance_cents"] == total, (
        f"balance_cents {account['balance_cents']} != ledger sum {total}"
    )


# ---------------------------------------------------------------------------
# Version and listing helpers (PRD §2.3, §2.4)
# ---------------------------------------------------------------------------
def assert_version(record: Dict[str, Any], expected: int) -> None:
    """Assert a record's optimistic-concurrency version."""
    assert record["version"] == expected, (
        f"version: expected {expected}, got {record['version']}"
    )


def read_version(api_response) -> int:
    """Extract ``version`` from a successful single-resource response."""
    return validate_success(api_response)["version"]


def ids_of(records: List[Dict[str, Any]]) -> List[str]:
    """Project a listing down to its ordered identifiers."""
    return [record["id"] for record in records]


def assert_listing_ids(records: List[Dict[str, Any]], expected_ids: List[str]) -> None:
    """Assert a listing returned exactly these identifiers in this order."""
    actual = ids_of(records)
    assert actual == expected_ids, f"listing ids: expected {expected_ids}, got {actual}"


def assert_pagination_meta(
    meta: Dict[str, Any],
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    """Assert the pagination block of a list response."""
    expected = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    for field, value in expected.items():
        if value is None:
            continue
        assert meta.get(field) == value, (
            f"meta.{field}: expected {value!r}, got {meta.get(field)!r}"
        )
