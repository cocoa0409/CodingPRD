"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the shape of a single API response data
dict against PRD §3 and §2.4 (common-fields exceptions for the immutable
PointsTransaction and MembershipYear families).
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    FIXED_AWARD_TABLE,
    SEGMENT_FARE_CLASS_MULT,
    SEGMENT_MAX_PER_SEGMENT,
    SEGMENT_MIN_PER_SEGMENT,
    SEGMENT_TIER_BONUS_MULT,
)


# ---------------------------------------------------------------------------
# Common-field assertion helpers.
# ---------------------------------------------------------------------------
def _assert_common_fields_mutable(data: Dict[str, Any]) -> None:
    """For entities with common_fields: true — PRD §2.4 says they
    carry id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO-8601 with 3 fractional digits, "
        f"got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO-8601 with 3 fractional digits, "
        f"got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def _assert_common_fields_append_only(data: Dict[str, Any]) -> None:
    """For entities with common_fields: false — PRD §2.4 explicitly
    states "PointsTransaction is an immutable append-only ledger entry
    that carries only id and created_at, with no updated_at and no
    version" and the same for MembershipYear."""
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO-8601 with 3 fractional digits, "
        f"got {data.get('created_at')!r}"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions.
# ---------------------------------------------------------------------------
def assert_member(data: Dict[str, Any]) -> None:
    _assert_common_fields_mutable(data)
    assert isinstance(data.get("email"), str) and len(data["email"]) > 0
    assert isinstance(data.get("display_name"), str)
    assert data.get("home_region") in ("DOMESTIC", "INTERNATIONAL")
    assert data.get("status") in ("ACTIVE", "FROZEN", "CLOSED")
    assert data.get("tier") in ("BASIC", "SILVER", "GOLD", "PLATINUM")
    assert data.get("tier_source") in ("EARNED", "STATUS_MATCH")
    assert isinstance(data.get("points_balance"), int) and data["points_balance"] >= 0, (
        "PRD §2.8: A member's points_balance is never negative."
    )
    assert isinstance(data.get("current_year_qualifying_segments"), int)
    assert isinstance(data.get("current_year_qualifying_points"), int)
    assert isinstance(data.get("current_membership_year"), int)


def assert_flight(data: Dict[str, Any]) -> None:
    _assert_common_fields_mutable(data)
    assert isinstance(data.get("flight_number"), str)
    assert isinstance(data.get("origin"), str) and len(data["origin"]) == 3
    assert isinstance(data.get("destination"), str) and len(data["destination"]) == 3
    assert isinstance(data.get("distance_miles"), int) and data["distance_miles"] > 0
    assert data.get("route_region") in ("DOMESTIC", "INTERNATIONAL")
    assert is_iso8601_timestamp(data.get("departure_at", ""))
    assert data.get("status") in ("SCHEDULED", "DEPARTED", "CANCELLED")
    assert isinstance(data.get("base_fare_cents"), int) and data["base_fare_cents"] >= 0
    for cap_field in ("capacity_economy", "capacity_business", "capacity_first"):
        assert isinstance(data.get(cap_field), int) and data[cap_field] >= 0
    if "load_factor" in data and data["load_factor"] is not None:
        lf = float(data["load_factor"])
        assert 0.0 <= lf <= 1.0, "load_factor in [0.0, 1.0] inclusive (PRD §3.2)"


