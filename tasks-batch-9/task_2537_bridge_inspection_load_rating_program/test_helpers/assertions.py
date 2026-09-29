"""
Domain assertion helpers for the Bridge Inspection & Load Rating Program API.

Each helper encodes one rule the PRD states, so that a test reads as the
business claim it makes rather than as a pile of dictionary lookups. The
framework's own generic assertions (envelope shape, error identity, pagination
meta, UUID and timestamp format) are imported from
`prd_bench_local_runner.testing` and are not re-implemented here.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    CS_WEIGHT_CS1,
    CS_WEIGHT_CS2,
    CS_WEIGHT_CS3,
    CS_WEIGHT_CS4,
    ELEMENT_GROUP_OF,
    NBI_RATING_LADDER,
    RATING_VEHICLE_TONS,
)


# ─── Timestamp and date tolerance ──────────────────────────────────────────
# PRD §2.5 declares stored instants as "an ISO 8601 timestamp in UTC with three
# fractional digits (for example `2026-08-01T00:00:00.000Z`)", while a client
# sets the clock and supplies observation instants without fractional digits.
# Comparisons on instants therefore go through the second-precision prefix, and
# comparisons on calendar dates through the day-precision prefix, so that a
# conforming server is never failed for a formatting difference the PRD allows.

def date_part(value: str) -> str:
    """The `YYYY-MM-DD` calendar-date prefix of an ISO 8601 string."""
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    assert len(value) >= 10, f"value {value!r} is too short to carry a date"
    return value[:10]


def second_part(value: str) -> str:
    """The `YYYY-MM-DDTHH:MM:SS` second-precision prefix of an ISO 8601 string."""
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    assert len(value) >= 19, f"value {value!r} is too short to carry an instant"
    return value[:19]


def assert_date_equals(actual: Any, expected: str, label: str = "date") -> None:
    """Assert that `actual` names the same UTC calendar day as `expected`."""
    assert actual is not None, f"{label} is null, expected {expected}"
    assert date_part(actual) == date_part(expected), (
        f"{label}: expected calendar date {date_part(expected)}, got {actual!r}"
    )


def assert_instant_equals(actual: Any, expected: str, label: str = "instant") -> None:
    """Assert that `actual` names the same UTC second as `expected`."""
    assert actual is not None, f"{label} is null, expected {expected}"
    assert second_part(actual) == second_part(expected), (
        f"{label}: expected instant {second_part(expected)}, got {actual!r}"
    )


# ─── PRD §2.5: the common system-managed field set ─────────────────────────
def assert_common_fields(resource: Dict[str, Any], label: str = "resource") -> None:
    """
    Assert the four system-managed fields PRD §2.5 requires of thirteen of the
    fourteen resource types: a UUID `id` with no type prefix, ISO 8601 UTC
    `created_at` and `updated_at`, and an integer `version`.
    """
    assert is_valid_uuid(resource.get("id")), (
        f"{label}.id must be a UUID with no type prefix, got {resource.get('id')!r}"
    )
    assert is_iso8601_timestamp(resource.get("created_at")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp, "
        f"got {resource.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(resource.get("updated_at")), (
        f"{label}.updated_at must be an ISO 8601 UTC timestamp, "
        f"got {resource.get('updated_at')!r}"
    )
    assert isinstance(resource.get("version"), int) and not isinstance(
        resource.get("version"), bool
    ), f"{label}.version must be an integer, got {resource.get('version')!r}"
    assert resource["version"] >= 1, (
        f"{label}.version must be at least 1, got {resource['version']}"
    )


def assert_notification_log_shape(log: Dict[str, Any]) -> None:
    """
    Assert the notification log's exceptional shape.

    PRD §2.5: "A notification log entry is an immutable audit record: it carries
    `id` and `created_at` only. It has no `updated_at` field and no `version`
    field at all, and once written it is never modified."
    """
    assert is_valid_uuid(log.get("id")), (
        f"notification log id must be a UUID, got {log.get('id')!r}"
    )
    assert is_iso8601_timestamp(log.get("created_at")), (
        f"notification log created_at must be an ISO 8601 UTC timestamp, "
        f"got {log.get('created_at')!r}"
    )
    assert "updated_at" not in log, (
        "a notification log entry has no updated_at field, "
        f"but the body carried {log.get('updated_at')!r}"
    )
    assert "version" not in log, (
        "a notification log entry has no version field at all, "
        f"but the body carried {log.get('version')!r}"
    )


def assert_version_advanced_by(
    new_version: int, old_version: int, delta: int, label: str = "resource"
) -> None:
    """
    Assert an exact `version` delta.

    PRD §2.5 makes `version` "a system-managed counter that increments by one on
    every mutation of the resource, including mutations that only touch derived
    fields", so a claim about how many writes an operation performed is a claim
    about this delta.
    """
    assert new_version == old_version + delta, (
        f"{label}.version: expected {old_version} + {delta} = {old_version + delta}, "
        f"got {new_version}"
    )


def assert_version_unchanged(
    new_version: int, old_version: int, label: str = "resource"
) -> None:
    """Assert that an operation wrote nothing to this resource (PRD §2.5)."""
    assert new_version == old_version, (
        f"{label}.version moved from {old_version} to {new_version}, "
        "but the operation must not write to this resource"
    )


# ─── PRD §2.6: precision ───────────────────────────────────────────────────
def _decimal_places(value: float) -> int:
    """How many decimal places a numeric value actually carries."""
    text = format(Decimal(str(value)).normalize(), "f")
    return len(text.split(".")[1]) if "." in text else 0


def assert_at_most_decimals(value: Any, places: int, label: str = "value") -> None:
    """Assert a derived quantity carries no more than `places` decimals (PRD §2.6)."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be numeric, got {value!r}"
    )
    actual = _decimal_places(float(value))
    assert actual <= places, (
        f"{label} must be carried to {places} decimal places, "
        f"got {value!r} with {actual}"
    )


