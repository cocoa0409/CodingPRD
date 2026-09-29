"""Domain assertions.

These wrap the framework validators with the invariants the PRD states in
prose, so a test can say "the capacity triple still adds up" in one line.
"""

from decimal import Decimal
from typing import Any, Iterable, List, Optional, Sequence

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    assert_at_least_one_succeeds,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    run_race,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from .constants import (
    POSTURE_FROZEN_RATIO,
    POSTURE_RESTRICTED_RATIO,
    round_half_up,
)
from .types import COMMON_FIELDS, JsonDict, MenuPosture, SlotStatus


# --------------------------------------------------------------------------
# Envelope and common fields
# --------------------------------------------------------------------------


def assert_common_fields(entity: JsonDict) -> None:
    """Every entity carries an id, both timestamps and a version."""
    for field in COMMON_FIELDS:
        assert field in entity, f"missing common field {field!r} in {sorted(entity)}"
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert is_iso8601_timestamp(entity["updated_at"]), entity["updated_at"]
    assert isinstance(entity["version"], int), entity["version"]
    assert entity["version"] >= 1, entity["version"]


def assert_version_bumped(before: JsonDict, after: JsonDict, by: int = 1) -> None:
    """A mutation advances ``version``."""
    assert after["id"] == before["id"], "compared two different entities"
    assert after["version"] == before["version"] + by, (
        f"version went {before['version']} -> {after['version']}, expected "
        f"+{by}"
    )


def assert_version_unchanged(before: JsonDict, after: JsonDict) -> None:
    assert after["version"] == before["version"], (
        f"version moved {before['version']} -> {after['version']} but the call "
        "should have been rejected"
    )


def assert_fields(entity: JsonDict, **expected: Any) -> None:
    """Compare a batch of fields, reporting all mismatches at once."""
    problems = []
    for key, want in expected.items():
        assert key in entity, f"missing field {key!r} in {sorted(entity)}"
        got = entity[key]
        if isinstance(want, Decimal):
            if Decimal(str(got)) != want:
                problems.append(f"{key}: expected {want}, got {got!r}")
        elif got != want:
            problems.append(f"{key}: expected {want!r}, got {got!r}")
    assert not problems, "; ".join(problems)


def assert_status(entity: JsonDict, expected: str, field: str = "status") -> None:
    assert entity[field] == expected, (
        f"{field} is {entity[field]!r}, expected {expected!r}"
    )


# --------------------------------------------------------------------------
# Decimal discipline (PRD §2.5)
# --------------------------------------------------------------------------


def assert_decimal_places(value: Any, places: int, label: str = "value") -> Decimal:
    """The API serialises fixed-scale numbers; check the scale and return the
    Decimal so the caller can go on comparing."""
    as_decimal = Decimal(str(value))
    exponent = -as_decimal.as_tuple().exponent
    assert exponent <= places, (
        f"{label} has {exponent} decimal places, expected at most {places}: {value!r}"
    )
    return as_decimal


def assert_score(value: Any, expected: str, label: str = "score") -> None:
    """A two-decimal score equals ``expected`` exactly."""
    got = assert_decimal_places(value, 2, label)
    assert got == Decimal(expected), f"{label} is {value!r}, expected {expected}"


def assert_ratio(value: Any, expected: str, label: str = "ratio") -> None:
    """A four-decimal ratio equals ``expected`` exactly."""
    got = assert_decimal_places(value, 4, label)
    assert got == Decimal(expected), f"{label} is {value!r}, expected {expected}"


def assert_cents(value: Any, expected: int, label: str = "cents") -> None:
    assert isinstance(value, int), f"{label} must be an integer number of cents: {value!r}"
    assert value == expected, f"{label} is {value}, expected {expected}"


def assert_bps(value: Any, expected: int, label: str = "bps") -> None:
    assert isinstance(value, int), f"{label} must be an integer basis-point count: {value!r}"
    assert value == expected, f"{label} is {value}, expected {expected}"


# --------------------------------------------------------------------------
# Conserved quantities (PRD §2.10)
# --------------------------------------------------------------------------


def assert_capacity_triple(
    plan: JsonDict,
    occupied: Optional[int] = None,
    reserved: Optional[int] = None,
    available: Optional[int] = None,
) -> None:
    """``occupied + reserved + available`` always equals ``menu_slot_capacity``;
    any of the three may additionally be pinned to an exact value."""
    got = (
        plan["occupied_menu_slots"],
        plan["reserved_menu_slots"],
        plan["available_menu_slots"],
    )
    total = sum(got)
    assert total == plan["menu_slot_capacity"], (
        f"occupied+reserved+available = {got[0]}+{got[1]}+{got[2]} = {total} but "
        f"menu_slot_capacity is {plan['menu_slot_capacity']}"
    )
    assert got[2] >= 0, f"available_menu_slots went negative: {got[2]}"
    expected = (occupied, reserved, available)
    for name, want, have in zip(
        ("occupied_menu_slots", "reserved_menu_slots", "available_menu_slots"),
        expected,
        got,
    ):
        if want is not None:
            assert have == want, f"{name} is {have}, expected {want}"


