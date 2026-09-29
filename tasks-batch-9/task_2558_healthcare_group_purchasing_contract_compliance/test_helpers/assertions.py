"""Domain assertion helpers layered on the shared primitives."""

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

Json = Dict[str, Any]

_MILLIS_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_BARE_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --- identity / audit ------------------------------------------------------


def assert_identifier(value: Any) -> None:
    """Identifiers are UUIDs carried as strings with no prefix."""
    assert isinstance(value, str), "identifier must be a string, got {0!r}".format(value)
    assert is_valid_uuid(value), "identifier is not a UUID: {0!r}".format(value)


def assert_audit_timestamps(entity: Json) -> None:
    """``created_at`` and ``updated_at`` are ISO 8601 with three fractional digits."""
    for field in ("created_at", "updated_at"):
        value = entity.get(field)
        assert isinstance(value, str), "{0} must be a string, got {1!r}".format(field, value)
        assert is_iso8601_timestamp(value), "{0} is not ISO 8601: {1!r}".format(field, value)
        assert _MILLIS_INSTANT.match(value), (
            "{0} must carry exactly three fractional digits: {1!r}".format(field, value)
        )


def assert_versioned_entity(entity: Json, expected_version: Optional[int] = None) -> None:
    """A resource that carries the full audit trio plus an integer ``version``."""
    assert_identifier(entity.get("id"))
    assert_audit_timestamps(entity)
    version = entity.get("version")
    assert isinstance(version, int) and not isinstance(version, bool), (
        "version must be an integer, got {0!r}".format(version)
    )
    assert version >= 1, "version must start at 1, got {0!r}".format(version)
    if expected_version is not None:
        assert version == expected_version, "expected version {0}, got {1}".format(
            expected_version, version
        )


def assert_immutable_row(entity: Json) -> None:
    """A purchase line: ``id`` and ``created_at`` only, no ``updated_at``, no ``version``."""
    assert_identifier(entity.get("id"))
    created_at = entity.get("created_at")
    assert isinstance(created_at, str) and is_iso8601_timestamp(created_at), (
        "created_at is not ISO 8601: {0!r}".format(created_at)
    )
    assert "updated_at" not in entity, "purchase lines must not carry updated_at"
    assert "version" not in entity, "purchase lines must not carry version"


def assert_version_bump(new_entity: Json, old_version: int, by: int = 1) -> None:
    actual = new_entity.get("version")
    assert actual == old_version + by, (
        "expected version {0} (was {1}, +{2}), got {3}".format(
            old_version + by, old_version, by, actual
        )
    )


def assert_version_unchanged(entity: Json, expected_version: int) -> None:
    assert entity.get("version") == expected_version, (
        "version moved: expected it to stay {0}, got {1}".format(
            expected_version, entity.get("version")
        )
    )


def assert_fields_unchanged(before: Json, after: Json, *fields: str) -> None:
    for field in fields:
        assert before.get(field) == after.get(field), (
            "field {0} changed from {1!r} to {2!r}".format(
                field, before.get(field), after.get(field)
            )
        )


# --- instants and dates ----------------------------------------------------


def normalize_instant(value: str) -> str:
    """Strip a zero-millisecond suffix so instants compare by value."""
    assert isinstance(value, str), "instant must be a string, got {0!r}".format(value)
    assert _BARE_INSTANT.match(value), "not a UTC instant: {0!r}".format(value)
    return value.replace(".000Z", "Z")


def assert_instant_equals(actual: Any, expected: str) -> None:
    assert normalize_instant(actual) == normalize_instant(expected), (
        "expected instant {0}, got {1}".format(expected, actual)
    )


def assert_date(value: Any, expected: Optional[str] = None) -> None:
    """A calendar date in ``YYYY-MM-DD`` form, optionally equal to ``expected``."""
    assert isinstance(value, str) and _DATE.match(value), (
        "expected a YYYY-MM-DD date, got {0!r}".format(value)
    )
    if expected is not None:
        assert value == expected, "expected date {0}, got {1}".format(expected, value)


