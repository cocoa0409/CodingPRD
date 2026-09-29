"""Domain assertions for the condominium association API.

These wrap the repeated shape checks and the two conservation invariants the
PRD states, so tests read as statements about association behaviour rather than
as dictionary plumbing.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from .api_client import ApiClient

# ----------------------------------------------------------------------
# Envelope / common-field shape
# ----------------------------------------------------------------------
_COMMON_FIELDS = ("id", "created_at", "updated_at", "version")
_APPEND_ONLY_FIELDS = ("id", "created_at")


def assert_common_fields(entity: Mapping[str, Any]) -> None:
    """Every versioned entity carries id, created_at, updated_at and version."""
    for field in _COMMON_FIELDS:
        assert field in entity, f"missing common field {field!r}: {entity}"
    assert is_valid_uuid(entity["id"]), f"id is not a uuid: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert is_iso8601_timestamp(entity["updated_at"]), entity["updated_at"]
    assert isinstance(entity["version"], int) and entity["version"] >= 1, entity["version"]


def assert_append_only_fields(entity: Mapping[str, Any]) -> None:
    """Ledger entries and votes carry only id and created_at.

    The PRD forbids implementations from emitting updated_at or version on
    those two entities, so their presence is a failure, not a nicety.
    """
    for field in _APPEND_ONLY_FIELDS:
        assert field in entity, f"missing field {field!r}: {entity}"
    assert is_valid_uuid(entity["id"]), f"id is not a uuid: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert "updated_at" not in entity, "append-only entity must not emit updated_at"
    assert "version" not in entity, "append-only entity must not emit version"


_INSTANT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})$"
)


def looks_like_instant(value: Any) -> bool:
    """True for an ISO 8601 UTC instant string in any fractional-digit form."""
    return isinstance(value, str) and bool(_INSTANT_RE.match(value))


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating any fractional-digit form.

    The PRD pins the *instant* a field carries -- "stamps ``notice_sent_at``
    with the logical clock" -- and pins the three-fractional-digit rendering
    only for ``created_at``, ``updated_at`` and ``api_request_timestamp``.  It
    is therefore the instant, not its textual rendering, that an assertion on
    any other timestamp field may demand.
    """
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def same_instant(got: Any, want: Any) -> bool:
    """Instant equality that ignores fractional-digit rendering only."""
    if looks_like_instant(got) and looks_like_instant(want):
        return parse_instant(got) == parse_instant(want)
    return bool(got == want)


def assert_instant_equals(got: Any, want: Any, label: str = "timestamp") -> None:
    """Assert two ISO 8601 UTC instants name the same moment, to the second."""
    assert looks_like_instant(got), f"{label} is not an ISO 8601 instant: {got!r}"
    assert same_instant(got, want), f"{label}: expected {want!r}, got {got!r}"


def assert_fields_equal(entity: Mapping[str, Any], **expected: Any) -> None:
    """Assert a batch of field values with one readable message per mismatch."""
    mismatches = []
    for field, want in expected.items():
        assert field in entity, f"missing field {field!r}: {sorted(entity)}"
        got = entity[field]
        if not same_instant(got, want):
            mismatches.append(f"{field}: expected {want!r}, got {got!r}")
    assert not mismatches, "; ".join(mismatches)


# ----------------------------------------------------------------------
# Cents / basis-point discipline
# ----------------------------------------------------------------------
def assert_integer_cents(entity: Mapping[str, Any], *fields: str) -> None:
    """Money fields are integer cents -- never floats, never strings."""
    for field in fields:
        value = entity[field]
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{field} must be integer cents, got {type(value).__name__}: {value!r}"
        )


def assert_basis_points(entity: Mapping[str, Any], *fields: str) -> None:
    """Basis-point fields are integers in [0, 10000]."""
    for field in fields:
        value = entity[field]
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{field} must be an integer basis-point value, got {value!r}"
        )
        assert 0 <= value <= 10_000, f"{field} out of basis-point range: {value}"


