"""Reusable domain assertions.

These wrap the checks that recur across scenarios: envelope shape, the common
record properties, the bed-count identity of a care unit, the trust-fund replay
invariant, collection ordering and the counter object returned by the nightly
checkpoint.
"""

from typing import Any, Dict, Iterable, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data, validate_paginated, validate_success

PAGINATION_META_FIELDS = ("limit", "offset", "total_count", "has_more")


def assert_fields(record: Dict[str, Any], **expected: Any) -> None:
    """Assert that each named field of `record` equals the expected value."""
    for field, value in expected.items():
        assert field in record, f"expected field {field!r} on record, got keys {sorted(record)}"
        assert record[field] == value, (
            f"expected {field}={value!r}, got {record[field]!r}"
        )


def assert_common_fields(record: Dict[str, Any]) -> None:
    """Assert the four common record properties are present and well formed."""
    for field in ("id", "created_at", "updated_at", "version"):
        assert field in record, f"expected common field {field!r}, got keys {sorted(record)}"
    assert isinstance(record["id"], str) and record["id"], "id must be a non-empty string"
    assert isinstance(record["version"], int), "version must be an integer"
    assert record["version"] >= 1, "version starts at 1"


def assert_immutable_record_fields(record: Dict[str, Any]) -> None:
    """A cost-share determination carries only `id` and `created_at`."""
    assert "id" in record and "created_at" in record
    assert "updated_at" not in record, "an immutable record carries no updated_at"
    assert "version" not in record, "an immutable record carries no version"


def assert_single_object_envelope(response) -> Dict[str, Any]:
    """Validate a single-object response and assert it carries no pagination meta."""
    body = response.json()
    meta = body.get("meta", {})
    for field in PAGINATION_META_FIELDS:
        assert field not in meta, f"single-object responses carry no {field!r} in meta"
    assert body.get("response_type") == "object"
    return validate_success(response, response.status_code)


def assert_page_meta(
    meta: Dict[str, Any],
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    for field in PAGINATION_META_FIELDS:
        assert field in meta, f"expected {field!r} in array response meta"
    if limit is not None:
        assert meta["limit"] == limit, f"expected limit {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"expected offset {offset}, got {meta['offset']}"
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"expected total_count {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"expected has_more {has_more}, got {meta['has_more']}"
        )


def assert_ordered_by(
    rows: Sequence[Dict[str, Any]], keys: Sequence[str], descending: Sequence[bool] = ()
) -> None:
    """Assert rows are sorted by the given keys, honouring per-key direction."""
    directions = list(descending) + [False] * (len(keys) - len(descending))
    for earlier, later in zip(rows, rows[1:]):
        for key, is_desc in zip(keys, directions):
            a, b = earlier.get(key), later.get(key)
            if a == b:
                continue
            if is_desc:
                assert a > b, f"rows not ordered by {key} descending: {a!r} then {b!r}"
            else:
                assert a < b, f"rows not ordered by {key} ascending: {a!r} then {b!r}"
            break


def assert_ids_in_order(rows: Sequence[Dict[str, Any]], expected_ids: Sequence[str]) -> None:
    actual = [row["id"] for row in rows]
    assert actual == list(expected_ids), f"expected ids {list(expected_ids)}, got {actual}"


def assert_bed_arithmetic(unit: Dict[str, Any]) -> None:
    """The four bed counts of a unit must sum to its licensed bed count."""
    total = (
        unit["out_of_service_bed_count"]
        + unit["occupied_bed_count"]
        + unit["held_bed_count"]
        + unit["available_bed_count"]
    )
    assert total == unit["licensed_bed_count"], (
        "out_of_service + occupied + held + available must equal licensed_bed_count; "
        f"got {total} against {unit['licensed_bed_count']}"
    )


def assert_bed_counts(
    unit: Dict[str, Any],
    occupied: Optional[int] = None,
    held: Optional[int] = None,
    available: Optional[int] = None,
    posture: Optional[str] = None,
) -> None:
    if occupied is not None:
        assert unit["occupied_bed_count"] == occupied, (
            f"expected occupied_bed_count {occupied}, got {unit['occupied_bed_count']}"
        )
    if held is not None:
        assert unit["held_bed_count"] == held, (
            f"expected held_bed_count {held}, got {unit['held_bed_count']}"
        )
    if available is not None:
        assert unit["available_bed_count"] == available, (
            f"expected available_bed_count {available}, got {unit['available_bed_count']}"
        )
    if posture is not None:
        assert unit["operational_posture"] == posture, (
            f"expected operational_posture {posture}, got {unit['operational_posture']}"
        )
    assert_bed_arithmetic(unit)


def assert_ledger_replay(rows: Iterable[Dict[str, Any]], resident_balance: int) -> None:
    """The resident balance must equal the sum of every signed amount in the ledger."""
    signed = [row["signed_amount_cents"] for row in rows]
    assert sum(signed) == resident_balance, (
        f"ledger sums to {sum(signed)} but resident balance is {resident_balance}"
    )


def assert_running_balances(rows: Sequence[Dict[str, Any]]) -> None:
    """Each row's balance_after_cents must be the running sum in replay order."""
    running = 0
    for row in rows:
        running += row["signed_amount_cents"]
        assert row["balance_after_cents"] == running, (
            f"row {row['id']} reports balance {row['balance_after_cents']}, replay gives {running}"
        )


def assert_census_counters(result: Dict[str, Any], **expected: Any) -> None:
    """Assert the counter object returned by the nightly checkpoint."""
    for field in (
        "generated_census_day_count",
        "pna_credited_resident_count",
        "cost_share_debited_resident_count",
        "skipped_cost_share_debit_count",
        "offered_waitlist_entry_count",
        "expired_offer_count",
        "review_due_care_plan_count",
        "current_utc",
    ):
        assert field in result, f"expected checkpoint counter {field!r}, got keys {sorted(result)}"
    assert_fields(result, **expected)


def assert_version_advanced(before: int, after: int, by: int = 1) -> None:
    assert after == before + by, f"expected version {before} + {by}, got {after}"


def collect_page(response) -> List[Dict[str, Any]]:
    data, _meta = validate_paginated(response)
    return data


def data_of(response) -> Dict[str, Any]:
    """Lenient extraction used by fixtures that only need the created record."""
    return get_success_data(response)
