"""Domain assertion helpers.

These wrap the framework validators with league-specific vocabulary so the
tests themselves read as PRD prose.
"""
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import (
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_success,
)

from . import constants as C


# --------------------------------------------------------------------------
# Envelope / identity
# --------------------------------------------------------------------------
def assert_common_fields(record: Dict[str, Any]) -> None:
    """PRD §2.5: every resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(record["id"]), f"id is not a UUID: {record['id']}"
    assert is_iso8601_timestamp(record["created_at"])
    assert is_iso8601_timestamp(record["updated_at"])
    assert isinstance(record["version"], int)


def assert_three_digit_millis(value: str) -> None:
    """PRD §2.4: shape YYYY-MM-DDTHH:MM:SS.mmmZ — exactly three digits."""
    assert isinstance(value, str), f"not a string timestamp: {value!r}"
    assert len(value) == 24 and value.endswith("Z") and value[19] == ".", (
        f"timestamp {value!r} is not in the shape YYYY-MM-DDTHH:MM:SS.mmmZ"
    )
    assert value[20:23].isdigit(), f"timestamp {value!r} lacks three millis digits"


def assert_pure_date(value: str) -> None:
    """PRD §2.4: birthdate, age_cutoff_date, enrollment_verified_through and
    background_check_expires_on use YYYY-MM-DD with no time component."""
    assert isinstance(value, str), f"not a string date: {value!r}"
    assert len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"date {value!r} is not in the shape YYYY-MM-DD"
    )


# --------------------------------------------------------------------------
# Precision regimes (PRD §2.8)
# --------------------------------------------------------------------------
def _quantize(value: Any, places: int) -> Decimal:
    return Decimal(str(value)).quantize(
        Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP
    )


def assert_gpa(actual: Any, expected: float) -> None:
    """GPAs are three decimals, rounded half up (PRD §2.8)."""
    assert actual is not None, "expected a GPA, got None"
    assert _quantize(actual, C.GPA_DECIMALS) == _quantize(
        expected, C.GPA_DECIMALS
    ), f"expected GPA {expected!r} at three decimals, got {actual!r}"


def assert_seed_points(actual: Any, expected: float) -> None:
    """Seed points are four decimals, rounded half up (PRD §2.8)."""
    assert actual is not None, "expected seed_points, got None"
    assert _quantize(actual, C.SEED_POINT_DECIMALS) == _quantize(
        expected, C.SEED_POINT_DECIMALS
    ), f"expected seed_points {expected!r} at four decimals, got {actual!r}"


def assert_integrity_score(actual: Any, expected: float) -> None:
    """Integrity scores are two decimals, rounded half up (PRD §2.8)."""
    assert actual is not None, "expected integrity_score, got None"
    assert _quantize(actual, C.INTEGRITY_DECIMALS) == _quantize(
        expected, C.INTEGRITY_DECIMALS
    ), f"expected integrity_score {expected!r} at two decimals, got {actual!r}"


def assert_cents(actual: Any, expected: int) -> None:
    """PRD §2.4: all money is integer cents, never a float or a string."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"money must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"expected {expected} cents, got {actual}"


# --------------------------------------------------------------------------
# Conservation invariants (PRD §2.9)
# --------------------------------------------------------------------------
def assert_starter_capacity_conserved(team: Dict[str, Any], max_starters: int) -> None:
    """PRD §2.9: starter_slots_used + starter_slots_available == max_starters."""
    assert team["starter_slots_used"] + team["starter_slots_available"] == max_starters, (
        "starter capacity conservation broken: "
        f"{team['starter_slots_used']} + {team['starter_slots_available']} "
        f"!= {max_starters}"
    )


def assert_subsidy_conserved(
    district: Dict[str, Any], granted_total: int
) -> None:
    """PRD §2.9: remaining pool + granted across the district's teams equals
    the immutable subsidy_pool_initial_cents."""
    assert (
        district["subsidy_pool_cents"] + granted_total
        == district["subsidy_pool_initial_cents"]
    ), (
        "subsidy conservation broken: "
        f"{district['subsidy_pool_cents']} + {granted_total} != "
        f"{district['subsidy_pool_initial_cents']}"
    )


def assert_match_point_pool(season: Dict[str, Any], expected: int) -> None:
    """PRD §2.9: a season's match_point_pool equals the sum of its teams'
    match_points."""
    assert season["match_point_pool"] == expected, (
        f"expected match_point_pool {expected}, got {season['match_point_pool']}"
    )


# --------------------------------------------------------------------------
# Version / state helpers
# --------------------------------------------------------------------------
def assert_version_is(record: Dict[str, Any], expected: int) -> None:
    """PRD §2.5: version increments by exactly one on every mutation."""
    assert record["version"] == expected, (
        f"expected version {expected}, got {record['version']}"
    )


def assert_version_advanced_by(
    before: Dict[str, Any], after: Dict[str, Any], delta: int = 1
) -> None:
    assert after["version"] == before["version"] + delta, (
        f"expected version to advance by {delta} from {before['version']}, "
        f"got {after['version']}"
    )


def assert_match_state(
    match: Dict[str, Any],
    play_status: Optional[str] = None,
    result_status: Optional[str] = None,
    dispute_status: Optional[str] = None,
    broadcast_status: Optional[str] = None,
) -> None:
    """PRD §3.7: a match carries four independent state dimensions."""
    if play_status is not None:
        assert match["play_status"] == play_status, (
            f"expected play_status {play_status}, got {match['play_status']}"
        )
    if result_status is not None:
        assert match["result_status"] == result_status, (
            f"expected result_status {result_status}, got {match['result_status']}"
        )
    if dispute_status is not None:
        assert match["dispute_status"] == dispute_status, (
            f"expected dispute_status {dispute_status}, got {match['dispute_status']}"
        )
    if broadcast_status is not None:
        assert match["broadcast_status"] == broadcast_status, (
            "expected broadcast_status "
            f"{broadcast_status}, got {match['broadcast_status']}"
        )


def assert_slot_axes(
    slot: Dict[str, Any],
    verification_status: Optional[str] = None,
    academic_status: Optional[str] = None,
    participation_status: Optional[str] = None,
) -> None:
    """PRD §3.5: two independent verification axes plus the derived third."""
    if verification_status is not None:
        assert slot["verification_status"] == verification_status, (
            "expected verification_status "
            f"{verification_status}, got {slot['verification_status']}"
        )
    if academic_status is not None:
        assert slot["academic_status"] == academic_status, (
            f"expected academic_status {academic_status}, "
            f"got {slot['academic_status']}"
        )
    if participation_status is not None:
        assert slot["participation_status"] == participation_status, (
            "expected participation_status "
            f"{participation_status}, got {slot['participation_status']}"
        )


def data_of(response: Any, expected_status: int = 200) -> Dict[str, Any]:
    """Validate the success envelope and hand back ``data``."""
    validate_success(response, expected_status=expected_status)
    return get_success_data(response)