# ----------------------------------------------------------------------
# Conservation invariants stated by the PRD
# ----------------------------------------------------------------------
def assert_unit_ledger_conserved(
    api: ApiClient, unit_id: str, headers: dict[str, str]
) -> int:
    """INVARIANT L: a unit's balance_due_cents equals the signed sum of all of
    its ledger entries -- POSTED and REVERSED rows alike.

    Returns the signed sum so callers can assert its exact value too.
    """
    unit = validate_success(api.get_unit(unit_id, headers))
    entries, _ = validate_paginated(
        api.list_ledger_entries(headers, params={"unit_id": unit_id, "limit": 100})
    )
    signed_sum = sum(int(entry["amount_cents"]) for entry in entries)
    assert unit["balance_due_cents"] == signed_sum, (
        f"INVARIANT L violated on unit {unit_id}: balance_due_cents "
        f"{unit['balance_due_cents']} != signed ledger sum {signed_sum}"
    )
    return signed_sum


#: Work-order statuses whose encumbrance still counts against a contract.
ENCUMBERING_WORK_ORDER_STATUSES = ("SCHEDULED", "IN_PROGRESS", "ON_HOLD", "COMPLETED")


def assert_contract_authorization_conserved(
    api: ApiClient, contract_id: str, headers: dict[str, str]
) -> int:
    """INVARIANT E: a contract's committed_cents equals the sum of
    encumbered_cents over its work orders in SCHEDULED, IN_PROGRESS, ON_HOLD or
    COMPLETED.  An ON_HOLD order releases nothing.

    Returns the summed encumbrance.
    """
    contracts, _ = validate_paginated(
        api.list_vendor_contracts(headers, params={"limit": 100})
    )
    contract = next((c for c in contracts if c["id"] == contract_id), None)
    assert contract is not None, f"contract {contract_id} not listed"
    orders, _ = validate_paginated(
        api.list_work_orders(headers, params={"contract_id": contract_id, "limit": 100})
    )
    total = sum(
        int(order["encumbered_cents"])
        for order in orders
        if order["status"] in ENCUMBERING_WORK_ORDER_STATUSES
    )
    assert contract["committed_cents"] == total, (
        f"INVARIANT E violated on contract {contract_id}: committed_cents "
        f"{contract['committed_cents']} != encumbrance sum {total}"
    )
    return total


# ----------------------------------------------------------------------
# Ledger helpers
# ----------------------------------------------------------------------
def fetch_ledger_entries(
    api: ApiClient, headers: dict[str, str], **filters: Any
) -> list[dict[str, Any]]:
    """List ledger entries with the given filters, oldest first."""
    params: dict[str, Any] = {"limit": 100}
    params.update(filters)
    entries, _ = validate_paginated(api.list_ledger_entries(headers, params=params))
    return list(entries)


def find_entry(
    entries: Iterable[Mapping[str, Any]], **criteria: Any
) -> Mapping[str, Any]:
    """Return the single ledger entry matching every criterion."""
    matches = [
        entry
        for entry in entries
        if all(entry.get(key) == value for key, value in criteria.items())
    ]
    assert len(matches) == 1, (
        f"expected exactly one entry matching {criteria}, found {len(matches)}"
    )
    return matches[0]


def count_entries(entries: Iterable[Mapping[str, Any]], **criteria: Any) -> int:
    """Count ledger entries matching every criterion."""
    return sum(
        1
        for entry in entries
        if all(entry.get(key) == value for key, value in criteria.items())
    )


