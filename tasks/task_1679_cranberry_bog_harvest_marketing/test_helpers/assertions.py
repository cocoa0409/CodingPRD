"""Entity assertions and domain invariant checkers (PRD §2.4, §2.5, §3).

Structural assertions only: identifiers, timestamps, version, enum membership,
and numeric types. Value-level expectations live in the tests themselves so a
failure message names the business rule that broke.
"""
import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_money(actual, expected):
    """Money/barrel quantities are decimal, rounded half-up to 2 places (PRD §2.5).

    A tight tolerance keeps half-up rounding bugs (one cent) visible while
    absorbing binary float representation noise for the same decimal literal.
    """
    assert actual == pytest.approx(expected, abs=1e-6), (
        f"Expected {expected}, got {actual}"
    )


def assert_rate4(actual, expected):
    """Pool final rates are rounded half-up to 4 decimal places (PRD §2.5)."""
    assert actual == pytest.approx(expected, abs=1e-8), (
        f"Expected {expected}, got {actual}"
    )


def _assert_common(data: dict):
    """PRD §2.4 common resource properties."""
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_season(data: dict):
    _assert_common(data)
    assert isinstance(data["year"], int)
    assert isinstance(data["harvest_window_start"], str)
    assert isinstance(data["harvest_window_end"], str)
    assert data["status"] in ("SETUP", "OPEN", "HARVEST_CLOSED", "SETTLED")


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["member_code"], str) and data["member_code"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["status"] in ("PENDING", "ACTIVE", "SUSPENDED", "WITHDRAWN")


def assert_member_quota(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["season_id"])
    assert data["posture"] in ("WITHIN_QUOTA", "OVER_QUOTA")
    assert isinstance(data["quota_locked"], bool)
    assert data["delivered_barrels"] >= 0
    assert data["over_quota_barrels"] >= 0


def assert_bog(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert data["acres"] > 0
    assert data["variety"] in ("STEVENS", "BEN_LEAR", "MULICA_QUEEN", "EARLY_BLACK")
    assert data["sprinkler_demand_gpm"] > 0
    assert data["status"] in ("ACTIVE", "RENOVATION_PLANNED", "UNDER_RENOVATION",
                              "REPLANTED")


def assert_yield_estimate(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["bog_id"])
    assert is_valid_uuid(data["season_id"])
    assert is_valid_uuid(data["member_id"])
    assert data["estimated_barrels"] > 0
    assert isinstance(data["revision_count"], int)
    assert data["status"] in ("SUBMITTED", "APPROVED", "FLAGGED")


def assert_receiving_station(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["daily_capacity_barrels"] > 0


def assert_harvest_ticket(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["bog_id"])
    assert is_valid_uuid(data["season_id"])
    assert is_valid_uuid(data["member_id"])
    assert data["method"] in ("WET", "DRY")
    assert data["status"] in ("REQUESTED", "APPROVED", "COMPLETED", "CANCELLED",
                              "EXPIRED")


def assert_frost_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["bog_id"])
    assert is_valid_uuid(data["season_id"])
    assert isinstance(data["damage_flag"], bool)
    assert data["status"] in ("DECLARED", "ACTIVE", "COMPLETED", "CANCELLED")


def assert_pool(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["season_id"])
    assert data["code"] in ("MAIN", "OVER_QUOTA")
    assert data["status"] in ("OPEN", "CLOSED", "SETTLED")
    assert 0 <= data["retain_pct"] <= 1


def assert_delivery(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["season_id"])
    assert is_valid_uuid(data["bog_id"])
    assert is_valid_uuid(data["receiving_station_id"])
    assert data["expected_barrels"] > 0
    assert isinstance(data["dispute_count"], int)
    assert data["status"] in ("SCHEDULED", "RECEIVED", "GRADED", "DISPUTED",
                              "ACCEPTED", "REJECTED", "VOIDED")
    if data.get("grade") is not None:
        assert data["grade"] in ("A", "B", "C", "REJECT")


def assert_patronage_distribution(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["pool_id"])
    assert is_valid_uuid(data["member_id"])
    assert data["weighted_barrels"] > 0
    assert data["status"] in ("COMPUTED", "APPROVED", "PAID")


def assert_pool_money_invariants(pool: dict):
    """Aggregate pool quantities never go negative mid-lifecycle (PRD §3.8)."""
    assert pool["accepted_net_barrels"] >= 0
    assert pool["weighted_barrels_total"] >= 0
    assert pool["advances_outstanding"] >= 0
