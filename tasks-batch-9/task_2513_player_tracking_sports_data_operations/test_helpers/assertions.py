"""
Domain assertion helpers and the reference implementations of the PRD's
arithmetic disciplines.

The three numeric disciplines of PRD 2.7 are implemented once here — half-up
rounding, ceiling, and exact arithmetic — so that a test can state an expected
figure either as a literal or as the formula the PRD gives, and both agree.
"""

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, List, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    CANONICAL_DRIFT_PCT,
    EXPECTED_ACCEPTED_TAGS_PER_GAME,
    GENERATION_SCALE,
    LATENCY_PREMIUM_MS,
    LATENCY_STANDARD_MS,
    LEAGUE_RESERVE_FRACTION,
    MULTIPLIER_BASE,
    MULTIPLIER_PREMIUM,
    MULTIPLIER_STANDARD,
    PENALTY_WEIGHT_APPROVED,
    PENALTY_WEIGHT_REJECTED,
    QUALITY_WEIGHT_COMPLETENESS,
    QUALITY_WEIGHT_CONFIDENCE,
    QUALITY_WEIGHT_PENALTY,
    SLA_CREDIT_FRACTION,
    TIER_RATE_CENTS,
)
from .types import IMMUTABLE_FORBIDDEN_FIELDS, Json


# ---------------------------------------------------------------------------
# Numeric disciplines
# ---------------------------------------------------------------------------

def round_half_up(value: float, places: int) -> float:
    """Round half up to a fixed number of decimal places (PRD 2.7)."""
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def round_half_up_cents(value: float) -> int:
    """Charges expressed in cents are integers produced by rounding half up."""
    return int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def ceil_units(value: float) -> int:
    """Ceiling to the next whole unit (PRD 2.7), tolerant of binary float dust."""
    exact = Decimal(str(value))
    # Snap a value that is within a hair of an integer onto that integer so the
    # ceiling reflects the exact arithmetic the PRD describes.
    snapped = exact.quantize(Decimal("1.000000000"), rounding=ROUND_HALF_UP)
    return int(math.ceil(snapped))


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

def expected_composite_rms_mm(x_mm: float, y_mm: float, z_mm: float) -> float:
    """The quadratic mean of the three axis errors, half-up to 2 dp (PRD 3.2)."""
    return round_half_up(math.sqrt((x_mm ** 2 + y_mm ** 2 + z_mm ** 2) / 3), 2)


# ---------------------------------------------------------------------------
# Quality index
# ---------------------------------------------------------------------------

def expected_quality_index(
    scored_confidences: Sequence[float],
    approved_correction_count: int,
    rejected_correction_count: int,
    accepted_tag_count: int,
) -> float:
    """The quality index of PRD 3.6, half-up to four decimal places."""
    if not scored_confidences:
        return 0.0
    mean_confidence = sum(scored_confidences) / len(scored_confidences)
    penalty = (
        approved_correction_count * PENALTY_WEIGHT_APPROVED
        + rejected_correction_count * PENALTY_WEIGHT_REJECTED
    ) / max(1, accepted_tag_count)
    penalty = min(1.0, penalty)
    completeness = min(1.0, accepted_tag_count / EXPECTED_ACCEPTED_TAGS_PER_GAME)
    index = (
        QUALITY_WEIGHT_CONFIDENCE * mean_confidence
        + QUALITY_WEIGHT_PENALTY * (1 - penalty)
        + QUALITY_WEIGHT_COMPLETENESS * completeness
    )
    return round_half_up(index, 4)


# ---------------------------------------------------------------------------
# Minute ledger
# ---------------------------------------------------------------------------

def expected_league_reserve_minutes(licensable_minutes: int) -> int:
    """Fifteen percent of the gross licensable figure, rounded up (PRD 3.7)."""
    return ceil_units(licensable_minutes * LEAGUE_RESERVE_FRACTION)


def expected_allocated_minutes(seconds: int) -> int:
    """A window's own draw: seconds / 60 rounded up, once per window."""
    return ceil_units(seconds / 60)


# ---------------------------------------------------------------------------
# Billing
# ---------------------------------------------------------------------------

def expected_latency_multiplier(requested_latency_ms: int) -> float:
    """The latency premium of PRD 3.8."""
    if requested_latency_ms <= LATENCY_PREMIUM_MS:
        return MULTIPLIER_PREMIUM
    if requested_latency_ms <= LATENCY_STANDARD_MS:
        return MULTIPLIER_STANDARD
    return MULTIPLIER_BASE


def expected_reserved_units(
    bandwidth_mbps: float, duration_seconds: int, requested_latency_ms: int
) -> int:
    """Reserved-forward variant: one ceiling over the whole booked window."""
    duration_minutes = duration_seconds / 60
    multiplier = expected_latency_multiplier(requested_latency_ms)
    return ceil_units(bandwidth_mbps * duration_minutes * multiplier)


def expected_charge_cents(units: int, tier: str) -> int:
    """Units at the tier rate, half-up to whole cents."""
    return round_half_up_cents(units * TIER_RATE_CENTS[tier])