def assert_two_decimals(value: Any, label: str = "value") -> None:
    """Health indices, deficiency percentages, priority scores and compliance
    percentages "are all carried to 2 decimal places" (PRD §2.6)."""
    assert_at_most_decimals(value, 2, label)


def assert_three_decimals(value: Any, label: str = "rating factor") -> None:
    """Rating factors "are carried to 3 decimal places" (PRD §2.6)."""
    assert_at_most_decimals(value, 3, label)


def assert_one_decimal(value: Any, label: str = "tonnage") -> None:
    """Tonnage figures "are carried to 1 decimal place" (PRD §2.6)."""
    assert_at_most_decimals(value, 1, label)


def assert_whole_cents(value: Any, label: str = "money") -> None:
    """
    PRD §2.6: "All money in the system is carried as a whole number of
    **cents**; there are no fractional cents and no floating-point currency."
    """
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be a whole number of cents, got {value!r}"
    )


def assert_half_ton_step(value: Any, label: str = "posted_limit_tons") -> None:
    """
    PRD §2.6: "Posted weight limits are quantised to a half-ton step by rounding
    **down**, never half-up."
    """
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be numeric, got {value!r}"
    )
    doubled = Decimal(str(value)) * 2
    assert doubled == doubled.to_integral_value(), (
        f"{label} must sit on a half-ton step, got {value!r}"
    )


# ─── PRD §3.2: element arithmetic ──────────────────────────────────────────
def expected_element_health_index(
    total_quantity: float, cs1: float, cs2: float, cs3: float, cs4: float
) -> Decimal:
    """
    Recompute an element health index exactly as PRD §3.2 specifies: weight the
    good, fair, poor and severe quantities by 1.00, 0.80, 0.40 and 0.00, sum the
    products, divide by `total_quantity`, multiply by 100 and round half up to
    two decimals.
    """
    weighted = (
        Decimal(str(cs1)) * Decimal(str(CS_WEIGHT_CS1))
        + Decimal(str(cs2)) * Decimal(str(CS_WEIGHT_CS2))
        + Decimal(str(cs3)) * Decimal(str(CS_WEIGHT_CS3))
        + Decimal(str(cs4)) * Decimal(str(CS_WEIGHT_CS4))
    )
    raw = weighted / Decimal(str(total_quantity)) * Decimal(100)
    return _round_half_up(raw, 2)