def bucket_totals(entries: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Signed cents per bucket across the supplied entries."""
    totals: dict[str, int] = {}
    for entry in entries:
        bucket = entry.get("bucket")
        if bucket is None:
            continue
        totals[bucket] = totals.get(bucket, 0) + int(entry["amount_cents"])
    return totals


# ----------------------------------------------------------------------
# Allocation-snapshot helpers
# ----------------------------------------------------------------------
def snapshot_row(snapshot: Iterable[Mapping[str, Any]], unit_id: str) -> Mapping[str, Any]:
    """The allocation-snapshot row for one unit."""
    rows = [row for row in snapshot if row.get("unit_id") == unit_id]
    assert len(rows) == 1, f"expected one snapshot row for {unit_id}, got {len(rows)}"
    return rows[0]


def allocation_row(
    allocation: Iterable[Mapping[str, Any]], unit_id: str
) -> Mapping[str, Any]:
    """The deductible-allocation row for one unit."""
    rows = [row for row in allocation if row.get("unit_id") == unit_id]
    assert len(rows) == 1, f"expected one allocation row for {unit_id}, got {len(rows)}"
    return rows[0]


def assert_allocation_sums_to(
    allocation: Iterable[Mapping[str, Any]], field: str, expected_total: int
) -> None:
    """A distributed amount must sum back to the pool it came from."""
    total = sum(int(row[field]) for row in allocation)
    assert total == expected_total, (
        f"allocation {field} sums to {total}, expected {expected_total}"
    )


# ----------------------------------------------------------------------
# Read-back convenience
# ----------------------------------------------------------------------
def read_association(api: ApiClient, association_id: str, headers: dict[str, str]):
    return validate_success(api.get_association(association_id, headers))


def read_unit(api: ApiClient, unit_id: str, headers: dict[str, str]):
    return validate_success(api.get_unit(unit_id, headers))


def read_by_id(
    api_call_response, entity_id: str
) -> dict[str, Any]:
    """Pick one entity out of a paginated list response by id."""
    rows, _ = validate_paginated(api_call_response)
    match = next((row for row in rows if row["id"] == entity_id), None)
    assert match is not None, f"entity {entity_id} not present in listing"
    return match


def read_work_order(api: ApiClient, work_order_id: str, headers: dict[str, str]):
    return read_by_id(api.list_work_orders(headers, params={"limit": 100}), work_order_id)


def read_contract(api: ApiClient, contract_id: str, headers: dict[str, str]):
    return read_by_id(
        api.list_vendor_contracts(headers, params={"limit": 100}), contract_id
    )


def read_element(api: ApiClient, element_id: str, headers: dict[str, str]):
    return read_by_id(
        api.list_common_elements(headers, params={"limit": 100}), element_id
    )


def read_budget(api: ApiClient, budget_id: str, headers: dict[str, str]):
    return read_by_id(api.list_budgets(headers, params={"limit": 100}), budget_id)


def read_special_assessment(api: ApiClient, assessment_id: str, headers: dict[str, str]):
    return read_by_id(
        api.list_special_assessments(headers, params={"limit": 100}), assessment_id
    )


def read_meeting(api: ApiClient, meeting_id: str, headers: dict[str, str]):
    return read_by_id(
        api.list_board_meetings(headers, params={"limit": 100}), meeting_id
    )


def read_claim(api: ApiClient, claim_id: str, headers: dict[str, str]):
    return read_by_id(
        api.list_insurance_claims(headers, params={"limit": 100}), claim_id
    )


def read_case(api: ApiClient, case_id: str, headers: dict[str, str]):
    return read_by_id(
        api.list_violation_cases(headers, params={"limit": 100}), case_id
    )


def read_certificate(api: ApiClient, certificate_id: str, headers: dict[str, str]):
    return read_by_id(
        api.list_resale_certificates(headers, params={"limit": 100}), certificate_id
    )


def read_vote(api: ApiClient, vote_id: str, headers: dict[str, str]):
    return read_by_id(api.list_votes(headers, params={"limit": 100}), vote_id)


def read_billing_run(api: ApiClient, billing_run_id: str, headers: dict[str, str]):
    return read_by_id(api.list_billing_runs(headers, params={"limit": 100}), billing_run_id)


def read_ledger_entry(api: ApiClient, entry_id: str, headers: dict[str, str]):
    return read_by_id(api.list_ledger_entries(headers, params={"limit": 100}), entry_id)