def assert_flight_segment(data: Dict[str, Any]) -> None:
    _assert_common_fields_mutable(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_valid_uuid(data.get("flight_id", ""))
    assert data.get("booked_cabin") in ("ECONOMY", "BUSINESS", "FIRST")
    assert data.get("status") in ("BOOKED", "FLOWN", "CANCELLED", "REFUNDED")
    if data.get("flown_cabin") is not None:
        assert data["flown_cabin"] in ("ECONOMY", "BUSINESS", "FIRST")


def assert_upgrade_request(data: Dict[str, Any]) -> None:
    _assert_common_fields_mutable(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_valid_uuid(data.get("flight_segment_id", ""))
    assert is_valid_uuid(data.get("flight_id", ""))
    assert data.get("target_cabin") in ("BUSINESS", "FIRST")
    assert isinstance(data.get("points_offered"), int) and data["points_offered"] >= 0
    assert data.get("status") in (
        "WAITLISTED", "CONFIRMED", "DENIED", "EXPIRED", "CANCELLED",
    )
    assert isinstance(data.get("waitlist_join_seq"), int) and data["waitlist_join_seq"] >= 1
    assert isinstance(data.get("priority_score"), int)
    assert isinstance(data.get("held_points"), int) and data["held_points"] >= 0


def assert_award_booking(data: Dict[str, Any]) -> None:
    _assert_common_fields_mutable(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_valid_uuid(data.get("flight_id", ""))
    assert data.get("cabin") in ("ECONOMY", "BUSINESS", "FIRST")
    assert data.get("pricing_mode") in ("DYNAMIC", "FIXED")
    assert isinstance(data.get("points_cost"), int) and data["points_cost"] >= 0
    assert data.get("status") in (
        "HELD", "CONFIRMED", "CANCELLED", "REFUNDED", "EXPIRED",
    )
    assert is_iso8601_timestamp(data.get("held_until", ""))


def assert_companion_certificate(data: Dict[str, Any]) -> None:
    _assert_common_fields_mutable(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert data.get("status") in (
        "ACTIVE", "RESERVED", "USED", "EXPIRED", "REVOKED",
    )
    assert is_iso8601_timestamp(data.get("issued_at", ""))
    assert is_iso8601_timestamp(data.get("expires_at", ""))
    assert data.get("issued_reason") in ("TIER_REACHED_PLATINUM", "ADMIN_GRANT")


def assert_status_match_request(data: Dict[str, Any]) -> None:
    _assert_common_fields_mutable(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert isinstance(data.get("competitor_program"), str)
    assert data.get("competitor_tier") in ("BASIC", "SILVER", "GOLD", "PLATINUM")
    assert isinstance(data.get("evidence_url"), str)
    assert data.get("status") in (
        "PENDING", "APPROVED", "ACTIVE", "EXPIRED", "REJECTED",
    )


def assert_points_transaction(data: Dict[str, Any]) -> None:
    _assert_common_fields_append_only(data)
    assert "updated_at" not in data, (
        "PRD §2.4: PointsTransaction carries only id and created_at, "
        "with no updated_at."
    )
    assert "version" not in data, (
        "PRD §2.4: PointsTransaction carries only id and created_at, "
        "with no version."
    )
    assert is_valid_uuid(data.get("member_id", ""))
    assert data.get("kind") in (
        "ACCRUAL", "REDEMPTION", "REDEMPTION_REFUND",
        "GIFT_OUT", "GIFT_IN", "GIFT_FEE",
        "EXPIRATION", "STATUS_MATCH_BONUS", "ADMIN_ADJUSTMENT",
    )
    assert isinstance(data.get("points_delta"), int)
    assert is_iso8601_timestamp(data.get("posted_at", ""))


def assert_membership_year(data: Dict[str, Any]) -> None:
    _assert_common_fields_append_only(data)
    assert "updated_at" not in data, (
        "PRD §2.4: MembershipYear carries only id and created_at, with "
        "no updated_at."
    )
    assert "version" not in data, (
        "PRD §2.4: MembershipYear carries only id and created_at, with "
        "no version."
    )
    assert is_valid_uuid(data.get("member_id", ""))
    assert isinstance(data.get("year"), int)
    assert isinstance(data.get("qualifying_segments_final"), int)
    assert isinstance(data.get("qualifying_points_final"), int)
    assert data.get("starting_tier") in ("BASIC", "SILVER", "GOLD", "PLATINUM")
    assert data.get("awarded_tier") in ("BASIC", "SILVER", "GOLD", "PLATINUM")


# ---------------------------------------------------------------------------
# Domain invariant checkers.
# ---------------------------------------------------------------------------
def assert_load_factor_precision(load_factor: float) -> None:
    """PRD §2.9: load_factor "rounded to four decimal places when serialised"."""
    # Allow integer 0 or 1 to be serialised either as 0.0 or 1.0.
    lf = float(load_factor)
    rounded = round(lf, 4)
    assert math.isclose(lf, rounded, abs_tol=1e-9), (
        f"load_factor {lf!r} not rounded to four decimal places"
    )


def expected_segment_accrual(base_fare_cents: int, flown_cabin: str,
                              tier_at_departure: str) -> int:
    """Reference computation per PRD §3.3 Segment accrual formula.

    1. base_dollars = floor(base_fare_cents / 100)
    2. raw = base_dollars * fare_class_mult * tier_bonus_mult (IEEE-754 double)
    3. floor(raw)
    4. clamp to [MIN_PER_SEGMENT, MAX_PER_SEGMENT]
    """
    base_dollars = base_fare_cents // 100
    raw = (
        base_dollars
        * SEGMENT_FARE_CLASS_MULT[flown_cabin]
        * SEGMENT_TIER_BONUS_MULT[tier_at_departure]
    )
    floored = math.floor(raw)
    if floored < SEGMENT_MIN_PER_SEGMENT:
        return SEGMENT_MIN_PER_SEGMENT
    if floored > SEGMENT_MAX_PER_SEGMENT:
        return SEGMENT_MAX_PER_SEGMENT
    return int(floored)


def expected_fixed_award_price(route_region: str, cabin: str) -> int:
    """Reference computation per PRD §3.5 Fixed mode lookup table."""
    return FIXED_AWARD_TABLE[route_region][cabin]


def expected_priority_score(tier: str, points_offered: int,
                            waitlist_join_seq: int) -> int:
    """Reference computation per PRD §3.4.

    "Compute priority_score as tier_rank multiplied by 10 000 000, plus
    points_offered, minus waitlist_join_seq."
    """
    tier_rank = {"BASIC": 0, "SILVER": 1, "GOLD": 2, "PLATINUM": 3}[tier]
    return tier_rank * 10_000_000 + points_offered - waitlist_join_seq


def assert_version_incremented_by_one(prev: Dict[str, Any],
                                      curr: Dict[str, Any]) -> None:
    """PRD §2.4: "version is an integer that starts at 1 and increments
    by exactly one with every server-side mutation."
    """
    assert curr["version"] == prev["version"] + 1, (
        f"version expected {prev['version'] + 1}, got {curr['version']}"
    )


def assert_ledger_sum_matches_balance(transactions: Iterable[Dict[str, Any]],
                                      member_balance: int) -> None:
    """PRD §2.8: "The single source of truth for a member's
    points_balance is the PointsTransaction ledger. The balance is
    exactly the signed sum of every points_delta whose posted_at is less
    than or equal to now."
    """
    total = sum(int(t["points_delta"]) for t in transactions)
    assert total == member_balance, (
        f"Ledger sum {total} != member.points_balance {member_balance} "
        f"(PRD §2.8 conservation contract)"
    )


def filter_transactions_by_kind(transactions: List[Dict[str, Any]],
                                kind: str) -> List[Dict[str, Any]]:
    return [t for t in transactions if t.get("kind") == kind]


__all__ = [
    "assert_award_booking",
    "assert_companion_certificate",
    "assert_flight",
    "assert_flight_segment",
    "assert_ledger_sum_matches_balance",
    "assert_load_factor_precision",
    "assert_member",
    "assert_membership_year",
    "assert_points_transaction",
    "assert_status_match_request",
    "assert_upgrade_request",
    "assert_version_incremented_by_one",
    "expected_fixed_award_price",
    "expected_priority_score",
    "expected_segment_accrual",
    "filter_transactions_by_kind",
]
