"""Domain assertions expressed in the PRD's own language.

The rounding disciplines of §2.7 (money at 2 decimal places, MW and MWh at 3,
percentages at 2, `workforce_availability_ratio` at 4, `screening_score` at 2)
and the two conserved quantities of §2.8 are checked here so that individual
tests read as statements about the contract rather than about float tolerances.
"""

from datetime import datetime, timezone
from typing import Iterable, Optional

import pytest

from .types import (
    COMMON_FIELDS,
    LOAD_STUDY_FORBIDDEN_FIELDS,
    LOAD_STUDY_IDENTITY_FIELDS,
)

MONEY_TOLERANCE = 0.01
MW_TOLERANCE = 0.001
PCT_TOLERANCE = 0.01
RATIO_TOLERANCE = 0.0001


# --------------------------------------------------------------------------- #
# numeric comparisons at the PRD's declared precisions
# --------------------------------------------------------------------------- #
def assert_money(actual, expected: float, label: str = "money") -> None:
    """Monetary amounts are carried and reported at 2 decimal places (§2.7)."""
    assert actual is not None, f"{label} must not be null"
    assert actual == pytest.approx(expected, abs=MONEY_TOLERANCE), (
        f"{label}: expected {expected:.2f}, got {actual}"
    )


def assert_mw(actual, expected: float, label: str = "megawatts") -> None:
    """Power and energy quantities are carried at 3 decimal places (§2.7)."""
    assert actual is not None, f"{label} must not be null"
    assert actual == pytest.approx(expected, abs=MW_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_pct(actual, expected: float, label: str = "percentage") -> None:
    """Percentages are reported at 2 decimal places (§2.7)."""
    assert actual is not None, f"{label} must not be null"
    assert actual == pytest.approx(expected, abs=PCT_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_ratio(actual, expected: float, label: str = "ratio") -> None:
    """`workforce_availability_ratio` is rounded to 4 decimal places (§2.7)."""
    assert actual is not None, f"{label} must not be null"
    assert actual == pytest.approx(expected, abs=RATIO_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


# --------------------------------------------------------------------------- #
# the two conserved quantities of §2.8
# --------------------------------------------------------------------------- #
def assert_utility_ledger_conserved(utility: dict) -> None:
    """"A utility's `reserved_capacity_mw` plus its `available_capacity_mw`
    always equals its `total_transmission_capacity_mw`, and
    `available_capacity_mw` is never negative." (§2.8)"""
    reserved = utility["reserved_capacity_mw"]
    available = utility["available_capacity_mw"]
    total = utility["total_transmission_capacity_mw"]
    assert available >= 0, f"available_capacity_mw must never be negative, got {available}"
    assert reserved + available == pytest.approx(total, abs=MW_TOLERANCE), (
        f"reserved {reserved} + available {available} must equal total {total}"
    )


def assert_premium_ledger_conserved(program: dict) -> None:
    """"A program's `option_exposure_usd` plus its `forfeited_premium_usd` plus
    its `capitalized_premium_usd` always equals its
    `premium_committed_total_usd`." (§2.8)"""
    exposure = program["option_exposure_usd"]
    forfeited = program["forfeited_premium_usd"]
    capitalized = program["capitalized_premium_usd"]
    total = program["premium_committed_total_usd"]
    assert exposure + forfeited + capitalized == pytest.approx(
        total, abs=MONEY_TOLERANCE
    ), (
        f"exposure {exposure} + forfeited {forfeited} + capitalized {capitalized} "
        f"must equal premium_committed_total_usd {total}"
    )


def assert_premium_ledger(
    program: dict,
    exposure: float,
    forfeited: float,
    capitalized: float,
    total: float,
) -> None:
    """Assert all four premium buckets and then the conservation identity."""
    assert_money(program["option_exposure_usd"], exposure, "option_exposure_usd")
    assert_money(program["forfeited_premium_usd"], forfeited, "forfeited_premium_usd")
    assert_money(
        program["capitalized_premium_usd"], capitalized, "capitalized_premium_usd"
    )
    assert_money(
        program["premium_committed_total_usd"], total, "premium_committed_total_usd"
    )
    assert_premium_ledger_conserved(program)


def assert_capacity_ledger(
    utility: dict, reserved: float, available: float
) -> None:
    """Assert both ledger figures and then the conservation identity."""
    assert_mw(utility["reserved_capacity_mw"], reserved, "reserved_capacity_mw")
    assert_mw(utility["available_capacity_mw"], available, "available_capacity_mw")
    assert_utility_ledger_conserved(utility)


# --------------------------------------------------------------------------- #
# identity, timestamps and versioning (§2.4)
# --------------------------------------------------------------------------- #
def assert_has_common_fields(resource: dict, label: str = "resource") -> None:
    for field in COMMON_FIELDS:
        assert field in resource, f"{label} must expose '{field}'"


def assert_load_study_shape(study: dict) -> None:
    """"It has no `updated_at` and no `version` field at all, and neither field
    should appear in its representation." (§2.4)"""
    for field in LOAD_STUDY_IDENTITY_FIELDS:
        assert field in study, f"a load study must expose '{field}'"
    for field in LOAD_STUDY_FORBIDDEN_FIELDS:
        assert field not in study, (
            f"a load study must not expose '{field}': it is an immutable "
            f"historical artifact"
        )


def assert_clock_instant(actual, expected: str, label: str = "timestamp") -> None:
    """A server-stamped instant that the PRD ties to the logical clock.

    "At startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and it
    must continue to read that instant until it is explicitly moved" (§2.6), so
    a field the PRD says is "stamped" with "the current logical clock" must
    denote the same instant the clock was set to. The three-fractional-digit
    serialisation of §2.4 is stated only of `created_at` and `updated_at`, so
    this compares the instants rather than the two strings byte for byte.
    """
    assert actual is not None, f"{label} must not be null"
    parsed = datetime.fromisoformat(str(actual).replace("Z", "+00:00"))
    wanted = datetime.fromisoformat(str(expected).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if wanted.tzinfo is None:
        wanted = wanted.replace(tzinfo=timezone.utc)
    assert parsed == wanted, (
        f"{label}: expected the logical clock instant {expected}, got {actual}"
    )


def assert_version(resource: dict, expected: int, label: str = "resource") -> None:
    assert resource["version"] == expected, (
        f"{label}: expected version {expected}, got {resource['version']}"
    )


def assert_version_unchanged(before: dict, after: dict, label: str = "resource") -> None:
    assert before["version"] == after["version"], (
        f"{label}: a refused request must not increment version "
        f"({before['version']} -> {after['version']})"
    )


# --------------------------------------------------------------------------- #
# envelope shape (§2.2)
# --------------------------------------------------------------------------- #
def assert_error_envelope(response) -> dict:
    """"The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`." (§2.2)"""
    body = response.json()
    assert body["response_type"] == "error"
    assert set(body["data"].keys()) == {"error_id", "message"}, (
        f"an error envelope's data carries only error_id and message, got "
        f"{sorted(body['data'].keys())}"
    )
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"an error envelope's meta carries only api_request_id and "
        f"api_request_timestamp, got {sorted(body['meta'].keys())}"
    )
    assert body["meta"]["api_request_id"].startswith("req_")
    return body["data"]


def assert_pagination_meta(
    meta: dict, limit: int, offset: int, total_count: int, has_more: bool
) -> None:
    """"The `meta` object of a list response carries `limit`, `offset`,
    `total_count` and `has_more`." (§2.3)"""
    assert meta["limit"] == limit, f"meta.limit: expected {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, (
        f"meta.offset: expected {offset}, got {meta['offset']}"
    )
    assert meta["total_count"] == total_count, (
        f"meta.total_count: expected {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"meta.has_more: expected {has_more}, got {meta['has_more']}"
    )


# --------------------------------------------------------------------------- #
# domain state assertions
# --------------------------------------------------------------------------- #
def assert_status(resource: dict, expected: str, label: str = "resource") -> None:
    assert resource["status"] == expected, (
        f"{label}: expected status {expected}, got {resource['status']}"
    )


def assert_site_screening_outputs(
    site: dict,
    score: float,
    hazard_tier: str,
    workforce_ratio: Optional[float] = None,
) -> None:
    assert_pct(site["screening_score"], score, "screening_score")
    assert site["hazard_tier"] == hazard_tier, (
        f"hazard_tier: expected {hazard_tier}, got {site['hazard_tier']}"
    )
    if workforce_ratio is not None:
        assert_ratio(
            site["workforce_availability_ratio"],
            workforce_ratio,
            "workforce_availability_ratio",
        )


def assert_land_control(site: dict, pct: float, status: str) -> None:
    assert_pct(site["land_control_pct"], pct, "land_control_pct")
    assert site["land_control_status"] == status, (
        f"land_control_status: expected {status}, got {site['land_control_status']}"
    )


def assert_program_rollup(
    program: dict,
    program_status: Optional[str] = None,
    committed_load_mw: Optional[float] = None,
    renewable_coverage_pct: Optional[float] = None,
    full_land_control_site_count: Optional[int] = None,
) -> None:
    if program_status is not None:
        assert program["program_status"] == program_status, (
            f"program_status: expected {program_status}, got {program['program_status']}"
        )
    if committed_load_mw is not None:
        assert_mw(program["committed_load_mw"], committed_load_mw, "committed_load_mw")
    if renewable_coverage_pct is not None:
        assert_pct(
            program["renewable_coverage_pct"],
            renewable_coverage_pct,
            "renewable_coverage_pct",
        )
    if full_land_control_site_count is not None:
        assert program["full_land_control_site_count"] == full_land_control_site_count, (
            f"full_land_control_site_count: expected "
            f"{full_land_control_site_count}, got "
            f"{program['full_land_control_site_count']}"
        )


def assert_ids_in_order(items: Iterable[dict], expected_ids: Iterable[str]) -> None:
    actual = [item["id"] for item in items]
    expected = list(expected_ids)
    assert actual == expected, f"expected ids in order {expected}, got {actual}"
