"""Domain assertions and pure re-implementations of the PRD's arithmetic."""

from decimal import ROUND_HALF_UP, Decimal
from math import asin, cos, radians, sin, sqrt
from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    BREACH_WEIGHT,
    DEPOSIT_PCT_FAR,
    DEPOSIT_PCT_MID,
    DEPOSIT_PCT_NEAR,
    DEPOSIT_TIER_FAR_DAYS,
    DEPOSIT_TIER_NEAR_DAYS,
    DRAW_PENALTY_WEIGHT,
    EARTH_RADIUS_MILES,
    HOSPITALITY_LINE_CAP_CENTS,
    REPORT_WEIGHT,
    SHARE_BRACKET_HI_CENTS,
    SHARE_BRACKET_LO_CENTS,
    SHARE_PCT_HI,
    SHARE_PCT_LO,
    SHARE_PCT_MID,
    TRAVEL_ESCALATION_PCT,
)


# ------------------------------------------------------------------ arithmetic
def round_half_up(value) -> int:
    """Round half up to a whole unit, the only rounding mode in this API."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value) -> float:
    """Round half up to two decimals, used for distances."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def haversine_miles(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance on a sphere of radius 3958.7613 miles."""
    p1, p2 = radians(float(lat1)), radians(float(lat2))
    d_lat = p2 - p1
    d_lon = radians(float(lon2)) - radians(float(lon1))
    a = sin(d_lat / 2) ** 2 + cos(p1) * cos(p2) * sin(d_lon / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * asin(sqrt(a))


def expected_distance_miles(lat1, lon1, lat2, lon2) -> float:
    return round_half_up_2dp(haversine_miles(lat1, lon1, lat2, lon2))


def expected_line_cost_cents(
    quantity: int, effective_unit_cost_cents: int, category: str
) -> int:
    """quantity * effective unit price * (1 + escalation), rounded per line."""
    escalation = TRAVEL_ESCALATION_PCT if category == "TRAVEL" else 0.0
    return round_half_up(
        Decimal(quantity)
        * Decimal(effective_unit_cost_cents)
        * (Decimal(1) + Decimal(str(escalation)))
    )


def expected_contracted_contribution(
    line_cost_cents: int, category: str, is_promoter_provided: bool
) -> int:
    """Contracted-scope contribution of one APPROVED or SUBSTITUTED line."""
    if is_promoter_provided:
        return 0
    if category == "HOSPITALITY":
        return min(line_cost_cents, HOSPITALITY_LINE_CAP_CENTS)
    return line_cost_cents


def expected_draw_penalty(draw_score: int) -> int:
    return round_half_up(Decimal(str(DRAW_PENALTY_WEIGHT)) * Decimal(100 - draw_score))


def expected_strict_risk_score(
    reported_conflict_count: int, radius_breach_count: int, draw_score: int
) -> int:
    return min(
        100,
        REPORT_WEIGHT * reported_conflict_count
        + BREACH_WEIGHT * radius_breach_count
        + expected_draw_penalty(draw_score),
    )


def expected_adjudicated_risk_score(radius_breach_count: int, draw_score: int) -> int:
    return min(
        100, BREACH_WEIGHT * radius_breach_count + expected_draw_penalty(draw_score)
    )


def expected_deposit_pct(days_until_show: int) -> float:
    if days_until_show >= DEPOSIT_TIER_FAR_DAYS:
        return DEPOSIT_PCT_FAR
    if days_until_show >= DEPOSIT_TIER_NEAR_DAYS:
        return DEPOSIT_PCT_MID
    return DEPOSIT_PCT_NEAR


def expected_promoter_share_pct(gross_pre_share_cents: int) -> float:
    if gross_pre_share_cents >= SHARE_BRACKET_HI_CENTS:
        return SHARE_PCT_HI
    if gross_pre_share_cents >= SHARE_BRACKET_LO_CENTS:
        return SHARE_PCT_MID
    return SHARE_PCT_LO


def expected_settlement_total_cents(
    guarantee_cents: int,
    rider_estimate_cents: int,
    waiver_fee_cents: int,
    deposit_paid_cents: int,
) -> int:
    """Settlement in the PRD's pinned order, with one rounding on the share."""
    gross_pre_share = guarantee_cents + rider_estimate_cents + waiver_fee_cents
    share = expected_promoter_share_pct(gross_pre_share)
    reimbursed = round_half_up(Decimal(rider_estimate_cents) * Decimal(str(share)))
    return guarantee_cents + reimbursed + waiver_fee_cents - deposit_paid_cents


# ------------------------------------------------------------------ envelope
def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None):
    """Every resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(entity["id"]), f"id must be a UUID: {entity.get('id')}"
    assert is_iso8601_timestamp(entity["created_at"]), entity.get("created_at")
    assert is_iso8601_timestamp(entity["updated_at"]), entity.get("updated_at")
    assert isinstance(entity["version"], int), "version must be an integer"
    assert entity["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_envelope_meta(body: Dict[str, Any]):
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), meta["api_request_id"]
    assert is_iso8601_timestamp(meta["api_request_timestamp"])


def assert_booking_state(booking: Dict[str, Any], contract: str, settlement: str):
    assert booking["contract_status"] == contract, (
        f"expected contract_status {contract}, got {booking['contract_status']}"
    )
    assert booking["settlement_status"] == settlement, (
        f"expected settlement_status {settlement}, got {booking['settlement_status']}"
    )


def assert_ordered_by(rows: Iterable[Dict[str, Any]], key: str, descending: bool = False):
    values = [row[key] for row in rows]
    expected = sorted(values, reverse=descending)
    assert values == expected, f"rows not ordered by {key}: {values}"


def assert_version_bumped(before: Dict[str, Any], after: Dict[str, Any]):
    assert after["version"] > before["version"], (
        f"version did not advance: {before['version']} -> {after['version']}"
    )
    assert after["updated_at"] >= before["updated_at"], "updated_at moved backwards"