def _round_half_up(value: Decimal, places: int) -> Decimal:
    """Round half up, the single rounding mode PRD §2.6 declares."""
    quantum = Decimal(1).scaleb(-places)
    return value.quantize(quantum, rounding="ROUND_HALF_UP")


def assert_element_derived_fields(
    row: Dict[str, Any],
    total_quantity: float,
    cs1: float,
    cs2: float,
    cs3: float,
    cs4: float,
) -> None:
    """
    Assert the four values PRD §3.2 says writing an element row derives:
    `reported_sum`, `balanced`, `deficient_quantity` and `element_health_index`.
    """
    expected_sum = cs1 + cs2 + cs3 + cs4
    assert float(row["reported_sum"]) == float(expected_sum), (
        f"reported_sum must total the four condition-state quantities "
        f"({expected_sum}), got {row['reported_sum']}"
    )
    assert row["balanced"] is (float(expected_sum) == float(total_quantity)), (
        "balanced must be true exactly when reported_sum equals total_quantity"
    )
    assert float(row["deficient_quantity"]) == float(cs3 + cs4), (
        f"deficient_quantity must be cs3_qty plus cs4_qty ({cs3 + cs4}), "
        f"got {row['deficient_quantity']}"
    )
    expected_ehi = expected_element_health_index(total_quantity, cs1, cs2, cs3, cs4)
    assert Decimal(str(row["element_health_index"])) == expected_ehi, (
        f"element_health_index must be {expected_ehi}, "
        f"got {row['element_health_index']}"
    )


def assert_element_group_for_key(row: Dict[str, Any]) -> None:
    """
    PRD §3.2 fixes the grouping: "`DECK`, `JOINT` and `RAILING` belong to
    `DECK_GROUP`; `GIRDER` and `BEARING` belong to `SUPERSTRUCTURE`; `PIER_CAP`,
    `COLUMN` and `ABUTMENT` belong to `SUBSTRUCTURE`."
    """
    expected = ELEMENT_GROUP_OF[row["element_key"]]
    assert row["element_group"] == expected, (
        f"element_key {row['element_key']} belongs to {expected}, "
        f"but the row carried {row['element_group']}"
    )


# ─── PRD §3.3: the NBI component-rating ladder ─────────────────────────────
def expected_nbi_rating(group_index: float) -> int:
    """
    Map a group index to a component rating through the descending ladder of
    PRD §3.3, where "the first satisfied rung wins and every comparison is 'at
    least'".
    """
    for threshold, rating in NBI_RATING_LADDER:
        if group_index >= threshold:
            return rating
    return 0


def assert_nbi_rating_from_index(rating: Any, group_index: float) -> None:
    """Assert a computed component rating agrees with the ladder of PRD §3.3."""
    expected = expected_nbi_rating(group_index)
    assert rating == expected, (
        f"a group index of {group_index} rates {expected} on the ladder, got {rating}"
    )


# ─── PRD §3.4: the rating equation ─────────────────────────────────────────
def expected_rating_factor(
    condition_factor: float,
    system_factor: float,
    resistance_factor: float,
    capacity: float,
    dead_load_dc: float,
    dead_load_dw: float,
    live_load_factor: float,
    live_load: float,
    impact_factor: float,
) -> Decimal:
    """
    Recompute a rating factor exactly as PRD §3.4 specifies, rounded half up to
    three decimals.
    """
    numerator = (
        Decimal(str(condition_factor))
        * Decimal(str(system_factor))
        * Decimal(str(resistance_factor))
        * Decimal(str(capacity))
        - Decimal("1.25") * Decimal(str(dead_load_dc))
        - Decimal("1.50") * Decimal(str(dead_load_dw))
    )
    denominator = (
        Decimal(str(live_load_factor))
        * Decimal(str(live_load))
        * Decimal(str(impact_factor))
    )
    return _round_half_up(numerator / denominator, 3)


