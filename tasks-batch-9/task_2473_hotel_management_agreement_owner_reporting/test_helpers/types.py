"""TypedDict shapes for every entity exposed by the hotel-management API.

Field names mirror the API contract exactly. Every entity except the
reserve-for-replacement ledger carries the four common system fields
(``id``, ``created_at``, ``updated_at``, ``version``); the ledger is
append-only and therefore carries only ``id`` and ``created_at``.
"""

from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Envelope shapes
# ---------------------------------------------------------------------------


class ResponseMeta(TypedDict, total=False):
    """The ``meta`` object present on every response."""

    api_request_id: str
    api_request_timestamp: str
    limit: int
    offset: int
    total_count: int
    has_more: bool


class ErrorData(TypedDict):
    """The ``data`` object of an error response."""

    error_id: str
    message: str


class ApiEnvelope(TypedDict, total=False):
    meta: ResponseMeta
    response_type: str
    data: Any


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


class ManagementAgreement(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    hotel_name: str
    owner_entity_name: str
    status: str
    base_fee_pct: float
    incentive_fee_pct: float
    incentive_tier2_pct: float
    incentive_tier2_threshold_cents: int
    owner_priority_cents: int
    ffe_reserve_pct: float
    centralized_services_cap_pct: float
    working_capital_floor_cents: int
    working_capital_balance_cents: int
    initial_working_capital_cents: int
    ffe_reserve_balance_cents: int
    manager_liability_accrued_cents: int
    owner_review_window_days: int
    max_revision_rounds: int
    gop_test_threshold_pct: float
    rpi_test_threshold: float
    min_benchmark_months: int
    test_periods_expected: int
    consecutive_failure_limit: int
    performance_failure_streak: int
    employee_model: str
    manager_indemnity_cap_cents: int
    cure_window_days: int
    dispute_standstill_days: int
    max_dispute_rounds: int
    funding_due_days: int
    termination_notice_days: int
    distribution_hold: bool
    termination_effective_utc: Optional[str]


class OperatingBudget(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    agreement_id: str
    supersedes_budget_id: Optional[str]
    fiscal_year: int
    status: str
    budgeted_revenue_cents: int
    budgeted_operating_expenses_cents: int
    budgeted_capital_ffe_cents: int
    budgeted_capital_brand_cents: int
    budgeted_base_fee_cents: int
    budgeted_centralized_cents: int
    budgeted_agop_cents: int
    revision_round: int
    submitted_at: Optional[str]
    submitted_by_user_id: Optional[str]
    owner_decision_deadline_utc: Optional[str]
    decided_by_user_id: Optional[str]
    carryforward_applied: bool


class VarianceRequest(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    budget_id: str
    category: str
    requested_amount_cents: int
    justification: str
    effective_baseline_cents: int
    variance_pct: float
    approval_level: str
    status: str
    requested_by_user_id: str
    decided_by_user_id: Optional[str]
    denied_by_cascade: bool


class MonthlyReportPackage(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    agreement_id: str
    fiscal_year: int
    period_month: int
    rooms_revenue_cents: int
    fnb_revenue_cents: int
    other_revenue_cents: int
    operating_expenses_cents: int
    closing_cash_available_cents: int
    gross_revenue_cents: int
    allocated_centralized_cents: int
    base_fee_cents: int
    agop_cents: int
    incentive_fee_provisional_cents: int
    reported_rpi: Optional[float]
    financial_status: str
    benchmark_status: str
    package_status: str
    due_date_utc: str
    submitted_at: Optional[str]
    submitted_late: bool
    resubmission_count: int


class MarketBenchmark(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    report_package_id: str
    hotel_revpar_cents: int
    comp_set_revpar_cents: int
    rooms_available: int
    source: str
    rpi: float
    superseded: bool


class CentralizedServiceCharge(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    report_package_id: str
    service_code: str
    allocation_basis: str
    pool_amount_cents: int
    hotel_basis_share: float
    allow_deferral: bool
    supporting_detail_provided: bool
    requested_amount_cents: int
    allocated_amount_cents: int
    deferred_amount_cents: int
    disclosure_status: str
    adjusted_amount_cents: Optional[int]


class FeeAccrual(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    report_package_id: str
    fee_type: str
    variant: str
    fiscal_year: int
    period_month: int
    amount_cents: int
    status: str
    paid_amount_cents: int


class CashDistribution(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    report_package_id: str
    available_cash_cents: int
    wc_restoration_cents: int
    base_fee_paid_cents: int
    reserve_contribution_cents: int
    owner_priority_paid_cents: int
    incentive_fee_paid_cents: int
    residual_to_owner_cents: int
    shortfall_cents: int
    status: str


class ReserveLedgerEntry(TypedDict, total=False):
    """Append-only: carries ``id`` and ``created_at`` only.

    There is deliberately no ``updated_at`` and no ``version`` key here.
    """

    id: str
    created_at: str
    agreement_id: str
    entry_type: str
    amount_cents: int
    balance_after_cents: int
    source_kind: str
    memo: str


class WorkingCapitalCall(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    agreement_id: str
    amount_cents: int
    reason: str
    status: str
    due_date_utc: str
    funded_amount_cents: int
    late_funded: bool
    auto_created: bool


class PerformanceTest(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    agreement_id: str
    fiscal_year: int
    accepted_period_count: int
    actual_agop_cents: int
    budgeted_agop_snapshot_cents: int
    budget_source_status: str
    prorated_budget_agop_cents: int
    gop_achievement_pct: float
    rpi_weighted: float
    rpi_simple_average: float
    str_month_count: int
    status: str
    cure_payment_due_cents: int
    cure_paid_cents: int
    cure_deadline_utc: Optional[str]
    streak_after_test: int


class BrandStandardDispute(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    agreement_id: str
    franchise_requirement_ref: str
    estimated_cost_cents: int
    remediation_start_utc: str
    remediation_deadline_utc: str
    status: str
    round: int
    current_cost_estimate_cents: int
    standstill_start_utc: Optional[str]
    standstill_end_utc: Optional[str]
    funding_source: Optional[str]
    funded_amount_cents: int


class EmploymentClaim(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    agreement_id: str
    position_class: str
    claim_amount_cents: int
    gross_negligence: bool
    employer_of_record: str
    owner_share_cents: int
    manager_share_cents: int
    status: str


class TrueUpSummary(TypedDict, total=False):
    """The settlement projection returned by the annual true-up endpoint.

    Not an entity: it carries no id / created_at / updated_at / version.
    """

    fiscal_year: int
    accepted_period_count: int
    annual_agop_cents: int
    final_incentive_fee_cents: int
    provisional_incentive_total_cents: int
    true_up_delta_cents: int
    true_up_accrual_id: str
    attached_report_package_id: str


class ClockState(TypedDict, total=False):
    current_utc: str
    deemed_approved_budget_count: int
    overdue_call_count: int
    lapsed_cure_count: int
    deadlocked_dispute_count: int
    terminated_agreement_count: int


PaginatedRows = List[Dict[str, Any]]

__all__ = [
    "ApiEnvelope",
    "BrandStandardDispute",
    "CashDistribution",
    "CentralizedServiceCharge",
    "ClockState",
    "EmploymentClaim",
    "ErrorData",
    "FeeAccrual",
    "ManagementAgreement",
    "MarketBenchmark",
    "MonthlyReportPackage",
    "OperatingBudget",
    "PaginatedRows",
    "PerformanceTest",
    "ReserveLedgerEntry",
    "ResponseMeta",
    "TrueUpSummary",
    "VarianceRequest",
    "WorkingCapitalCall",
]