def expected_record_units(
    bandwidth_mbps: float, duration_seconds: int, latency_multiplier: float
) -> int:
    """Metered-actual variant: one ceiling per usage record."""
    return ceil_units(bandwidth_mbps * (duration_seconds / 60) * latency_multiplier)


def expected_sla_credit_cents(units_charged: int, tier: str) -> int:
    """A quarter of the record's charge, half-up to whole cents."""
    return round_half_up_cents(
        units_charged * TIER_RATE_CENTS[tier] * SLA_CREDIT_FRACTION
    )


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def expected_raw_generation_value(segment_values: Sequence[float], generation: str) -> float:
    """Each segment scaled and rounded, then summed, then rounded (PRD 3.9)."""
    scale = GENERATION_SCALE[generation]
    per_segment = [round_half_up(value * scale, 2) for value in segment_values]
    return round_half_up(sum(per_segment), 2)


def expected_canonical_season_value(
    segment_values: Sequence[float], generation: str
) -> float:
    """Exact sum, scaled once, drift applied, rounded exactly once (PRD 3.9)."""
    scale = GENERATION_SCALE[generation]
    drift = CANONICAL_DRIFT_PCT[generation]
    exact_sum = sum(Decimal(str(value)) for value in segment_values)
    scaled = exact_sum * Decimal(str(scale))
    corrected = scaled * (Decimal(1) + Decimal(str(drift)) / Decimal(100))
    return float(corrected.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Envelope / audit-field assertions
# ---------------------------------------------------------------------------

def assert_identity_fields(row: Json) -> None:
    """Every minted resource carries a server-generated UUID id (PRD 2.4)."""
    assert is_valid_uuid(row["id"]), f"id must be a UUID string, got {row.get('id')!r}"
    assert is_iso8601_timestamp(row["created_at"]), (
        f"created_at must be an ISO 8601 timestamp, got {row.get('created_at')!r}"
    )


def assert_mutable_audit_fields(row: Json, expected_version: Optional[int] = None) -> None:
    """A mutable resource carries id, created_at, updated_at and version."""
    assert_identity_fields(row)
    assert is_iso8601_timestamp(row["updated_at"]), (
        f"updated_at must be an ISO 8601 timestamp, got {row.get('updated_at')!r}"
    )
    assert isinstance(row["version"], int), "version must be an integer"
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"expected version {expected_version}, got {row['version']}"
        )


def assert_immutable_record_shape(row: Json) -> None:
    """An immutable resource exposes only id and created_at of the audit group."""
    assert_identity_fields(row)
    for field in IMMUTABLE_FORBIDDEN_FIELDS:
        assert field not in row, (
            f"immutable records must not expose '{field}': {sorted(row)}"
        )


def assert_request_id_prefix(response_body: Json) -> None:
    """meta.api_request_id starts with req_ (PRD 2.2)."""
    request_id = response_body["meta"]["api_request_id"]
    assert request_id.startswith("req_"), (
        f"api_request_id must start with 'req_', got {request_id!r}"
    )


def assert_page_meta(
    meta: Json, limit: int, offset: int, total_count: int, has_more: bool
) -> None:
    """Every list response reports limit, offset, total_count and has_more."""
    assert meta["limit"] == limit, f"expected limit {limit}, got {meta.get('limit')}"
    assert meta["offset"] == offset, f"expected offset {offset}, got {meta.get('offset')}"
    assert meta["total_count"] == total_count, (
        f"expected total_count {total_count}, got {meta.get('total_count')}"
    )
    assert meta["has_more"] is has_more, (
        f"expected has_more {has_more}, got {meta.get('has_more')}"
    )


def assert_created_at_ascending(rows: Iterable[Json]) -> None:
    """List results are ordered by created_at ascending unless stated otherwise."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows are not created_at ascending: {stamps}"


def assert_created_at_descending(rows: Iterable[Json]) -> None:
    """A rig's calibration-run history is returned newest first."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps, reverse=True), (
        f"rows are not newest-first: {stamps}"
    )


# ---------------------------------------------------------------------------
# Census / ledger assertions
# ---------------------------------------------------------------------------

def assert_installation_census(
    venue: Json,
    certified: int,
    recalibrating: int,
    uncertified: int,
    retired: int = 0,
) -> None:
    """The three gating counts sum to active; retired stands outside (PRD 2.11)."""
    assert venue["certified_installation_count"] == certified, (
        f"certified {venue['certified_installation_count']} != {certified}"
    )
    assert venue["recalibrating_installation_count"] == recalibrating, (
        f"recalibrating {venue['recalibrating_installation_count']} != {recalibrating}"
    )
    assert venue["uncertified_installation_count"] == uncertified, (
        f"uncertified {venue['uncertified_installation_count']} != {uncertified}"
    )
    assert venue["retired_installation_count"] == retired, (
        f"retired {venue['retired_installation_count']} != {retired}"
    )
    assert venue["active_installation_count"] == certified + recalibrating + uncertified, (
        "active_installation_count must equal the sum of the three gating counts"
    )