def expected_tons(rating_factor: float) -> Decimal:
    """
    PRD §3.4: the already-rounded three-decimal factor is multiplied by "the
    rating vehicle's gross weight of 36.0 tons" and rounded half up to one
    decimal place.
    """
    return _round_half_up(
        Decimal(str(rating_factor)) * Decimal(str(RATING_VEHICLE_TONS)), 1
    )


def expected_posted_limit(inventory_rating_tons: float) -> Decimal:
    """
    PRD §3.4: "`posted_limit_tons` is `inventory_rating_tons` quantised
    *downward* to the nearest half ton: double the inventory tonnage, discard
    the fractional part, and halve the result."
    """
    doubled = Decimal(str(inventory_rating_tons)) * 2
    floored = doubled.to_integral_value(rounding="ROUND_FLOOR")
    return floored / 2


def assert_rating_tonnage_pair(rating: Dict[str, Any]) -> None:
    """
    Assert the tons on a rating follow from its own already-rounded factors,
    which is the second pinned rounding order of PRD §2.6.
    """
    assert Decimal(str(rating["operating_rating_tons"])) == expected_tons(
        rating["rating_factor_operating"]
    ), (
        "operating_rating_tons must be the rounded operating factor times 36.0, "
        f"got {rating['operating_rating_tons']} from "
        f"{rating['rating_factor_operating']}"
    )
    assert Decimal(str(rating["inventory_rating_tons"])) == expected_tons(
        rating["rating_factor_inventory"]
    ), (
        "inventory_rating_tons must be the rounded inventory factor times 36.0, "
        f"got {rating['inventory_rating_tons']} from "
        f"{rating['rating_factor_inventory']}"
    )


def assert_operating_exceeds_inventory(rating: Dict[str, Any]) -> None:
    """
    PRD §3.4: the operating variant "always yields the higher of the two rating
    factors" and the inventory variant "always yields the lower of the two".
    """
    assert rating["rating_factor_operating"] > rating["rating_factor_inventory"], (
        "the operating factor must exceed the inventory factor, got "
        f"{rating['rating_factor_operating']} and {rating['rating_factor_inventory']}"
    )


# ─── PRD §3.8: the budget waterfall ────────────────────────────────────────
def assert_budget_identity(cycle: Dict[str, Any]) -> None:
    """
    PRD §3.8: "After every mutation the identity `authorized_budget_cents` equals
    `reserve_cents` plus `committed_cents` plus `remaining_cents` must hold."
    """
    for field in (
        "authorized_budget_cents",
        "reserve_cents",
        "committed_cents",
        "remaining_cents",
    ):
        assert_whole_cents(cycle[field], f"cycle.{field}")
    total = cycle["reserve_cents"] + cycle["committed_cents"] + cycle["remaining_cents"]
    assert cycle["authorized_budget_cents"] == total, (
        "the budget identity must hold: "
        f"{cycle['authorized_budget_cents']} != {cycle['reserve_cents']} + "
        f"{cycle['committed_cents']} + {cycle['remaining_cents']}"
    )


def assert_allocation_summary_matches_cycle(
    summary: Dict[str, Any], cycle: Dict[str, Any]
) -> None:
    """The computed read of PRD §3.8 must agree with the cycle it summarises."""
    assert summary["program_cycle_id"] == cycle["id"]
    for field in (
        "authorized_budget_cents",
        "reserve_cents",
        "available_cents",
        "committed_cents",
        "remaining_cents",
        "identified_count",
        "programmed_count",
        "deferred_count",
        "unprogrammed_cost_cents",
    ):
        assert summary[field] == cycle[field], (
            f"allocation summary {field} reads {summary[field]} "
            f"but the cycle carries {cycle[field]}"
        )


# ─── Listing helpers ───────────────────────────────────────────────────────
def find_by_id(rows: List[Dict[str, Any]], row_id: str) -> Optional[Dict[str, Any]]:
    """Locate one row of a listing by its `id`."""
    for row in rows:
        if row.get("id") == row_id:
            return row
    return None


def assert_ascending_created_at(rows: List[Dict[str, Any]]) -> None:
    """
    PRD §2.3: "every list endpoint returns records sorted by their creation
    timestamp in ascending order — oldest first."
    """
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), (
        f"listing must be ordered oldest first, got {stamps}"
    )
