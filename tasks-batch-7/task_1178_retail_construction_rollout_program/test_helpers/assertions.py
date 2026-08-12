"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    BidPackageStatus,
    BidStatus,
    ChangeOrderStatus,
    ChangeOrderTier,
    ContractorStatus,
    DrawingSetStatus,
    MarketStatus,
    PermitStatus,
    ProgramBudgetPosture,
    ProtectionPosture,
    PunchItemStatus,
    ReadinessPosture,
    RolloutProgramStatus,
    SiteBudgetPosture,
    SiteStatus,
    TurnoverStatus,
    VendorMobilizationStatus,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer counter"
    )


def assert_rollout_program(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in RolloutProgramStatus]
    assert data["budget_posture"] in [p.value for p in ProgramBudgetPosture]
    for field in ("total_budget_cents", "contingency_pool_cents", "committed_cents",
                  "actuals_cents", "contingency_reserved_cents", "contingency_free_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_market(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in MarketStatus]
    assert isinstance(data["max_concurrent_vendor_crews"], int)


def assert_municipality_profile(data: dict):
    _assert_common_fields(data)
    for field in ("statutory_review_days", "observed_avg_review_days",
                  "permit_validity_days", "fee_base_cents", "fee_per_sqft_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_site(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in SiteStatus]
    assert data["budget_posture"] in [p.value for p in SiteBudgetPosture]
    assert data["readiness_posture"] in [p.value for p in ReadinessPosture]
    for field in ("square_footage", "phase_wave", "budget_allocation_cents",
                  "base_contract_cents", "approved_co_cents", "proposed_co_cents",
                  "committed_cents", "variance_ratio_final_bp",
                  "variance_ratio_provisional_bp", "actuals_cents",
                  "permit_fees_paid_cents", "punch_open_critical_count",
                  "punch_open_total_count"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_drawing_set(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in DrawingSetStatus]
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert isinstance(data["review_round"], int) and data["review_round"] >= 1


def assert_permit(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in PermitStatus]
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert isinstance(data["fee_cents"], int)


def assert_contractor(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in ContractorStatus]


def assert_bid_package(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in BidPackageStatus]
    assert data["evaluation_mode"] in ("LOWEST_PRICE", "BEST_VALUE")


def assert_bid(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in BidStatus]
    assert isinstance(data["is_responsive"], bool)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["duration_days"], int)
    assert 0 <= data["tech_score"] <= 100


def assert_vendor_mobilization(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in VendorMobilizationStatus]
    assert data["vendor_type"] in ("FIXTURE", "IT", "SIGNAGE")


def assert_change_order(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in ChangeOrderStatus]
    assert data["tier"] in [t.value for t in ChangeOrderTier]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["proposed_by_user_id"], str) and data["proposed_by_user_id"]


def assert_punch_item(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in PunchItemStatus]
    assert data["severity"] in ("CRITICAL", "MAJOR", "MINOR")
    assert isinstance(data["reopen_count"], int) and data["reopen_count"] >= 0


def assert_turnover(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in TurnoverStatus]


def assert_opening_commitment(data: dict):
    _assert_common_fields(data)
    assert data["protection_posture"] in [p.value for p in ProtectionPosture]
    assert isinstance(data["slip_days"], int) and data["slip_days"] >= 0


def assert_site_ledger_invariants(site: dict):
    """Site budget buckets always satisfy committed = base + approved."""
    assert site["committed_cents"] == site["base_contract_cents"] + site["approved_co_cents"], (
        f"committed_cents {site['committed_cents']} != base {site['base_contract_cents']} "
        f"+ approved {site['approved_co_cents']}"
    )
    if site["base_contract_cents"] == 0:
        assert site["variance_ratio_final_bp"] == 0
        assert site["variance_ratio_provisional_bp"] == 0
