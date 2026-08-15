"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
import pytest
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)

from .types import (
    FiscalYearStatus, EnrollmentProjectionStatus, BudgetVersionStatus,
    BudgetLineStatus, StaffingAllocationStatus, PositionStatus,
    RevenueEstimateStatus, EavBasis, PublicHearingStatus, ElectionStatus,
    ElectionType, BondProposalStatus, BondProjectStatus, BallotMeasureStatus,
    PublicationType, DistrictPublicationStatus, BondSaleStatus, ReviewStatus,
    PaymentStatus, CapitalPlanAmendmentStatus, GradeBand, FundCode,
)


def _assert_common_fields(data: dict):
    """Every resource carries id + created_at; all except district
    publications additionally carry updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def assert_fiscal_year(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert data["status"] in [s.value for s in FiscalYearStatus]
    for f in ("eav_current", "eav_prior", "prior_year_extension",
                  "outstanding_debt_principal", "fte_ceiling",
                  "authorized_fte_total"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"
    assert isinstance(data["open_position_count"], int)


def assert_enrollment_projection(data: dict):
    _assert_common_fields(data)
    assert data["grade_band"] in [b.value for b in GradeBand]
    assert isinstance(data["projected_pupils"], int) and data["projected_pupils"] >= 0
    assert isinstance(data["weighted_pupils_projected"], int)
    assert data["status"] in [s.value for s in EnrollmentProjectionStatus]
    if data["status"] == EnrollmentProjectionStatus.PROVISIONAL.value:
        assert data.get("actual_pupils") is None
        assert data.get("weighted_pupils_certified") is None


def assert_budget_version(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["version_label"], str)
    assert isinstance(data["total_appropriations"], (int, float))
    assert data["status"] in [s.value for s in BudgetVersionStatus]


def assert_budget_line(data: dict):
    _assert_common_fields(data)
    assert data["fund_code"] in [f.value for f in FundCode]
    assert isinstance(data["appropriation_amount"], (int, float))
    assert data["status"] in [s.value for s in BudgetLineStatus]


def assert_staffing_allocation(data: dict):
    _assert_common_fields(data)
    assert data["grade_band"] in [b.value for b in GradeBand]
    for f in ("required_fte", "allocated_fte", "positions_fte_total",
              "cost_estimate_projected", "cost_estimate_actual"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"
    assert data["status"] in [s.value for s in StaffingAllocationStatus]


def assert_position(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["fte"] in (0.5, 1.0)
    assert isinstance(data["base_salary"], (int, float)) and data["base_salary"] > 0
    assert data["status"] in [s.value for s in PositionStatus]
    if data["status"] != PositionStatus.FILLED.value:
        assert data.get("incumbent_salary") is None


def assert_revenue_estimate(data: dict):
    _assert_common_fields(data)
    for f in ("operating_levy_request", "debt_service_levy", "other_revenue",
              "cpi_rate", "capped_operating_levy", "total_levy", "state_aid",
              "operating_rate", "debt_service_rate", "total_tax_rate",
              "total_revenue"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"
    assert data["eav_basis"] in [b.value for b in EavBasis]
    assert data["status"] in [s.value for s in RevenueEstimateStatus]


def assert_public_hearing(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["venue"], str) and len(data["venue"]) > 0
    assert isinstance(data["hearing_date"], str)
    assert isinstance(data["notice_publication_date"], str)
    assert data["status"] in [s.value for s in PublicHearingStatus]


def assert_election(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["election_date"], str)
    assert data["election_type"] in [t.value for t in ElectionType]
    assert data["status"] in [s.value for s in ElectionStatus]


def assert_bond_proposal(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["question_title"], str)
    for f in ("total_amount", "remaining_authorization", "available_proceeds"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"
    assert data["status"] in [s.value for s in BondProposalStatus]


def assert_bond_project(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["site_code"], str)
    for f in ("estimated_cost", "authorized_amount", "spent_amount"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"
    assert isinstance(data["priority_rank"], int)
    assert data["status"] in [s.value for s in BondProjectStatus]


def assert_ballot_measure(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["ballot_language"], str)
    assert isinstance(data["word_count"], int)
    assert isinstance(data["drafted_by_user_id"], str)
    assert data["status"] in [s.value for s in BallotMeasureStatus]


def assert_district_publication(data: dict):
    """Append-only record: id + created_at only; updated_at and version are
    absent (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 UTC timestamp"
    assert "updated_at" not in data, "publications carry no updated_at"
    assert "version" not in data, "publications carry no version"
    assert data["publication_type"] in [t.value for t in PublicationType]
    assert data["status"] in [s.value for s in DistrictPublicationStatus]


def assert_bond_sale(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["series_label"], str)
    for f in ("par_amount", "premium", "issuance_costs", "net_proceeds"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"
    assert data["status"] in [s.value for s in BondSaleStatus]


def assert_project_expenditure(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["vendor_name"], str)
    for f in ("amount", "retainage_amount", "disbursed_amount"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"
    assert data["review_status"] in [s.value for s in ReviewStatus]
    assert data["payment_status"] in [s.value for s in PaymentStatus]


def assert_capital_plan_amendment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["reason"], str)
    assert isinstance(data["adjustments"], list)
    assert data["status"] in [s.value for s in CapitalPlanAmendmentStatus]


# ─── Money / rate comparisons ────────────────────────────────────────────────

def assert_money(actual, expected, label="amount"):
    """Money is decimal, round_half_up to 2dp (PRD §2.7); compare within
    half a cent."""
    assert actual == pytest.approx(expected, abs=0.005), (
        f"{label}: expected {expected}, got {actual}")


def assert_rate(actual, expected, label="rate"):
    """Tax rates are round_half_up to 4dp (PRD §2.7)."""
    assert actual == pytest.approx(expected, abs=0.00005), (
        f"{label}: expected {expected}, got {actual}")
