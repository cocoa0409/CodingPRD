"""
Domain assertions layered on top of the generic envelope validators.

The helpers here exist so a test reads as the accounting statement it is making:
a lot's gross price splits into a breakage reserve and deferred revenue, a
rollforward's eleven figures tie together, a reopen restores what a close moved.
Anything that only checks envelope shape delegates to the generic validators.
"""

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.types import (
    COMMON_FIELDS,
    IMMUTABLE_COMMON_FIELDS,
    LIABILITY_ROLLFORWARD_FIELDS,
    MUTABLE_ONLY_FIELDS,
    expected_fields,
)


# ─── Envelope shortcuts ──────────────────────────────────────────────────────
def assert_ok(response) -> Dict[str, Any]:
    """A 200 carrying one object; returns the object."""
    return validate_success(response, 200)


def assert_created(response) -> Dict[str, Any]:
    """A 201 carrying a freshly minted entity at version 1; returns the entity."""
    entity = validate_success(response, 201)
    assert_common_fields(entity, expected_version=1)
    return entity


def assert_envelope_object(response, expected_status: int = 200) -> Dict[str, Any]:
    """A success envelope whose response_type is 'object'."""
    data = validate_success(response, expected_status)
    body = response.json()
    assert body["response_type"] == "object", (
        f"Expected response_type 'object', got '{body['response_type']}'"
    )
    assert isinstance(data, dict), f"Expected an object in data, got {type(data)}"
    return data


def assert_envelope_array(response) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """A success envelope whose response_type is 'array'; returns (rows, meta)."""
    rows, meta = validate_paginated(response)
    body = response.json()
    assert body["response_type"] == "array", (
        f"Expected response_type 'array', got '{body['response_type']}'"
    )
    assert isinstance(rows, list), f"Expected a list in data, got {type(rows)}"
    return rows, meta


def assert_error(response, expected_error_id: str) -> Dict[str, Any]:
    """
    An error envelope carrying exactly the expected error_id, with the HTTP
    status cross-checked against the registered mapping.
    """
    return validate_error(response, expected_error_id)


# ─── System fields ───────────────────────────────────────────────────────────
def assert_common_fields(
    entity: Mapping[str, Any], expected_version: Optional[int] = None
) -> None:
    """A mutable entity carries a UUID id, two timestamps and a positive version."""
    for field in COMMON_FIELDS:
        assert field in entity, f"Missing common field '{field}'"
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"created_at is not ISO-8601: {entity['created_at']!r}"
    )
    assert is_iso8601_timestamp(entity["updated_at"]), (
        f"updated_at is not ISO-8601: {entity['updated_at']!r}"
    )
    assert isinstance(entity["version"], int), "version must be an integer"
    assert entity["version"] >= 1, f"version must start at 1, got {entity['version']}"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"Expected version {expected_version}, got {entity['version']}"
        )


def assert_immutable_common_fields(entity: Mapping[str, Any]) -> None:
    """
    An append-only ledger row carries only id and created_at, and must not
    expose the mutable-entity system fields at all.
    """
    for field in IMMUTABLE_COMMON_FIELDS:
        assert field in entity, f"Missing immutable common field '{field}'"
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"created_at is not ISO-8601: {entity['created_at']!r}"
    )
    for field in MUTABLE_ONLY_FIELDS:
        assert field not in entity, (
            f"An immutable row must not carry '{field}', got {entity.get(field)!r}"
        )


def assert_representation_complete(entity: Mapping[str, Any], entity_name: str) -> None:
    """Every field the contract declares for this entity is present."""
    missing = [f for f in expected_fields(entity_name) if f not in entity]
    assert not missing, f"{entity_name} representation is missing {missing}"


def assert_version(entity: Mapping[str, Any], expected: int) -> None:
    assert entity["version"] == expected, (
        f"Expected version {expected}, got {entity['version']}"
    )


def assert_unchanged(before: Mapping[str, Any], after: Mapping[str, Any], *fields: str) -> None:
    """Named fields hold the value they held before the operation."""
    drifted = {
        field: (before.get(field), after.get(field))
        for field in fields
        if before.get(field) != after.get(field)
    }
    assert not drifted, f"Fields moved when they should not have: {drifted}"


# ─── Field comparison ────────────────────────────────────────────────────────
def assert_fields(entity: Mapping[str, Any], **expected: Any) -> None:
    """
    Compare many fields at once and report every mismatch together, so one run
    shows the whole shape of a wrong calculation instead of its first symptom.
    """
    mismatches = []
    for field, want in expected.items():
        assert field in entity, f"Missing field '{field}' in {sorted(entity.keys())}"
        got = entity[field]
        if got != want:
            mismatches.append(f"{field}: expected {want!r}, got {got!r}")
    assert not mismatches, "Field mismatches:\n  " + "\n  ".join(mismatches)


def assert_null_fields(entity: Mapping[str, Any], *fields: str) -> None:
    """Named fields are present and null."""
    for field in fields:
        assert field in entity, f"Missing field '{field}'"
        assert entity[field] is None, f"Expected {field} to be null, got {entity[field]!r}"


