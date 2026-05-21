"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the shape of a single API response data
dict against PRD §2.4 (common-fields exceptions for AirportQueue and
HeatMapSnapshot which are append-only) and the §3 entity narratives.
"""
from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    AIRPORT_SURCHARGE,
    BASE_FARE_CENTS,
    MULTIPLIER_CAP,
    PER_KM_CENTS,
    PLATFORM_FEE_RATE,
    SURGE_ABOVE_TOP,
    SURGE_TIER_THRESHOLDS,
)


# ---------------------------------------------------------------------------
# Common-field assertion helpers — PRD §2.4.
# ---------------------------------------------------------------------------
def _assert_common_fields_mutable(data: Dict[str, Any]) -> None:
    """For entities with the standard system-managed property set — PRD
    §2.4 says they carry id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO-8601 UTC with 3 fractional digits, "
        f"got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO-8601 UTC with 3 fractional digits, "
        f"got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def _assert_common_fields_append_only(data: Dict[str, Any]) -> None:
    """For entities PRD §2.4 declares append-only: AirportQueue and
    HeatMapSnapshot carry only id and created_at, with no updated_at and
    no version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO-8601 UTC with 3 fractional digits, "
        f"got {data.get('created_at')!r}"
    )


# ---------------------------------------------------------------------------
# Half-up rounding helper — PRD §2.6.
# ---------------------------------------------------------------------------
def round_half_up_int(value: float) -> int:
    """Round to the nearest integer with half-up semantics, matching
    PRD §2.6 ("rounded half-up to a whole integer cent"). Python's
    builtin round() is banker's rounding, so we use Decimal."""
    return int(
        Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


def round_half_up_2(value: float) -> float:
    """Round to two decimal places half-up — PRD §2.5 ("stored to
    exactly two decimal places") and §2.6 ("All multiplier arithmetic
    carries two decimal places of precision and likewise uses round
    half-up.")"""
    return float(
        Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )


# ---------------------------------------------------------------------------
# Per-entity shape assertions.
# ---------------------------------------------------------------------------
def assert_grid(data: Dict[str, Any]) -> None:
    _assert_common_fields_mutable(data)
    assert isinstance(data.get("code"), str) and len(data["code"]) > 0
    assert isinstance(data.get("name"), str)
    assert isinstance(data.get("is_airport"), bool)
    assert isinstance(data.get("rush_hour_eligible"), bool)
    assert isinstance(data.get("active_driver_count"), int)
    assert data["active_driver_count"] >= 0, (
        "active_driver_count must be non-negative."
    )
    assert isinstance(data.get("open_demand_count"), int)
    assert data["open_demand_count"] >= 0, (
        "open_demand_count must be non-negative."
    )
    # PRD §3.1: current_multiplier "constrained to lie between 1.00 and
    # the MULTIPLIER_CAP of 3.00 inclusive".
    mult = data.get("current_multiplier")
    assert isinstance(mult, (int, float))
    assert 1.00 <= float(mult) <= MULTIPLIER_CAP, (
        f"current_multiplier {mult} must lie in [1.00, {MULTIPLIER_CAP}]."
    )
    # PRD §2.5: stored to exactly two decimal places.
    rounded = round_half_up_2(float(mult))
    assert math.isclose(float(mult), rounded, abs_tol=1e-9), (
        f"current_multiplier {mult} must carry two-decimal precision "
        f"(expected {rounded})."
    )


def assert_driver(data: Dict[str, Any]) -> None:
    _assert_common_fields_mutable(data)
    assert isinstance(data.get("name"), str)
    assert data.get("status") in (
        "OFFLINE", "AVAILABLE", "EN_ROUTE_PICKUP", "ON_TRIP",
        "IN_AIRPORT_QUEUE",
    )
    cgc = data.get("current_grid_code")
    assert cgc is None or isinstance(cgc, str)
    q = data.get("quest_id")
    assert q is None or isinstance(q, str)
    assert isinstance(data.get("quest_completed_rides"), int)
    assert data["quest_completed_rides"] >= 0
    assert isinstance(data.get("total_earnings_cents"), int)
    assert data["total_earnings_cents"] >= 0, (
        "PRD §3.7: total_earnings_cents never falls below zero."
    )


def assert_rider(data: Dict[str, Any]) -> None:
    _assert_common_fields_mutable(data)
    assert isinstance(data.get("name"), str)
    assert isinstance(data.get("wallet_balance_cents"), int)
    assert data["wallet_balance_cents"] >= 0


def assert_rush_hour_window(data: Dict[str, Any]) -> None:
    _assert_common_fields_mutable(data)
    assert isinstance(data.get("label"), str)
    assert data.get("day_of_week") in (
        "MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN",
    )
    sm = data.get("start_minute")
    em = data.get("end_minute")
    assert isinstance(sm, int) and 0 <= sm < 1440
    assert isinstance(em, int) and sm < em <= 1440
    bonus = data.get("additive_bonus")
    assert isinstance(bonus, (int, float))
    assert 0.00 <= float(bonus) <= 1.00, (
        "PRD §3.5: additive_bonus is a number at least 0.00 and at most 1.00."
    )
    assert isinstance(data.get("is_active"), bool)


def assert_quest_bonus(data: Dict[str, Any]) -> None:
    _assert_common_fields_mutable(data)
    assert isinstance(data.get("name"), str)
    assert isinstance(data.get("target_ride_count"), int)
    assert data["target_ride_count"] >= 1, (
        "PRD §3.6: target_ride_count at least 1."
    )
    assert isinstance(data.get("bonus_amount_cents"), int)
    assert data["bonus_amount_cents"] >= 0, (
        "PRD §3.6: bonus_amount_cents at least 0."
    )
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert data.get("status") in ("SCHEDULED", "ACTIVE", "CLOSED")


def assert_ride(data: Dict[str, Any]) -> None:
    _assert_common_fields_mutable(data)
    assert is_valid_uuid(data.get("rider_id", ""))
    drv = data.get("driver_id")
    assert drv is None or is_valid_uuid(drv)
    assert isinstance(data.get("pickup_grid_code"), str)
    assert isinstance(data.get("dropoff_grid_code"), str)
    assert isinstance(data.get("distance_km"), (int, float))
    assert float(data["distance_km"]) > 0
    assert data.get("status") in (
        "REQUESTED", "ASSIGNED", "ON_TRIP", "COMPLETED", "CANCELED",
        "DISPUTED", "REFUNDED",
    )
    assert isinstance(data.get("base_fare_cents"), int)
    assert isinstance(data.get("pickup_multiplier_snapshot"), (int, float))
    assert isinstance(data.get("rush_hour_bonus_snapshot"), (int, float))
    assert isinstance(data.get("quoted_fare_cents"), int)
    assert is_iso8601_timestamp(data.get("requested_at", ""))
    # completed_at / final_fare_cents / driver_earnings_cents may be null.
    fc = data.get("final_fare_cents")
    assert fc is None or isinstance(fc, int)
    de = data.get("driver_earnings_cents")
    assert de is None or isinstance(de, int)
    ca = data.get("completed_at")
    assert ca is None or is_iso8601_timestamp(ca)


def assert_dispute(data: Dict[str, Any]) -> None:
    _assert_common_fields_mutable(data)
    assert is_valid_uuid(data.get("ride_id", ""))
    assert is_valid_uuid(data.get("rider_id", ""))
    assert data.get("reason_code") in (
        "OVERCHARGE", "DRIVER_NO_SHOW", "ROUTE_DEVIATION", "OTHER",
    )
    assert isinstance(data.get("requested_refund_cents"), int)
    assert data["requested_refund_cents"] > 0
    arc = data.get("approved_refund_cents")
    assert arc is None or (isinstance(arc, int) and arc >= 0)
    assert data.get("status") in ("OPEN", "APPROVED", "REJECTED")
    ra = data.get("resolved_at")
    assert ra is None or is_iso8601_timestamp(ra)


def assert_airport_queue_row(data: Dict[str, Any]) -> None:
    """PRD §2.4: AirportQueue carries only id and created_at — no
    updated_at, no version."""
    _assert_common_fields_append_only(data)
    assert "updated_at" not in data, (
        "PRD §2.4: an AirportQueue row carries only id and created_at "
        "(no updated_at)."
    )
    assert "version" not in data, (
        "PRD §2.4: an AirportQueue row carries only id and created_at "
        "(no version)."
    )
    assert isinstance(data.get("grid_code"), str)
    assert is_valid_uuid(data.get("driver_id", ""))
    assert isinstance(data.get("position"), int)
    assert data["position"] >= 1, (
        "PRD §3.2: position is 1-indexed."
    )
    assert is_iso8601_timestamp(data.get("joined_at", ""))


def assert_heatmap_snapshot_row(data: Dict[str, Any]) -> None:
    """PRD §2.4: HeatMapSnapshot carries only id and created_at — no
    updated_at, no version."""
    _assert_common_fields_append_only(data)
    assert "updated_at" not in data, (
        "PRD §2.4: a HeatMapSnapshot row carries only id and created_at "
        "(no updated_at)."
    )
    assert "version" not in data, (
        "PRD §2.4: a HeatMapSnapshot row carries only id and created_at "
        "(no version)."
    )
    assert isinstance(data.get("grid_code"), str)
    assert isinstance(data.get("multiplier"), (int, float))
    assert isinstance(data.get("active_driver_count"), int)
    assert isinstance(data.get("open_demand_count"), int)
    assert is_iso8601_timestamp(data.get("snapshot_at", ""))


# ---------------------------------------------------------------------------
# Domain invariants — PRD §2.5 surge formula, §3.3 / §3.4 fare formulas.
# ---------------------------------------------------------------------------
def expected_surge_multiplier(active_driver_count: int,
                              open_demand_count: int,
                              is_airport: bool) -> float:
    """Reference implementation of PRD §2.5 surge_multiplier.

    Three steps, in order, exactly as PRD §2.5 prescribes:
    Step 1 — supply/demand ratio tier;
    Step 2 — additive AIRPORT_SURCHARGE if grid.is_airport;
    Step 3 — apply MULTIPLIER_CAP via min(); round half-up to 2dp.
    """
    if active_driver_count == 0 and open_demand_count == 0:
        raw = 1.00
    elif active_driver_count == 0:
        raw = MULTIPLIER_CAP
    else:
        ratio = open_demand_count / active_driver_count
        raw = SURGE_ABOVE_TOP
        for upper, tier_val in SURGE_TIER_THRESHOLDS:
            if ratio <= upper:
                raw = tier_val
                break
    if is_airport:
        raw += AIRPORT_SURCHARGE
    return round_half_up_2(min(raw, MULTIPLIER_CAP))


def expected_base_fare_cents(distance_km: float) -> int:
    """PRD §3.3: base_fare_cents = BASE_FARE_CENTS (250) + round_half_up
    (distance_km * PER_KM_CENTS (120))."""
    return BASE_FARE_CENTS + round_half_up_int(distance_km * PER_KM_CENTS)


def expected_quoted_fare_cents(base_fare_cents: int,
                               pickup_multiplier_snapshot: float,
                               rush_hour_bonus_snapshot: float) -> int:
    """PRD §3.3: effective multiplier = min(pickup + rush, CAP); then
    quoted = round_half_up(base * eff_mult)."""
    eff = min(
        pickup_multiplier_snapshot + rush_hour_bonus_snapshot,
        MULTIPLIER_CAP,
    )
    return round_half_up_int(base_fare_cents * eff)


def expected_final_fare_cents(base_fare_cents: int,
                              live_pickup_multiplier: float,
                              live_rush_hour_bonus: float) -> int:
    """PRD §3.4: chronological variant — re-read multiplier + rush bonus
    at the completion instant; cap; round half-up."""
    eff = min(
        live_pickup_multiplier + live_rush_hour_bonus, MULTIPLIER_CAP,
    )
    return round_half_up_int(base_fare_cents * eff)


def expected_driver_earnings_cents(final_fare_cents: int) -> int:
    """PRD §3.4: "The ride's driver_earnings_cents is the
    final_fare_cents multiplied by the quantity one minus the
    PLATFORM_FEE_RATE, rounded half-up to an integer cent." The two
    roundings — fare first, earnings second — run in that fixed order.
    """
    return round_half_up_int(final_fare_cents * (1 - PLATFORM_FEE_RATE))


def expected_earnings_clawback(approved_refund_cents: int) -> int:
    """PRD §3.7: "the driver's total_earnings_cents is decremented by
    the driver-share equivalent of the refund — that is, the
    approved_refund_cents multiplied by the quantity one minus the
    PLATFORM_FEE_RATE, rounded half-up to an integer cent, clamped so
    that total_earnings_cents never falls below zero."
    """
    return round_half_up_int(approved_refund_cents * (1 - PLATFORM_FEE_RATE))


def assert_ride_quoted_fare_matches_formula(ride: Dict[str, Any]) -> None:
    """Verify a Ride's quoted_fare_cents matches the §3.3 formula given
    its pinned snapshots and base."""
    expected = expected_quoted_fare_cents(
        ride["base_fare_cents"],
        float(ride["pickup_multiplier_snapshot"]),
        float(ride["rush_hour_bonus_snapshot"]),
    )
    assert ride["quoted_fare_cents"] == expected, (
        f"PRD §3.3: quoted_fare_cents={ride['quoted_fare_cents']} but "
        f"expected {expected} from "
        f"base={ride['base_fare_cents']} * min("
        f"{ride['pickup_multiplier_snapshot']}"
        f"+{ride['rush_hour_bonus_snapshot']}, {MULTIPLIER_CAP})."
    )


def assert_ride_base_fare_matches_formula(ride: Dict[str, Any]) -> None:
    expected = expected_base_fare_cents(float(ride["distance_km"]))
    assert ride["base_fare_cents"] == expected, (
        f"PRD §3.3: base_fare_cents={ride['base_fare_cents']} but "
        f"expected {expected} from distance_km={ride['distance_km']}."
    )


def find_in_list(items: Iterable[Dict[str, Any]],
                 **filters) -> Dict[str, Any] | None:
    """Find the first item in items whose key/value pairs match
    filters. Returns None if no match."""
    for item in items:
        if all(item.get(k) == v for k, v in filters.items()):
            return item
    return None


__all__ = [
    "assert_airport_queue_row",
    "assert_dispute",
    "assert_driver",
    "assert_grid",
    "assert_heatmap_snapshot_row",
    "assert_quest_bonus",
    "assert_ride",
    "assert_ride_base_fare_matches_formula",
    "assert_ride_quoted_fare_matches_formula",
    "assert_rider",
    "assert_rush_hour_window",
    "expected_base_fare_cents",
    "expected_driver_earnings_cents",
    "expected_earnings_clawback",
    "expected_final_fare_cents",
    "expected_quoted_fare_cents",
    "expected_surge_multiplier",
    "find_in_list",
    "round_half_up_2",
    "round_half_up_int",
]