# --- money, rates and percentages -----------------------------------------


def assert_cents(value: Any, expected: Optional[int] = None) -> None:
    """An integer count of cents, optionally equal to ``expected``."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        "money must be an integer count of cents, got {0!r}".format(value)
    )
    if expected is not None:
        assert value == expected, "expected {0} cents, got {1}".format(expected, value)


def assert_pct(actual: Any, expected: float) -> None:
    """Compare a two-decimal percentage without inviting float noise."""
    assert actual is not None, "expected percentage {0}, got None".format(expected)
    assert round(float(actual) - float(expected), 6) == 0, (
        "expected percentage {0}, got {1}".format(expected, actual)
    )


def assert_score(actual: Any, expected: float) -> None:
    assert actual is not None, "expected score {0}, got None".format(expected)
    assert round(float(actual) - float(expected), 6) == 0, (
        "expected score {0}, got {1}".format(expected, actual)
    )


# --- ladders ---------------------------------------------------------------


def assert_tier_ladder_echoed(contract: Json, expected: Sequence[Json]) -> None:
    tiers = contract.get("tiers")
    assert isinstance(tiers, list), "tiers must be an array, got {0!r}".format(tiers)
    assert len(tiers) == len(expected), "expected {0} tier rows, got {1}".format(
        len(expected), len(tiers)
    )
    for stored, wanted in zip(tiers, expected):
        for key, value in wanted.items():
            if key.endswith("_pct"):
                assert_pct(stored.get(key), value)
            else:
                assert stored.get(key) == value, (
                    "tier row {0}: expected {1}={2!r}, got {3!r}".format(
                        stored.get("tier_code"), key, value, stored.get(key)
                    )
                )


def assert_holdback_ladder_echoed(contract: Json, expected: Sequence[Json]) -> None:
    rungs = contract.get("holdback_tiers")
    assert isinstance(rungs, list), "holdback_tiers must be an array, got {0!r}".format(rungs)
    assert len(rungs) == len(expected), "expected {0} holdback rungs, got {1}".format(
        len(expected), len(rungs)
    )
    for stored, wanted in zip(rungs, expected):
        for key, value in wanted.items():
            assert stored.get(key) == value, (
                "holdback rung: expected {0}={1!r}, got {2!r}".format(
                    key, value, stored.get(key)
                )
            )


# --- pagination ------------------------------------------------------------


def assert_page_meta(
    meta: Json,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    if limit is not None:
        assert meta.get("limit") == limit, "expected limit {0}, got {1}".format(
            limit, meta.get("limit")
        )
    if offset is not None:
        assert meta.get("offset") == offset, "expected offset {0}, got {1}".format(
            offset, meta.get("offset")
        )
    if total_count is not None:
        assert meta.get("total_count") == total_count, (
            "expected total_count {0}, got {1}".format(total_count, meta.get("total_count"))
        )
    if has_more is not None:
        assert meta.get("has_more") is has_more, "expected has_more {0}, got {1}".format(
            has_more, meta.get("has_more")
        )


# --- purchase lines --------------------------------------------------------


def assert_line_classification(
    line: Json,
    classification: str,
    matched_vendor_item_number: Any = "__unset__",
    contract_units: Any = "__unset__",
    reject_reason: Any = "__unset__",
) -> None:
    assert line.get("classification") == classification, (
        "line {0}: expected classification {1}, got {2}".format(
            line.get("member_item_number"), classification, line.get("classification")
        )
    )
    if matched_vendor_item_number != "__unset__":
        assert line.get("matched_vendor_item_number") == matched_vendor_item_number, (
            "line {0}: expected matched_vendor_item_number {1!r}, got {2!r}".format(
                line.get("member_item_number"),
                matched_vendor_item_number,
                line.get("matched_vendor_item_number"),
            )
        )
    if contract_units != "__unset__":
        assert line.get("contract_units") == contract_units, (
            "line {0}: expected contract_units {1}, got {2}".format(
                line.get("member_item_number"), contract_units, line.get("contract_units")
            )
        )
    if reject_reason != "__unset__":
        assert line.get("reject_reason") == reject_reason, (
            "line {0}: expected reject_reason {1!r}, got {2!r}".format(
                line.get("member_item_number"), reject_reason, line.get("reject_reason")
            )
        )


def line_by_item_and_quantity(
    lines: Iterable[Json], member_item_number: str, quantity_units: int
) -> Json:
    matches = [
        line
        for line in lines
        if line.get("member_item_number") == member_item_number
        and line.get("quantity_units") == quantity_units
    ]
    assert len(matches) == 1, (
        "expected exactly one line for {0} x {1}, found {2}".format(
            member_item_number, quantity_units, len(matches)
        )
    )
    return matches[0]


# --- fee waterfall --------------------------------------------------------


def assert_waterfall_conserved(distribution: Json) -> None:
    """member_share_total + undistributed + gpo_retained must equal gross_pool."""
    gross = distribution.get("gross_pool_cents")
    shares = distribution.get("member_share_total_cents")
    undistributed = distribution.get("undistributed_cents")
    retained = distribution.get("gpo_retained_cents")
    for name, value in (
        ("gross_pool_cents", gross),
        ("member_share_total_cents", shares),
        ("undistributed_cents", undistributed),
        ("gpo_retained_cents", retained),
    ):
        assert_cents(value)
        assert value >= 0, "{0} must not be negative, got {1}".format(name, value)
    assert shares + undistributed + retained == gross, (
        "waterfall leaks: {0} + {1} + {2} != {3}".format(shares, undistributed, retained, gross)
    )


def share_for_member(distribution: Json, member_id: str) -> Json:
    shares = distribution.get("member_shares")
    assert isinstance(shares, list), "member_shares must be an array, got {0!r}".format(shares)
    matches = [row for row in shares if row.get("member_id") == member_id]
    assert len(matches) == 1, "expected exactly one share row for {0}, found {1}".format(
        member_id, len(matches)
    )
    return matches[0]


def assert_member_share(
    distribution: Json, member_id: str, weight_cents: int, share_cents: int
) -> None:
    row = share_for_member(distribution, member_id)
    assert row.get("weight_cents") == weight_cents, (
        "member {0}: expected weight_cents {1}, got {2}".format(
            member_id, weight_cents, row.get("weight_cents")
        )
    )
    assert row.get("share_cents") == share_cents, (
        "member {0}: expected share_cents {1}, got {2}".format(
            member_id, share_cents, row.get("share_cents")
        )
    )


# --- leakage report -------------------------------------------------------


def assert_top_items(
    top_items: Any, expected: Sequence[Tuple[str, int, int]]
) -> None:
    """``expected`` is an ordered sequence of (member_item_number, spend, quantity)."""
    assert isinstance(top_items, list), "top_items must be an array, got {0!r}".format(top_items)
    assert len(top_items) == len(expected), "expected {0} top_items, got {1}".format(
        len(expected), len(top_items)
    )
    for index, (number, spend, quantity) in enumerate(expected):
        row = top_items[index]
        assert row.get("member_item_number") == number, (
            "top_items[{0}]: expected {1}, got {2}".format(
                index, number, row.get("member_item_number")
            )
        )
        assert row.get("spend_cents") == spend, (
            "top_items[{0}] {1}: expected spend_cents {2}, got {3}".format(
                index, number, spend, row.get("spend_cents")
            )
        )
        assert row.get("quantity_units") == quantity, (
            "top_items[{0}] {1}: expected quantity_units {2}, got {3}".format(
                index, number, quantity, row.get("quantity_units")
            )
        )


# --- collection helpers ---------------------------------------------------


def ids_of(rows: Iterable[Json]) -> List[str]:
    return [row["id"] for row in rows]


def assert_exact_ids(rows: Iterable[Json], expected_ids: Iterable[str]) -> None:
    actual = sorted(ids_of(rows))
    wanted = sorted(expected_ids)
    assert actual == wanted, "expected rows {0}, got {1}".format(wanted, actual)
