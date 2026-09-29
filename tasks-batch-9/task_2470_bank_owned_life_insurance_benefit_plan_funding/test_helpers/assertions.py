"""Entity assertions and domain invariant checkers."""
import pytest
from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    ALLOCATION_BPS_TOTAL,
    FUNDED_MIN_BPS,
    UNDERFUNDED_MIN_BPS,
)


def _assert_identity(data: dict) -> None:
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"


def assert_mutable_common_fields(data: dict) -> None:
    """A mutable resource carries id, created_at, updated_at and version."""
    _assert_identity(data)
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version starts at 1, got {data['version']}"


def assert_immutable_common_fields(data: dict) -> None:
    """An immutable record carries only id and created_at — no updated_at, no version."""
    _assert_identity(data)
    assert "updated_at" not in data, "an immutable record has no updated_at field"
    assert "version" not in data, "an immutable record has no version field at all"


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------
def assert_carrier(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["naic_code"], str) and data["naic_code"]
    assert data["am_best_rating"] in [
        "A_PLUS_PLUS",
        "A_PLUS",
        "A",
        "A_MINUS",
        "B_PLUS_PLUS",
        "B_PLUS",
        "B",
    ], f"unexpected am_best_rating {data['am_best_rating']!r}"
    assert data["statutory_surplus_usd"] > 0, "statutory_surplus_usd must be positive"
    assert isinstance(data["domicile_state"], str) and data["domicile_state"]
    assert data["status"] in [
        "PENDING_DILIGENCE",
        "AUTHORIZED",
        "RESTRICTED",
        "SUSPENDED",
        "TERMINATED",
    ], f"unexpected carrier status {data['status']!r}"
    assert isinstance(data["watch_list_flag"], bool)
    for money in (
        "reserved_premium_usd",
        "in_force_premium_usd",
        "in_force_cash_value_usd",
    ):
        assert data[money] >= 0, f"{money} must not be negative"
        assert_cost_precision(data[money])
    assert isinstance(data["concentration_bps"], int)
    assert isinstance(data["regulatory_notice_count"], int)


