"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp, assert_cost_precision,
)

SPACE_STATES = ["DRAFT", "AVAILABLE", "ON_HOLD", "UNDER_LOI", "LEASED", "OFF_MARKET"]
LISTING_STATES = ["DRAFT", "ACTIVE", "UNDER_NEGOTIATION", "EXECUTED", "WITHDRAWN"]
REQUIREMENT_STATES = ["OPEN", "TOURING", "NEGOTIATING", "PLACED", "CLOSED_LOST"]
TOUR_STATES = ["REQUESTED", "CONFIRMED", "COMPLETED", "CANCELLED", "NO_SHOW"]
DEAL_STAGES = ["PROSPECT", "LOI_DRAFT", "LOI_COUNTERED", "LOI_ACCEPTED", "LEASE_OUT", "EXECUTED", "DEAD"]
PROPOSAL_OUTCOMES = ["PENDING", "COUNTERED", "ACCEPTED", "REJECTED"]


def _common_full(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def _common_lean(data: dict):
    """Lean record: id + created_at only; no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_brokerage(data: dict):
    _common_full(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["side"] in ["LISTING", "TENANT_REP", "DUAL"]
    assert isinstance(data["default_commission_pct"], (int, float))
    assert 0 < data["default_commission_pct"] <= 0.15


def assert_broker(data: dict):
    _common_full(data)
    assert is_valid_uuid(data["brokerage_id"])
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["license_no"], str) and len(data["license_no"]) > 0
    assert data["role"] in ["LISTING_BROKER", "TENANT_BROKER", "ADMIN"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_property(data: dict):
    _common_full(data)
    assert is_valid_uuid(data["listing_broker_id"])
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["market"], str) and len(data["market"]) > 0
    assert data["asset_class"] in ["OFFICE", "RETAIL", "INDUSTRIAL", "FLEX"]
    assert isinstance(data["total_sf"], int) and data["total_sf"] >= 1
    assert isinstance(data["available_sf"], int) and data["available_sf"] >= 0


def assert_space(data: dict):
    _common_full(data)
    assert is_valid_uuid(data["property_id"])
    assert isinstance(data["suite_no"], str) and len(data["suite_no"]) > 0
    assert isinstance(data["rentable_sf"], int) and data["rentable_sf"] >= 1
    assert isinstance(data["asking_rent_psf_yr"], (int, float)) and data["asking_rent_psf_yr"] > 0
    assert isinstance(data["free_rent_months"], int) and 0 <= data["free_rent_months"] <= 24
    assert isinstance(data["ti_allowance_psf"], (int, float)) and data["ti_allowance_psf"] >= 0
    assert data["status"] in SPACE_STATES


def assert_listing(data: dict):
    _common_full(data)
    assert is_valid_uuid(data["space_id"])
    assert is_valid_uuid(data["listing_broker_id"])
    assert isinstance(data["term_months"], int) and data["term_months"] >= 1
    assert 0 <= data["annual_escalation_pct"] <= 0.20
    assert 0 <= data["co_broke_offered_pct"] <= 1
    assert data["status"] in LISTING_STATES
    assert isinstance(data["open_deal_count"], int) and data["open_deal_count"] >= 0


def assert_requirement(data: dict):
    _common_full(data)
    assert is_valid_uuid(data["tenant_broker_id"])
    assert isinstance(data["tenant_name"], str) and len(data["tenant_name"]) > 0
    assert isinstance(data["market"], str) and len(data["market"]) > 0
    assert data["asset_class"] in ["OFFICE", "RETAIL", "INDUSTRIAL", "FLEX"]
    assert isinstance(data["min_sf"], int) and data["min_sf"] >= 1
    assert isinstance(data["max_sf"], int) and data["max_sf"] >= data["min_sf"]
    assert data["max_rent_psf_yr"] > 0
    assert data["status"] in REQUIREMENT_STATES
    assert isinstance(data["match_count"], int) and data["match_count"] >= 0


def assert_tour(data: dict):
    _common_full(data)
    assert is_valid_uuid(data["requirement_id"])
    assert is_valid_uuid(data["tenant_broker_id"])
    assert is_valid_uuid(data["space_id"])
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["status"] in TOUR_STATES
    assert isinstance(data["holds_space"], bool)


def assert_deal(data: dict):
    _common_full(data)
    assert is_valid_uuid(data["listing_id"])
    assert is_valid_uuid(data["requirement_id"])
    assert is_valid_uuid(data["listing_broker_id"])
    assert is_valid_uuid(data["procuring_broker_id"])
    assert isinstance(data["is_co_broke"], bool)
    assert data["stage"] in DEAL_STAGES
    assert isinstance(data["round_count"], int) and data["round_count"] >= 0
    assert isinstance(data["total_consideration"], (int, float))
    assert isinstance(data["total_commission"], (int, float))


def assert_proposal(data: dict):
    _common_full(data)
    assert is_valid_uuid(data["deal_id"])
    assert data["from_side"] in ["LISTING", "TENANT"]
    assert data["base_rent_psf_yr"] > 0
    assert isinstance(data["term_months"], int) and data["term_months"] >= 1
    assert data["outcome"] in PROPOSAL_OUTCOMES
    assert isinstance(data["net_effective_rent_psf_yr"], (int, float))


def assert_commission_split(data: dict):
    _common_lean(data)
    assert "updated_at" not in data, "CommissionSplit must NOT carry updated_at"
    assert "version" not in data, "CommissionSplit must NOT carry version"
    assert is_valid_uuid(data["deal_id"])
    assert is_valid_uuid(data["broker_id"])
    assert data["side"] in ["LISTING", "PROCURING"]
    assert isinstance(data["amount"], (int, float))


def assert_comp(data: dict):
    _common_lean(data)
    assert "updated_at" not in data, "Comp must NOT carry updated_at"
    assert "version" not in data, "Comp must NOT carry version"
    assert is_valid_uuid(data["space_id"])
    assert is_valid_uuid(data["deal_id"])
    assert isinstance(data["market"], str) and len(data["market"]) > 0
    assert isinstance(data["effective_rent_psf_yr"], (int, float))
    assert isinstance(data["term_months"], int)
    assert is_iso8601_timestamp(data["executed_at"])


def assert_commission_conserves_total(splits: list, total_commission: float):
    """Conserved-quantity invariant: LISTING + PROCURING amounts sum to total_commission exactly."""
    total = round(sum(s["amount"] for s in splits), 2)
    assert total == round(total_commission, 2), (
        f"CommissionSplit amounts {total} must sum to total_commission {total_commission}"
    )
    for s in splits:
        assert_cost_precision(s["amount"])