def assert_tag_census(
    game: Json,
    draft: int,
    submitted: int,
    accepted: int,
    under_correction: int,
    superseded: int,
    total: int,
) -> None:
    """The five tag buckets sum to total_tag_count (PRD 2.11)."""
    assert game["draft_tag_count"] == draft, f"draft {game['draft_tag_count']} != {draft}"
    assert game["submitted_tag_count"] == submitted, (
        f"submitted {game['submitted_tag_count']} != {submitted}"
    )
    assert game["accepted_tag_count"] == accepted, (
        f"accepted {game['accepted_tag_count']} != {accepted}"
    )
    assert game["under_correction_tag_count"] == under_correction, (
        f"under_correction {game['under_correction_tag_count']} != {under_correction}"
    )
    assert game["superseded_tag_count"] == superseded, (
        f"superseded {game['superseded_tag_count']} != {superseded}"
    )
    assert game["total_tag_count"] == total, f"total {game['total_tag_count']} != {total}"
    assert draft + submitted + accepted + under_correction + superseded == total, (
        "the five tag buckets must sum to total_tag_count"
    )


def assert_minute_ledger(
    game: Json,
    league_reserve_minutes: int,
    net_allocatable_minutes: int,
    allocated_minutes_total: int,
    remaining_allocatable_minutes: int,
    league_reserve_allocated_minutes: int = 0,
) -> None:
    """The minute ledger invariants of PRD 2.11."""
    assert game["league_reserve_minutes"] == league_reserve_minutes
    assert game["net_allocatable_minutes"] == net_allocatable_minutes
    assert game["allocated_minutes_total"] == allocated_minutes_total
    assert game["remaining_allocatable_minutes"] == remaining_allocatable_minutes
    assert game["league_reserve_allocated_minutes"] == league_reserve_allocated_minutes
    assert (
        game["league_reserve_minutes"] + game["net_allocatable_minutes"]
        == game["licensable_minutes"]
    ), "reserve plus net must equal licensable_minutes"
    assert (
        game["allocated_minutes_total"] + game["remaining_allocatable_minutes"]
        == game["net_allocatable_minutes"]
    ), "allocated plus remaining must equal the net pool"
    assert game["league_reserve_allocated_minutes"] <= game["league_reserve_minutes"], (
        "the reserve draw may never exceed the reserve"
    )


def assert_unit_ledger(
    licensee: Json, available: int, reserved: int, consumed: int
) -> None:
    """available + reserved + consumed == granted_units at all times (PRD 2.11)."""
    assert licensee["available_units"] == available, (
        f"available {licensee['available_units']} != {available}"
    )
    assert licensee["reserved_units"] == reserved, (
        f"reserved {licensee['reserved_units']} != {reserved}"
    )
    assert licensee["consumed_units"] == consumed, (
        f"consumed {licensee['consumed_units']} != {consumed}"
    )
    assert (
        licensee["available_units"]
        + licensee["reserved_units"]
        + licensee["consumed_units"]
        == licensee["granted_units"]
    ), "the unit ledger must sum to granted_units"


def assert_game_dimensions(
    game: Json,
    collection_status: str,
    certification_status: str,
    data_quality_flag: Optional[str] = None,
) -> None:
    """A game's two independent state dimensions (PRD 3.4)."""
    assert game["collection_status"] == collection_status, (
        f"collection_status {game['collection_status']} != {collection_status}"
    )
    assert game["certification_status"] == certification_status, (
        f"certification_status {game['certification_status']} != {certification_status}"
    )
    if data_quality_flag is not None:
        assert game["data_quality_flag"] == data_quality_flag, (
            f"data_quality_flag {game['data_quality_flag']} != {data_quality_flag}"
        )


def assert_quality_index(game: Json, expected: float) -> None:
    """quality_index is stored half-up to four decimal places."""
    actual = float(game["quality_index"])
    assert abs(actual - expected) < 1e-9, (
        f"quality_index {actual!r} != {expected!r}"
    )


def assert_two_dp(value: float, expected: float) -> None:
    actual = float(value)
    assert abs(actual - expected) < 1e-9, f"{actual!r} != {expected!r}"


def assert_null_fields(row: Json, fields: Iterable[str]) -> None:
    for field in fields:
        assert row[field] is None, f"expected {field} to be null, got {row[field]!r}"


def assert_installation_mirrors(
    installation: Json,
    result: Optional[str],
    composite_rms_mm: Optional[float],
    recorded_at_utc: Optional[str],
    engineer_user_id: Optional[str],
) -> None:
    """The four latest-run mirror fields on a rig (PRD 3.2)."""
    assert installation["latest_run_result"] == result
    if composite_rms_mm is None:
        assert installation["latest_run_composite_rms_mm"] is None
    else:
        assert_two_dp(installation["latest_run_composite_rms_mm"], composite_rms_mm)
    assert installation["latest_run_recorded_at_utc"] == recorded_at_utc
    assert installation["latest_run_engineer_user_id"] == engineer_user_id


def ids_of(rows: Iterable[Json]) -> List[str]:
    return [row["id"] for row in rows]