def assert_not_null_fields(entity: Mapping[str, Any], *fields: str) -> None:
    """Named fields are present and carry a value."""
    for field in fields:
        assert field in entity, f"Missing field '{field}'"
        assert entity[field] is not None, f"Expected {field} to be set, got null"


def assert_integer_cents(entity: Mapping[str, Any], *fields: str) -> None:
    """Money fields are integers, never floats and never strings."""
    for field in fields:
        assert field in entity, f"Missing field '{field}'"
        value = entity[field]
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{field} must be an integer number of cents, got {value!r}"
        )


def assert_utc_timestamp(entity: Mapping[str, Any], *fields: str) -> None:
    """Named fields carry an ISO-8601 UTC instant."""
    for field in fields:
        assert field in entity, f"Missing field '{field}'"
        value = entity[field]
        assert isinstance(value, str) and is_iso8601_timestamp(value), (
            f"{field} must be an ISO-8601 UTC timestamp, got {value!r}"
        )


# ─── Listing and pagination ──────────────────────────────────────────────────
def assert_page(
    response,
    expected_ids: Optional[Sequence[str]] = None,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """A list read whose window and contents match, in the order given."""
    rows, meta = assert_envelope_array(response)
    if expected_ids is not None:
        assert [row["id"] for row in rows] == list(expected_ids), (
            f"Expected ids {list(expected_ids)}, got {[row['id'] for row in rows]}"
        )
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"Expected total_count {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"Expected has_more {has_more}, got {meta['has_more']}"
        )
    if limit is not None:
        assert meta["limit"] == limit, f"Expected limit {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"Expected offset {offset}, got {meta['offset']}"
    return rows


def assert_created_at_ascending(rows: Iterable[Mapping[str, Any]]) -> None:
    """Rows arrive in created_at ascending order."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"Rows are not created_at ascending: {stamps}"


def assert_allocation_seq_ascending(rows: Sequence[Mapping[str, Any]]) -> None:
    """Ledger rows arrive by allocation_seq ascending, then created_at ascending."""
    keys = [(row["allocation_seq"], row["created_at"]) for row in rows]
    assert keys == sorted(keys), (
        f"Ledger rows are not (allocation_seq, created_at) ascending: {keys}"
    )


# ─── Domain identities ───────────────────────────────────────────────────────
def assert_lot_split(lot: Mapping[str, Any]) -> None:
    """
    A lot's gross standalone price divides exactly into the breakage reserve and
    the deferred revenue it defers.
    """
    assert (
        lot["breakage_reserve_cents"] + lot["deferred_revenue_cents"]
        == lot["gross_ssp_cents"]
    ), (
        "gross_ssp_cents must equal breakage_reserve_cents + deferred_revenue_cents: "
        f"{lot['gross_ssp_cents']} != {lot['breakage_reserve_cents']} + "
        f"{lot['deferred_revenue_cents']}"
    )


def assert_rollforward(rollforward: Mapping[str, Any], **expected: Any) -> None:
    """The rollforward read carries all twelve figures, and the named ones match."""
    for field in LIABILITY_ROLLFORWARD_FIELDS:
        assert field in rollforward, f"Rollforward is missing '{field}'"
    assert_fields(rollforward, **expected)


def assert_rollforward_ties(rollforward: Mapping[str, Any]) -> None:
    """
    The rollforward's own arithmetic holds: only the deferral of new issuance
    increases the liability and every release reduces it, the closing balance is
    the pre-catch-up figure plus the catch-up, and recognised breakage is the
    catch-up negated.
    """
    movement = (
        rollforward["opening_liability_cents"]
        + rollforward["issuance_deferred_cents"]
        - rollforward["redemption_recognized_cents"]
        - rollforward["remeasurement_delta_cents"]
        - rollforward["expiry_released_cents"]
    )
    assert rollforward["pre_catchup_liability_cents"] == movement, (
        "pre_catchup_liability_cents does not tie to opening plus movements: "
        f"{rollforward['pre_catchup_liability_cents']} != {movement}"
    )
    assert (
        rollforward["closing_liability_cents"]
        == rollforward["pre_catchup_liability_cents"]
        + rollforward["catch_up_adjustment_cents"]
    ), "closing_liability_cents does not tie to pre-catch-up plus the catch-up"
    assert (
        rollforward["breakage_recognized_cents"]
        == -rollforward["catch_up_adjustment_cents"]
    ), (
        "breakage_recognized_cents must be the negation of catch_up_adjustment_cents: "
        f"{rollforward['breakage_recognized_cents']} vs "
        f"{rollforward['catch_up_adjustment_cents']}"
    )


def assert_statement_net(statement: Mapping[str, Any]) -> None:
    """
    A statement's billed amount and its deferred remainder together account for
    the whole candidate: exactly one of them carries it.
    """
    assert (
        statement["net_due_cents"] == 0
        or statement["deferred_below_minimum_cents"] == 0
    ), (
        "A statement bills the candidate or defers it, never both: "
        f"net_due_cents={statement['net_due_cents']}, "
        f"deferred_below_minimum_cents={statement['deferred_below_minimum_cents']}"
    )