def assert_product_type(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert data["account_type"] in ["GENERAL", "SEPARATE", "HYBRID"]
    assert data["mec_status"] in ["MEC", "NON_MEC"]
    assert data["status"] in ["OPEN", "ON_WATCH", "CLOSED_TO_NEW"]
    assert isinstance(data["disclosed_me_charge_bps"], int)
    assert isinstance(data["guaranteed_min_crediting_bps"], int)
    assert isinstance(data["consecutive_low_yield_count"], int)
    assert isinstance(data["latest_me_charge_bps"], int)
    assert isinstance(data["latest_me_drift_bps"], int)


def assert_diligence_review(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert isinstance(data["review_year"], int)
    assert data["status"] in [
        "DRAFT",
        "UNDER_REVIEW",
        "INFO_REQUESTED",
        "APPROVED",
        "DECLINED",
    ]
    assert isinstance(data["info_request_count"], int)


def assert_capital_position(data: dict) -> None:
    assert_immutable_common_fields(data)
    assert data["tier1_capital_usd"] > 0
    assert data["total_assets_usd"] > 0
    assert_cost_precision(data["tier1_capital_usd"])


def assert_employee(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert data["annual_salary_usd"] > 0
    assert isinstance(data["officer_flag"], bool)
    assert data["insurable_interest_status"] in ["NOT_ESTABLISHED", "ESTABLISHED"]
    assert data["employment_status"] in ["ACTIVE", "TERMINATED", "DECEASED"]


def assert_consent_record(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert data["status"] in ["DRAFT", "EXECUTED", "REVOKED", "EXPIRED"]


def assert_purchase_request(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert data["status"] in [
        "DRAFT",
        "SUBMITTED",
        "DILIGENCE_CLEARED",
        "CAPACITY_RESERVED",
        "NOTICE_FILED",
        "CONCURRENCE_PENDING",
        "APPROVED",
        "ISSUED",
        "REJECTED",
        "WITHDRAWN",
    ]
    assert data["single_premium_usd"] > 0
    assert data["face_amount_usd"] > 0
    assert isinstance(data["notice_required"], bool)
    assert data["reserved_premium_usd"] >= 0
    assert_cost_precision(data["reserved_premium_usd"])


def assert_policy(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert data["status"] in [
        "IN_FORCE",
        "PENDING_EXCHANGE",
        "CLAIM_PENDING",
        "EXCHANGED",
        "SURRENDERED",
        "PAID_OUT",
    ]
    assert data["policy_year"] >= 1
    for money in (
        "single_premium_usd",
        "face_amount_usd",
        "cost_basis_usd",
        "cash_surrender_value_usd",
    ):
        assert data[money] >= 0, f"{money} must not be negative"
        assert_cost_precision(data[money])


def assert_policy_valuation(data: dict) -> None:
    assert_immutable_common_fields(data)
    assert data["credited_interest_usd"] >= 0
    assert data["mortality_expense_charge_usd"] >= 0
    assert isinstance(data["net_yield_bps"], int)
    assert isinstance(data["me_charge_bps"], int)
    assert isinstance(data["me_drift_bps"], int)
    assert_cost_precision(data["cash_value_usd"])


def assert_nqdc_plan(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert data["plan_type"] in ["SERP", "DEFERRED_BONUS", "DIRECTOR_FEE"]
    assert data["status"] in ["ACTIVE", "FROZEN", "TERMINATED"]
    assert data["discount_rate_bps"] > 0
    assert_funding_posture_consistent(data["funded_ratio_bps"], data["funding_posture"])


def assert_nqdc_liability(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert data["status"] in ["ACTIVE", "SETTLED"]
    assert data["accrued_to_date_usd"] >= 0
    assert data["projected_benefit_usd"] > 0
    assert data["years_to_payout"] >= 0
    assert_cost_precision(data["discounted_benefit_usd"])


def assert_death_claim(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert data["adjudication_status"] in [
        "FILED",
        "UNDER_ADJUDICATION",
        "APPROVED",
        "DENIED",
        "VOIDED",
    ]
    assert data["distribution_status"] in ["NOT_STARTED", "ALLOCATED", "DISTRIBUTED"]
    assert 0 <= data["allocated_bps_total"] <= ALLOCATION_BPS_TOTAL, (
        "allocated_bps_total may never exceed "
        f"{ALLOCATION_BPS_TOTAL}, got {data['allocated_bps_total']}"
    )
    assert data["terminal_dividend_usd"] >= 0


def assert_beneficiary_allocation(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert data["relationship"] in ["SPOUSE", "CHILD", "TRUST", "ESTATE"]
    assert data["status"] in ["ACTIVE", "VOIDED"]
    assert 1 <= data["allocation_pct_bps"] <= ALLOCATION_BPS_TOTAL
    assert data["gross_amount_usd"] >= 0
    assert_cost_precision(data["gross_amount_usd"])


def assert_exchange_analysis(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert data["disposition_type"] in [
        "FULL_SURRENDER",
        "PARTIAL_SURRENDER",
        "EXCHANGE_1035",
    ]
    assert data["cost_recovery_method"] in ["FIFO_BASIS_FIRST", "LIFO_INCOME_FIRST"]
    assert data["status"] in [
        "DRAFT",
        "REVIEWED",
        "COMMITTED",
        "EXECUTED",
        "ABANDONED",
        "REJECTED",
    ]
    assert data["taxable_gain_usd"] >= 0
    for money in ("taxable_gain_usd", "surrender_charge_usd", "tax_liability_usd", "net_proceeds_usd"):
        assert_cost_precision(data[money])


def assert_risk_assessment(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert data["status"] in [
        "COMPILED",
        "BOARD_SUBMITTED",
        "BOARD_ACCEPTED",
        "RETURNED",
    ]
    assert data["risk_rating"] in ["LOW", "MODERATE", "HIGH", "SEVERE"]
    for count in (
        "restricted_carrier_count",
        "watch_list_carrier_count",
        "on_watch_product_count",
        "closed_product_count",
        "critical_plan_count",
        "underfunded_plan_count",
        "risk_points",
    ):
        assert isinstance(data[count], int), f"{count} must be a whole number"
        assert data[count] >= 0


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------
def assert_funding_posture_consistent(funded_ratio_bps: int, funding_posture: str) -> None:
    """FUNDED at or above 10000 bps, UNDERFUNDED from 8000, CRITICAL below 8000."""
    if funded_ratio_bps >= FUNDED_MIN_BPS:
        expected = "FUNDED"
    elif funded_ratio_bps >= UNDERFUNDED_MIN_BPS:
        expected = "UNDERFUNDED"
    else:
        expected = "CRITICAL"
    assert funding_posture == expected, (
        f"funded_ratio_bps {funded_ratio_bps} implies {expected}, "
        f"got {funding_posture}"
    )


def assert_death_benefit_conservation(claim: dict, allocations: list) -> None:
    """total_death_benefit_usd == bank_portion_usd + sum of ACTIVE gross amounts."""
    active_total = sum(
        a["gross_amount_usd"] for a in allocations if a["status"] == "ACTIVE"
    )
    assert claim["total_death_benefit_usd"] == pytest.approx(
        claim["bank_portion_usd"] + active_total, abs=0.001
    ), (
        f"conservation broken: total {claim['total_death_benefit_usd']} != "
        f"bank {claim['bank_portion_usd']} + allocations {active_total}"
    )


def assert_capacity_projection_shape(projection: dict) -> None:
    """The projection reports the complete working of the capacity calculation."""
    for field in (
        "tier1_capital_usd",
        "base_limit_usd",
        "committed_usd",
        "prospective_usd",
        "base_ratio_bps",
        "effective_limit_pct",
        "aggregate_limit_usd",
        "headroom_usd",
        "carrier_concentration_bps",
        "single_carrier_limit_bps",
    ):
        assert field in projection, f"capacity projection must report {field}"


def assert_funding_summary_shape(summary: dict) -> None:
    """The funding summary reports both bases plus the selected-basis figures."""
    for field in (
        "basis",
        "accrual_liability_usd",
        "pbo_liability_usd",
        "matched_cash_value_usd",
        "basis_liability_usd",
        "funded_ratio_bps",
        "funding_posture",
        "participant_count",
    ):
        assert field in summary, f"funding summary must report {field}"
