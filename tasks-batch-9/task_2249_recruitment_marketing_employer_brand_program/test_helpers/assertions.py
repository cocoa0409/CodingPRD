"""Domain assertions shared by the test suite."""
from typing import Any, Dict, List, Optional, Sequence

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import TOTAL_CREDIT_BP


# ------------------------------------------------------------------ row shapes

def assert_mutable_row(data: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """A resource that can be edited exposes an id, both timestamps and a version."""
    assert is_valid_uuid(data["id"]), f"id is not a UUID: {data['id']}"
    assert is_iso8601_timestamp(data["created_at"]), data["created_at"]
    assert is_iso8601_timestamp(data["updated_at"]), data["updated_at"]
    assert isinstance(data["version"], int)
    if expected_version is not None:
        assert data["version"] == expected_version, (
            f"expected version {expected_version}, got {data['version']}"
        )


def assert_immutable_event_row(data: Dict[str, Any]) -> None:
    """An append-only event row carries an id and a creation stamp and nothing more."""
    assert is_valid_uuid(data["id"]), f"id is not a UUID: {data['id']}"
    assert is_iso8601_timestamp(data["created_at"]), data["created_at"]
    assert "updated_at" not in data, "an append-only row must not expose updated_at"
    assert "version" not in data, "an append-only row must not expose version"


def assert_millisecond_timestamp(value: str) -> None:
    """Timestamps are UTC with exactly three fractional digits."""
    assert isinstance(value, str), f"not a timestamp: {value!r}"
    assert value.endswith("Z"), f"timestamp is not UTC-suffixed: {value}"
    assert len(value) == 24, f"timestamp lacks millisecond precision: {value}"
    assert value[19] == ".", f"timestamp lacks millisecond precision: {value}"
    assert value[20:23].isdigit(), f"timestamp lacks millisecond precision: {value}"


def assert_fields_unchanged(
    before: Dict[str, Any], after: Dict[str, Any], fields: Sequence[str]
) -> None:
    for field in fields:
        assert after[field] == before[field], (
            f"{field} changed from {before[field]!r} to {after[field]!r}"
        )


# ------------------------------------------------------------------- ordering

def assert_ordered_by(
    rows: List[Dict[str, Any]], primary: str, secondary: Optional[str] = None
) -> None:
    """Rows come back sorted ascending by the declared keys."""
    def key(row):
        return (row[primary],) if secondary is None else (row[primary], row[secondary])

    keys = [key(row) for row in rows]
    assert keys == sorted(keys), f"rows are not ordered by {primary}/{secondary}: {keys}"


def assert_id_sequence(rows: List[Dict[str, Any]], expected_ids: Sequence[str]) -> None:
    assert [row["id"] for row in rows] == list(expected_ids)


# ------------------------------------------------------------ money and credit

def assert_cents(actual: Any, expected: int, label: str = "amount") -> None:
    assert isinstance(actual, int), f"{label} must be an integer number of cents: {actual!r}"
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_brand_health(actual: Any, expected: float) -> None:
    """Brand health is carried to two decimal places."""
    assert actual == pytest.approx(expected, abs=0.01), (
        f"expected brand health {expected}, got {actual}"
    )


def assert_basis_points_total(values: Sequence[int], expected: int = TOTAL_CREDIT_BP) -> None:
    assert sum(values) == expected, f"basis points sum to {sum(values)}, expected {expected}"


def assert_flight_pricing(
    flight: Dict[str, Any],
    flight_days: int,
    base_gross_cents: int,
    cost_tier: str,
    volume_discount_cents: int,
    platform_fee_cents: int,
    total_cost_cents: int,
) -> None:
    """Every pinned step of the flight price, so a wrong step cannot hide in the total."""
    assert flight["flight_days"] == flight_days, flight
    assert_cents(flight["base_gross_cents"], base_gross_cents, "base_gross_cents")
    assert flight["cost_tier"] == cost_tier, flight
    assert_cents(flight["volume_discount_cents"], volume_discount_cents, "volume_discount_cents")
    assert_cents(flight["platform_fee_cents"], platform_fee_cents, "platform_fee_cents")
    assert_cents(flight["total_cost_cents"], total_cost_cents, "total_cost_cents")


def assert_program_budget(
    program: Dict[str, Any], committed_budget_cents: int, available_budget_cents: int
) -> None:
    assert_cents(program["committed_budget_cents"], committed_budget_cents, "committed_budget_cents")
    assert_cents(program["available_budget_cents"], available_budget_cents, "available_budget_cents")


def assert_family_reservation(
    family: Dict[str, Any], reserved_cents: int, dedicated_available_cents: int
) -> None:
    assert_cents(family["reserved_cents"], reserved_cents, "reserved_cents")
    assert_cents(
        family["dedicated_available_cents"], dedicated_available_cents, "dedicated_available_cents"
    )


# --------------------------------------------------------------- budget ledger

def assert_ledger_entry(
    entry: Dict[str, Any],
    bucket: str,
    entry_type: str,
    delta_cents: int,
    reason: Optional[str] = None,
    source_type: Optional[str] = None,
    source_id: Optional[str] = None,
    sequence_no: Optional[int] = None,
) -> None:
    assert entry["bucket"] == bucket, entry
    assert entry["entry_type"] == entry_type, entry
    assert_cents(entry["delta_cents"], delta_cents, "delta_cents")
    if reason is not None:
        assert entry["reason"] == reason, entry
    if source_type is not None:
        assert entry["source_type"] == source_type, entry
    if source_id is not None:
        assert entry["source_id"] == source_id, entry
    if sequence_no is not None:
        assert entry["sequence_no"] == sequence_no, entry


def assert_ledger_buckets(
    entries: List[Dict[str, Any]], expected: Sequence[tuple]
) -> None:
    """``expected`` is a sequence of ``(bucket, entry_type, delta_cents)`` triples."""
    actual = [(e["bucket"], e["entry_type"], e["delta_cents"]) for e in entries]
    assert actual == list(expected), f"ledger draw was {actual}, expected {list(expected)}"


def assert_releases_mirror_reserves(
    reserves: List[Dict[str, Any]], releases: List[Dict[str, Any]]
) -> None:
    """One release per reservation: same bucket, negated amount, in reservation order."""
    ordered_reserves = sorted(reserves, key=lambda e: e["sequence_no"])
    ordered_releases = sorted(releases, key=lambda e: e["sequence_no"])
    assert len(ordered_releases) == len(ordered_reserves), (
        f"{len(ordered_reserves)} reservations produced {len(ordered_releases)} releases"
    )
    for reserve, release in zip(ordered_reserves, ordered_releases):
        assert release["bucket"] == reserve["bucket"], (reserve, release)
        assert release["delta_cents"] == -reserve["delta_cents"], (reserve, release)
        assert release["entry_type"] == "RELEASE", release
    assert sum(e["delta_cents"] for e in ordered_reserves + ordered_releases) == 0


def assert_sequence_numbers_ascend(entries: List[Dict[str, Any]]) -> None:
    numbers = [e["sequence_no"] for e in entries]
    assert numbers == sorted(numbers), f"sequence numbers are out of order: {numbers}"
    assert len(set(numbers)) == len(numbers), f"sequence numbers repeat: {numbers}"


# ------------------------------------------------------------------ channel mix

def assert_channel_mix(
    channel_mix: List[Dict[str, Any]], expected: Sequence[tuple]
) -> None:
    """``expected`` is a sequence of ``(channel_id, share_bp)`` pairs, in response order."""
    actual = [(entry["channel_id"], entry["share_bp"]) for entry in channel_mix]
    assert actual == list(expected), f"channel mix was {actual}, expected {list(expected)}"
    assert_basis_points_total([entry["share_bp"] for entry in channel_mix])