def assert_plan_assets_conserved(plan: JsonDict, expected_total_cents: int) -> None:
    assert_cents(
        plan["total_plan_assets_cents"], expected_total_cents, "total_plan_assets_cents"
    )


def assert_credit_balance_identity(plan: JsonDict) -> None:
    """``revenue_credit_balance_cents == accrued - allocated``."""
    accrued = plan["revenue_credit_accrued_cents"]
    allocated = plan["revenue_credit_allocated_cents"]
    balance = plan["revenue_credit_balance_cents"]
    assert balance == accrued - allocated, (
        f"balance {balance} != accrued {accrued} - allocated {allocated}"
    )
    assert balance >= 0, f"the credit pool went negative: {balance}"


def assert_posture_matches_ratio(plan: JsonDict) -> None:
    """The posture is never gentler than the at-risk ratio allows."""
    ratio = Decimal(str(plan["at_risk_slot_ratio"]))
    posture = plan["menu_posture"]
    if ratio >= Decimal(str(POSTURE_FROZEN_RATIO)):
        assert posture == MenuPosture.FROZEN, (
            f"ratio {ratio} should force FROZEN, got {posture}"
        )
    elif ratio >= Decimal(str(POSTURE_RESTRICTED_RATIO)):
        assert posture in (MenuPosture.RESTRICTED, MenuPosture.FROZEN), (
            f"ratio {ratio} should force at least RESTRICTED, got {posture}"
        )


def assert_at_risk_bookkeeping(plan: JsonDict, slots: Sequence[JsonDict]) -> None:
    """The plan's ratio agrees with the slot rows it summarises: the denominator
    counts ACTIVE, AT_RISK and PENDING_REPLACEMENT slots and the numerator counts
    the AT_RISK and PENDING_REPLACEMENT ones."""
    counted = [s for s in slots if s["status"] in SlotStatus.OCCUPYING]
    at_risk = [
        s
        for s in counted
        if s["status"] in (SlotStatus.AT_RISK, SlotStatus.PENDING_REPLACEMENT)
    ]
    if counted:
        expected = round_half_up(Decimal(len(at_risk)) / Decimal(len(counted)), 4)
    else:
        expected = Decimal("0.0000")
    assert Decimal(str(plan["at_risk_slot_ratio"])) == expected, (
        f"at_risk_slot_ratio is {plan['at_risk_slot_ratio']}, expected {expected}"
    )


# --------------------------------------------------------------------------
# Snapshot / compensation fields (PRD §2.10)
# --------------------------------------------------------------------------


def assert_snapshot_restored(
    entity: JsonDict, live_field: str, snapshot_field: str, expected: str
) -> None:
    """After a compensating action the live field is back to the value the
    snapshot field recorded."""
    assert entity[live_field] == expected, (
        f"{live_field} is {entity[live_field]!r}, expected the pre-action value "
        f"{expected!r}"
    )


# --------------------------------------------------------------------------
# Listing helpers
# --------------------------------------------------------------------------


def ids_of(rows: Iterable[JsonDict]) -> List[str]:
    return [row["id"] for row in rows]


def assert_contains_ids(rows: Iterable[JsonDict], *expected_ids: str) -> None:
    present = set(ids_of(rows))
    missing = [i for i in expected_ids if i not in present]
    assert not missing, f"rows are missing {missing}; present: {sorted(present)}"


def assert_excludes_ids(rows: Iterable[JsonDict], *excluded_ids: str) -> None:
    present = set(ids_of(rows))
    leaked = [i for i in excluded_ids if i in present]
    assert not leaked, f"rows should not contain {leaked}"


def assert_ordered_by(rows: Sequence[JsonDict], field: str, descending: bool = False) -> None:
    values = [row[field] for row in rows]
    expected = sorted(values, reverse=descending)
    assert values == expected, f"rows are not ordered by {field}: {values}"


def find_by(rows: Iterable[JsonDict], **match: Any) -> JsonDict:
    for row in rows:
        if all(row.get(k) == v for k, v in match.items()):
            return row
    raise AssertionError(f"no row matching {match}")


__all__ = [
    "assert_common_fields",
    "assert_version_bumped",
    "assert_version_unchanged",
    "assert_fields",
    "assert_status",
    "assert_decimal_places",
    "assert_score",
    "assert_ratio",
    "assert_cents",
    "assert_bps",
    "assert_capacity_triple",
    "assert_plan_assets_conserved",
    "assert_credit_balance_identity",
    "assert_posture_matches_ratio",
    "assert_at_risk_bookkeeping",
    "assert_snapshot_restored",
    "ids_of",
    "assert_contains_ids",
    "assert_excludes_ids",
    "assert_ordered_by",
    "find_by",
    # re-exported framework helpers
    "validate_success",
    "validate_error",
    "validate_error_is_one_of",
    "validate_paginated",
    "get_success_data",
    "is_valid_uuid",
    "is_iso8601_timestamp",
    "NON_EXISTENT_UUID",
    "run_race",
    "assert_race_outcome",
    "assert_exactly_one_succeeds",
    "assert_at_least_one_succeeds",
]
