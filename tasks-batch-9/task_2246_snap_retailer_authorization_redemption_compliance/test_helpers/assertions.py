"""Reusable structural and invariant assertions.

Shape assertions read their field list off the TypedDicts in types.py so a
missing or misnamed response field fails loudly. The invariant helpers encode the
conservation laws the specification states: the depot's five counters, the
penalty ledger against the case balance, and an inspector's committed minutes
against its scheduled visits.
"""
import re
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
)

from . import types as t

# --------------------------------------------------------------------------
# Envelope and common fields
# --------------------------------------------------------------------------


def assert_timestamp(value: Any, label: str = "timestamp") -> None:
    """Timestamps are ISO-8601 UTC with millisecond precision and a trailing Z."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{label} is not ISO-8601: {value!r}"
    assert value.endswith("Z"), f"{label} must end in Z: {value!r}"


def assert_common_fields(entity: Dict[str, Any], label: str = "entity") -> None:
    """Every entity carries an id, a created_at, an updated_at and a version."""
    for field in ("id", "created_at", "updated_at", "version"):
        assert field in entity, f"{label} is missing {field}"
    assert is_valid_uuid(entity["id"]), f"{label}.id is not a UUID: {entity['id']!r}"
    assert_timestamp(entity["created_at"], f"{label}.created_at")
    assert_timestamp(entity["updated_at"], f"{label}.updated_at")
    assert isinstance(entity["version"], int), f"{label}.version must be an integer"
    assert entity["version"] >= 1, f"{label}.version must start at 1"


def assert_ledger_entry_fields(entry: Dict[str, Any], label: str = "ledger entry") -> None:
    """A penalty ledger entry is the sole exception to the common-field rule: it
    carries an id and a created_at only, because nothing ever updates it."""
    for field in ("id", "created_at"):
        assert field in entry, f"{label} is missing {field}"
    assert is_valid_uuid(entry["id"]), f"{label}.id is not a UUID: {entry['id']!r}"
    assert_timestamp(entry["created_at"], f"{label}.created_at")
    for field in ("updated_at", "version"):
        assert field not in entry, f"{label} must not carry {field}"


def _shape(entity: Dict[str, Any], typed_dict: Any, label: str) -> None:
    for field in typed_dict.__annotations__.keys():
        assert field in entity, f"{label} is missing {field}: got {sorted(entity)}"


def assert_owner_shape(owner: Dict[str, Any]) -> None:
    assert_common_fields(owner, "owner")
    _shape(owner, t.Owner, "owner")


def assert_store_shape(store: Dict[str, Any]) -> None:
    assert_common_fields(store, "store")
    _shape(store, t.Store, "store")


def assert_application_shape(application: Dict[str, Any]) -> None:
    assert_common_fields(application, "application")
    _shape(application, t.Application, "application")


def assert_inspector_shape(inspector: Dict[str, Any]) -> None:
    assert_common_fields(inspector, "inspector")
    _shape(inspector, t.Inspector, "inspector")


def assert_store_visit_shape(visit: Dict[str, Any]) -> None:
    assert_common_fields(visit, "store visit")
    _shape(visit, t.StoreVisit, "store visit")


def assert_pos_transaction_shape(transaction: Dict[str, Any]) -> None:
    assert_common_fields(transaction, "pos transaction")
    _shape(transaction, t.PosTransaction, "pos transaction")


def assert_redemption_period_shape(period: Dict[str, Any]) -> None:
    assert_common_fields(period, "redemption period")
    _shape(period, t.RedemptionPeriod, "redemption period")


def assert_investigation_shape(investigation: Dict[str, Any]) -> None:
    assert_common_fields(investigation, "investigation")
    _shape(investigation, t.Investigation, "investigation")


def assert_sanction_case_shape(case: Dict[str, Any]) -> None:
    assert_common_fields(case, "sanction case")
    _shape(case, t.SanctionCase, "sanction case")


def assert_cmp_election_shape(election: Dict[str, Any]) -> None:
    assert_common_fields(election, "cmp election")
    _shape(election, t.CmpElection, "cmp election")


def assert_penalty_ledger_entry_shape(entry: Dict[str, Any]) -> None:
    assert_ledger_entry_fields(entry)
    _shape(entry, t.PenaltyLedgerEntry, "ledger entry")


def assert_depot_shape(depot: Dict[str, Any]) -> None:
    assert_common_fields(depot, "equipment depot")
    _shape(depot, t.EquipmentDepot, "equipment depot")


def assert_terminal_shape(terminal: Dict[str, Any]) -> None:
    assert_common_fields(terminal, "ebt terminal")
    _shape(terminal, t.EbtTerminal, "ebt terminal")


def assert_deployment_shape(deployment: Dict[str, Any]) -> None:
    assert_common_fields(deployment, "terminal deployment")
    _shape(deployment, t.TerminalDeployment, "terminal deployment")


def assert_equipment_order_shape(order: Dict[str, Any]) -> None:
    assert_common_fields(order, "equipment order")
    _shape(order, t.EquipmentOrder, "equipment order")


# --------------------------------------------------------------------------
# Field-by-field comparison
# --------------------------------------------------------------------------


_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def _instant(value: Any) -> Optional[str]:
    """Reduce an ISO-8601 UTC string to whole seconds, so that the specification's
    three fractional digits and the bare-second spellings of the same instant
    compare equal."""
    if isinstance(value, str) and _TIMESTAMP_RE.match(value):
        return value[:19]
    return None


def _equivalent(actual: Any, expected: Any) -> bool:
    if actual == expected:
        return True
    left, right = _instant(actual), _instant(expected)
    return left is not None and left == right


def assert_instant(actual: Any, expected: str, label: str = "timestamp") -> None:
    """Compare two timestamps as instants rather than as spellings."""
    assert _equivalent(actual, expected), (
        f"{label} expected the instant {expected}, got {actual!r}"
    )


def assert_fields(entity: Dict[str, Any], expected: Dict[str, Any], label: str = "entity") -> None:
    for field, value in expected.items():
        assert field in entity, f"{label} is missing {field}"
        assert _equivalent(entity[field], value), (
            f"{label}.{field} expected {value!r}, got {entity[field]!r}"
        )


# --------------------------------------------------------------------------
# Conservation invariants
# --------------------------------------------------------------------------

DEPOT_COUNTERS = (
    "units_in_stock",
    "units_reserved",
    "units_deployed",
    "units_pending_return",
    "units_retired",
)


def assert_depot_conservation(
    depot: Dict[str, Any], expected: Optional[Dict[str, int]] = None
) -> None:
    """The five depot counters always sum to total_units_owned."""
    total = sum(depot[counter] for counter in DEPOT_COUNTERS)
    assert total == depot["total_units_owned"], (
        "depot counters "
        + ", ".join(f"{c}={depot[c]}" for c in DEPOT_COUNTERS)
        + f" sum to {total}, not total_units_owned={depot['total_units_owned']}"
    )
    if expected:
        assert_fields(depot, expected, "depot")


def assert_ledger_conservation(
    entries: Iterable[Dict[str, Any]], case: Dict[str, Any]
) -> None:
    """The signed ledger amounts sum to the case's outstanding balance, and each
    entry's balance_after_cents is the running total up to and including it."""
    running = 0
    for index, entry in enumerate(entries):
        running += entry["amount_cents"]
        assert entry["balance_after_cents"] == running, (
            f"ledger entry {index} reports balance_after_cents="
            f"{entry['balance_after_cents']}, running total is {running}"
        )
    assert case["cmp_outstanding_cents"] == running, (
        f"case cmp_outstanding_cents={case['cmp_outstanding_cents']} does not equal "
        f"the ledger sum {running}"
    )


def assert_inspector_minutes(inspector: Dict[str, Any], expected_minutes: int) -> None:
    assert inspector["committed_minutes"] == expected_minutes, (
        f"inspector committed_minutes={inspector['committed_minutes']}, "
        f"expected {expected_minutes}"
    )


# --------------------------------------------------------------------------
# Listing helpers
# --------------------------------------------------------------------------


def data_ids(response: Any) -> List[str]:
    data, _meta = validate_paginated(response)
    return [row["id"] for row in data]


def assert_no_rows(response: Any) -> None:
    """An empty filter result is a normal empty array with a total_count of zero."""
    data, meta = validate_paginated(response)
    assert data == [], f"expected no rows, got {data}"
    assert meta["total_count"] == 0, f"expected total_count 0, got {meta['total_count']}"


def assert_row_count(response: Any, count: int) -> List[Dict[str, Any]]:
    """`total_count` is the number of rows matching the filter before pagination."""
    data, meta = validate_paginated(response)
    assert meta["total_count"] == count, (
        f"expected total_count {count}, got {meta['total_count']}"
    )
    assert len(data) == min(count, meta["limit"]), (
        f"expected {min(count, meta['limit'])} rows on the page, got {len(data)}"
    )
    return data
