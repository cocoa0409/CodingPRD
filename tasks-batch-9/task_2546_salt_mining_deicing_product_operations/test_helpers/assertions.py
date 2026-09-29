"""
Domain assertions for the Salt Deicing Operations API.

These wrap the generic format helpers with the PRD's own precision and
common-property rules: 2 decimal places for tonnage and money, 4 for
`planned_tons_per_hour`, 3 for `purity_pct_nacl` and `outbound_freight_rate_per_ton`,
and the split between the eleven versioned families and the immutable inspection.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import AUTO_SURGE_THRESHOLD_PCT

# Tolerance for comparing a stored decimal at N places against an expected value.
# A value rounded to 2 places can differ from the expected figure only by float
# representation noise, never by half a cent.
_TOLERANCE = {2: 0.0005, 3: 0.00005, 4: 0.000005}


def assert_amount(actual: Any, expected: float, places: int = 2, field: str = "value") -> None:
    """Assert a decimal field equals `expected` when read at `places` decimals."""
    assert actual is not None, f"{field} is null, expected {expected}"
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{field} must be numeric, got {actual!r}"
    )
    assert abs(float(actual) - expected) < _TOLERANCE[places], (
        f"{field}: expected {expected:.{places}f}, got {actual}"
    )
    scaled = float(actual) * (10 ** places)
    assert abs(scaled - round(scaled)) < 1e-6, (
        f"{field} carries more than {places} decimal places: {actual}"
    )


def assert_tons(actual: Any, expected: float, field: str = "tons") -> None:
    """Tonnage is stored at 2 decimal places, round half up (PRD §2.7)."""
    assert_amount(actual, expected, 2, field)


def assert_money(actual: Any, expected: float, field: str = "usd") -> None:
    """Every stored dollar figure is rounded to 2 decimal places (PRD §2.7)."""
    assert_amount(actual, expected, 2, field)


def assert_rate_per_hour(actual: Any, expected: float, field: str = "planned_tons_per_hour") -> None:
    """`planned_tons_per_hour` is carried at 4 decimal places (PRD §2.7)."""
    assert_amount(actual, expected, 4, field)


def assert_purity(actual: Any, expected: float, field: str = "purity_pct_nacl") -> None:
    """`purity_pct_nacl` is carried at 3 decimal places (PRD §2.7)."""
    assert_amount(actual, expected, 3, field)


def assert_three_decimals(actual: Any, expected: float, field: str) -> None:
    """For the two 3-decimal input fields of PRD §2.7."""
    assert_amount(actual, expected, 3, field)


# ─── Common resource properties (PRD §2.4) ────────────


def assert_iso_millis(timestamp: Any, field: str = "timestamp") -> None:
    """ISO 8601 UTC instant "with exactly three fractional digits"."""
    assert isinstance(timestamp, str), f"{field} must be a string, got {timestamp!r}"
    assert is_iso8601_timestamp(timestamp), f"{field} is not an ISO 8601 UTC instant: {timestamp}"
    assert timestamp.endswith("Z"), f"{field} must end in Z: {timestamp}"
    assert "." in timestamp, f"{field} must carry fractional digits: {timestamp}"
    fraction = timestamp.split(".")[1].rstrip("Z")
    assert len(fraction) == 3, (
        f"{field} must carry exactly three fractional digits: {timestamp}"
    )


def assert_common_fields(resource: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """
    The four common properties of the eleven versioned families: a UUID `id`, a
    millisecond `created_at`, a millisecond `updated_at`, and an integer `version`
    that "starts at 1 when the resource is created and increases by exactly 1 on
    every mutation".
    """
    assert is_valid_uuid(resource.get("id")), (
        f"id must be a UUID with no type prefix, got {resource.get('id')!r}"
    )
    assert_iso_millis(resource.get("created_at"), "created_at")
    assert_iso_millis(resource.get("updated_at"), "updated_at")
    version = resource.get("version")
    assert isinstance(version, int) and not isinstance(version, bool), (
        f"version must be an integer, got {version!r}"
    )
    assert version >= 1, f"version starts at 1, got {version}"
    if expected_version is not None:
        assert version == expected_version, (
            f"expected version {expected_version}, got {version}"
        )


def assert_immutable_inspection_fields(inspection: Dict[str, Any]) -> None:
    """
    `GroundControlInspection` "carries only id and created_at. It has no updated_at
    field, no version field, and no update endpoint of any kind."
    """
    assert is_valid_uuid(inspection.get("id")), (
        f"id must be a UUID, got {inspection.get('id')!r}"
    )
    assert_iso_millis(inspection.get("created_at"), "created_at")
    assert "updated_at" not in inspection, (
        "an inspection record must not carry updated_at"
    )
    assert "version" not in inspection, "an inspection record must not carry version"


def assert_version_bumped(after: Dict[str, Any], before: Dict[str, Any], by: int = 1) -> None:
    """A mutation "increases by exactly 1" — assert the exact delta, not a floor."""
    assert after["version"] == before["version"] + by, (
        f"expected version {before['version']} + {by}, got {after['version']}"
    )
    assert after["id"] == before["id"], "compared two different resources"


def assert_version_unchanged(after: Dict[str, Any], before: Dict[str, Any]) -> None:
    """A refused request applies "no side effect of any later stage" (PRD §2.6)."""
    assert after["version"] == before["version"], (
        f"version moved from {before['version']} to {after['version']} on a refused request"
    )


def assert_timestamps_unchanged(after: Dict[str, Any], before: Dict[str, Any]) -> None:
    assert after["updated_at"] == before["updated_at"], (
        f"updated_at moved from {before['updated_at']} to {after['updated_at']}"
    )


# ─── Conserved-quantity invariants (PRD §3.6, §3.9) ───


def assert_lot_invariant(lot: Dict[str, Any]) -> None:
    """
    "`tons_available` equals `tons_on_hand` minus the sum of `tons` across the lot's
    allocations whose `state` is `RESERVED`", and `tons_reserved` is precisely that
    sum — so the three figures must agree exactly, "with zero drift at two decimal
    places".
    """
    assert_tons(
        lot["tons_available"],
        round(float(lot["tons_on_hand"]) - float(lot["tons_reserved"]), 2),
        "tons_available",
    )


def assert_lot_tonnage(
    lot: Dict[str, Any],
    on_hand: float,
    reserved: float,
    available: float,
) -> None:
    assert_tons(lot["tons_on_hand"], on_hand, "tons_on_hand")
    assert_tons(lot["tons_reserved"], reserved, "tons_reserved")
    assert_tons(lot["tons_available"], available, "tons_available")
    assert_lot_invariant(lot)


def assert_penalty_ledger_invariant(
    contract: Dict[str, Any], accrued_orders: list
) -> None:
    """
    "a contract's `penalty_accrued_usd` equals the sum of `shortfall_penalty_usd`
    over its orders whose `penalty_state` is `ACCRUED`".
    """
    expected = round(
        sum(float(order["shortfall_penalty_usd"]) for order in accrued_orders), 2
    )
    assert_money(contract["penalty_accrued_usd"], expected, "penalty_accrued_usd")


# ─── Computed views (PRD §2.10) ───────────────────────


def assert_posture_view_threshold(view: Dict[str, Any]) -> None:
    """`auto_surge_threshold_pct` "which is always 90"."""
    assert_amount(
        view["auto_surge_threshold_pct"],
        float(AUTO_SURGE_THRESHOLD_PCT),
        2,
        "auto_surge_threshold_pct",
    )


def assert_hoist_capacity_view(
    view: Dict[str, Any],
    rated: float,
    hoist_factor: float,
    compliance_factor: float,
    effective: float,
    scheduled_open: float,
    scheduled_run_count: int,
) -> None:
    assert_tons(view["rated_hoist_tons_per_day"], rated, "rated_hoist_tons_per_day")
    assert_amount(view["hoist_factor"], hoist_factor, 2, "hoist_factor")
    assert_amount(view["compliance_factor"], compliance_factor, 2, "compliance_factor")
    assert_tons(
        view["effective_hoist_tons_per_day"], effective, "effective_hoist_tons_per_day"
    )
    assert_tons(
        view["scheduled_hoist_tons_open"], scheduled_open, "scheduled_hoist_tons_open"
    )
    assert view["scheduled_run_count"] == scheduled_run_count, (
        f"expected scheduled_run_count {scheduled_run_count}, "
        f"got {view['scheduled_run_count']}"
    )
    # "The mine's hourly capacity ... is that effective daily figure divided by the
    # 24 hours in a day", and it is compared unrounded.
    assert abs(float(view["mine_hourly_capacity"]) - effective / 24) < 1e-6, (
        f"mine_hourly_capacity {view['mine_hourly_capacity']} is not "
        f"{effective}/24"
    )


# ─── Pagination (PRD §2.3) ────────────────────────────


def assert_page_meta(
    meta: Dict[str, Any],
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> None:
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"expected total_count {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"expected has_more {has_more}, got {meta['has_more']}"
        )
    if limit is not None:
        assert meta["limit"] == limit, f"expected limit {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"expected offset {offset}, got {meta['offset']}"


def assert_ids_in_order(rows: list, expected_ids: list) -> None:
    """List ordering assertions read the ids in the exact order the PRD pins."""
    actual = [row["id"] for row in rows]
    assert actual == expected_ids, f"expected row order {expected_ids}, got {actual}"


def only(rows: list) -> Dict[str, Any]:
    """Assert a filtered list holds exactly one row and return it."""
    assert len(rows) == 1, f"expected exactly one row, got {len(rows)}"
    return rows[0]
