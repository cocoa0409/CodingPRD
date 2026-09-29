"""Domain types for the Warranty Reserve & Product Liability Accrual API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    WARRANTY_ANALYST = "WarrantyAnalyst"
    RESERVE_CONTROLLER = "ReserveController"
    QUALITY_ENGINEER = "QualityEngineer"
    ACTUARY = "Actuary"
    SUPPLIER_REP = "SupplierRep"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class AccrualPeriodStatus(str, Enum):
    OPEN = "OPEN"
    ANALYSIS_LOCKED = "ANALYSIS_LOCKED"
    ACTUARIAL_REVIEW = "ACTUARIAL_REVIEW"
    CLOSED = "CLOSED"


class HistoryMaturityStatus(str, Enum):
    LIMITED = "LIMITED"
    MATURE = "MATURE"


class ReservePosture(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    CONSTRAINED = "CONSTRAINED"


class ExposureStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class FailureModeSeverity(str, Enum):
    COSMETIC = "COSMETIC"
    FUNCTIONAL = "FUNCTIONAL"
    SAFETY = "SAFETY"


class WarrantyAccrualStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    POSTED = "POSTED"
    SUPERSEDED = "SUPERSEDED"


class AccrualMethod(str, Enum):
    HISTORICAL_RATE = "HISTORICAL_RATE"
    ANALOG_BLEND = "ANALOG_BLEND"


class AdequacyStatus(str, Enum):
    REDUNDANT = "REDUNDANT"
    SUFFICIENT = "SUFFICIENT"
    DEFICIENT = "DEFICIENT"


class FieldActionType(str, Enum):
    SERVICE_CAMPAIGN = "SERVICE_CAMPAIGN"
    SAFETY_RECALL = "SAFETY_RECALL"
    FIELD_BULLETIN = "FIELD_BULLETIN"


class ApprovalState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ExecutionState(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class RemedyClass(str, Enum):
    PERMANENT_REPAIR = "PERMANENT_REPAIR"
    INTERIM_REPAIR = "INTERIM_REPAIR"
    PART_REPLACEMENT = "PART_REPLACEMENT"
    BUYBACK = "BUYBACK"


class ServiceContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class RecognitionMethod(str, Enum):
    STRAIGHT_LINE = "STRAIGHT_LINE"
    CLAIMS_PATTERN = "CLAIMS_PATTERN"


class CreditRating(str, Enum):
    AAA = "AAA"
    BBB = "BBB"
    CCC = "CCC"
    D = "D"


class CollectabilityRating(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    IMPAIRED = "IMPAIRED"


class SupplierRecoveryStatus(str, Enum):
    DRAFT = "DRAFT"
    ASSERTED = "ASSERTED"
    NEGOTIATION = "NEGOTIATION"
    SETTLED = "SETTLED"
    WRITTEN_OFF = "WRITTEN_OFF"


class ValuationVariant(str, Enum):
    EXPECTED_VALUE = "EXPECTED_VALUE"
    CONTRACTUAL_FLOOR = "CONTRACTUAL_FLOOR"


class LiabilityReserveStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTUARY_REVIEWED = "ACTUARY_REVIEWED"
    BOOKED = "BOOKED"


# ---------------------------------------------------------------------------
# Entities carrying the full system-managed set (id, created_at, updated_at,
# version) — PRD §2.4.
# ---------------------------------------------------------------------------
class AccrualPeriod(TypedDict):
    id: str
    period_code: str
    period_start_date: str
    period_end_date: str
    status: str
    locked_at: Optional[str]
    closed_at: Optional[str]
    reopen_count: int
    rollforward_generated: bool
    significant_exposure_count: int
    requires_significant_exposure_disclosure: bool
    created_at: str
    updated_at: str
    version: int


class ProductFamily(TypedDict):
    id: str
    family_code: str
    name: str
    launch_date: str
    base_warranty_months: int
    standard_cost_per_claim_cents: int
    engineering_estimate_rate_ppm: Optional[int]
    analog_family_id: Optional[str]
    reserve_cap_cents: int
    observed_history_months: int
    observed_exposure_units: int
    units_sold_lifetime: int
    history_maturity_status: str
    warranty_reserve_balance_cents: int
    reserve_posture: str
    created_at: str
    updated_at: str
    version: int


class ProductVintage(TypedDict):
    id: str
    family_id: str
    vintage_code: str
    units_shipped: int
    ship_period_code: str
    warranty_expiry_date: str
    exposure_status: str
    created_at: str
    updated_at: str
    version: int


class FailureMode(TypedDict):
    id: str
    family_id: str
    mode_code: str
    description: str
    severity: str
    cost_per_claim_cents: int
    supplier_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WarrantyAccrual(TypedDict):
    id: str
    period_id: str
    vintage_id: str
    method: str
    elapsed_exposure_bps: int
    status: str
    revision_index: int
    expected_claim_rate_ppm: int
    cost_per_claim_basis_cents: int
    paid_to_date_cents: int
    accrued_amount_cents: int
    proposed_by_user_id: Optional[str]
    posted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdequacyReview(TypedDict):
    id: str
    period_id: str
    family_id: str
    expected_to_date_cents: int
    actual_paid_cents: int
    ave_ratio_bps: int
    trend_adjustment_bps: int
    remaining_base_cents: int
    adjusted_remaining_cents: int
    recommended_true_up_cents: int
    adequacy_status: str
    true_up_applied: bool
    applied_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FieldAction(TypedDict):
    id: str
    family_id: str
    action_code: str
    action_type: str
    is_safety_recall: bool
    affected_build_start_date: str
    affected_build_end_date: str
    affected_unit_count: int
    regulatory_notice_filed: bool
    selected_remedy_option_id: Optional[str]
    specific_accrual_cents: int
    executed_cost_cents: int
    approval_state: str
    execution_state: str
    approved_period_id: Optional[str]
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemedyOption(TypedDict):
    id: str
    field_action_id: str
    option_code: str
    remedy_class: str
    parts_cost_cents: int
    labor_hours_centi: int
    admin_cost_cents: int
    expected_take_rate_bps: int
    is_engineering_approved: bool
    per_unit_expected_cents: int
    created_at: str
    updated_at: str
    version: int


class ServiceContract(TypedDict):
    id: str
    family_id: str
    contract_number: str
    sold_date: str
    term_months: int
    total_contract_price_cents: int
    recognition_method: str
    status: str
    months_elapsed: int
    recognized_revenue_cents: int
    deferred_revenue_cents: int
    refunded_revenue_cents: int
    cancelled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict):
    id: str
    supplier_code: str
    name: str
    credit_rating: str
    annual_purchase_volume_cents: int
    contractual_recovery_cap_bps: int
    gross_asserted_recovery_cents: int
    open_recovery_asset_cents: int
    realized_recovery_cents: int
    written_off_recovery_cents: int
    closed_recovery_count: int
    realization_bps: int
    collectability_rating: str
    created_at: str
    updated_at: str
    version: int


class SupplierRecovery(TypedDict):
    id: str
    supplier_id: str
    failure_mode_id: str
    field_action_id: Optional[str]
    asserted_amount_cents: int
    settled_amount_cents: Optional[int]
    valuation_variant: str
    collectability_rating_at_valuation: str
    recognized_recovery_cents: int
    status: str
    assert_count: int
    supplier_response_note: Optional[str]
    settled_period_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LiabilityReserve(TypedDict):
    id: str
    period_id: str
    family_id: str
    reported_claim_count: int
    asserted_case_reserve_cents: int
    reporting_lag_months: int
    severity_trend_bps: int
    avg_case_severity_cents: int
    lag_factor_bps: int
    ibnr_claim_count: int
    ibnr_reserve_cents: int
    total_liability_reserve_cents: int
    status: str
    return_count: int
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Narrower resources: PRD §2.4 states a claim observation and a reserve
# rollforward snapshot carry `id` and `created_at` only — neither `updated_at`
# nor `version` is present.
# ---------------------------------------------------------------------------
class ClaimObservation(TypedDict):
    id: str
    vintage_id: str
    failure_mode_id: str
    observation_period_code: str
    months_in_service_from: int
    months_in_service_to: int
    claim_count: int
    paid_cost_cents: int
    created_at: str


class ReserveRollforward(TypedDict):
    id: str
    period_id: str
    beginning_balance_cents: int
    accruals_cents: int
    campaign_accruals_cents: int
    changes_in_estimate_cents: int
    claims_paid_cents: int
    supplier_recoveries_cents: int
    ending_balance_cents: int
    significant_exposure_count: int
    generated_by_user_id: str
    created_at: str
