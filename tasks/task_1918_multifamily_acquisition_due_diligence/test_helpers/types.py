"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1) — every role is an opaque operator identity.
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ACQUISITIONS_ANALYST = "AcquisitionsAnalyst"
    UNDERWRITING_MANAGER = "UnderwritingManager"
    PROPERTY_OPERATIONS_LEAD = "PropertyOperationsLead"
    HR_PARTNER = "HRPartner"
    VENDOR_MANAGER = "VendorManager"
    ESCROW_OFFICER = "EscrowOfficer"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------
class AcquisitionStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_DILIGENCE = "IN_DILIGENCE"
    DILIGENCE_COMPLETE = "DILIGENCE_COMPLETE"
    PRE_CLOSING = "PRE_CLOSING"
    CLOSED = "CLOSED"
    SETTLED = "SETTLED"
    TERMINATED = "TERMINATED"


class ReadinessPosture(str, Enum):
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    BLOCKED = "BLOCKED"


class UnitStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CLEARING = "CLEARING"
    VERIFIED = "VERIFIED"
    EXCLUDED = "EXCLUDED"


class LeaseFileStatus(str, Enum):
    UPLOADED = "UPLOADED"
    AUDITED = "AUDITED"
    DISCREPANCY_FLAGGED = "DISCREPANCY_FLAGGED"
    RESOLVED = "RESOLVED"
    WAIVED = "WAIVED"
    SUPERSEDED = "SUPERSEDED"


class AuditResult(str, Enum):
    PENDING = "PENDING"
    MATCH = "MATCH"
    OVERSTATED = "OVERSTATED"
    UNDERSTATED = "UNDERSTATED"


class RentRollVerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    MISMATCHED = "MISMATCHED"


class ConcessionStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    QA_ACCEPTED = "QA_ACCEPTED"
    QA_REJECTED = "QA_REJECTED"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    EXCLUDED = "EXCLUDED"


class TaxProjectionStatus(str, Enum):
    DRAFT = "DRAFT"
    COMPUTED = "COMPUTED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class DepositStatus(str, Enum):
    RECORDED = "RECORDED"
    RECONCILED = "RECONCILED"
    DISPUTED = "DISPUTED"
    ESCROW_QUEUED = "ESCROW_QUEUED"
    TRANSFERRED = "TRANSFERRED"


class EmployeeDecisionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NOTIFIED = "NOTIFIED"
    EFFECTIVE = "EFFECTIVE"
    RESCINDED = "RESCINDED"


class ServiceContractStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ASSUMED = "ASSUMED"
    NOTICE_SENT = "NOTICE_SENT"
    CANCELLED_EFFECTIVE = "CANCELLED_EFFECTIVE"
    RENEWED = "RENEWED"
    AUTO_RENEWED = "AUTO_RENEWED"
    TRANSFERRED = "TRANSFERRED"


class InsurancePolicyStatus(str, Enum):
    DOCUMENTED = "DOCUMENTED"
    LOSS_RUNS_REVIEWED = "LOSS_RUNS_REVIEWED"
    ASSUMED = "ASSUMED"
    TRANSFERRED = "TRANSFERRED"
    EXCLUDED = "EXCLUDED"


class RiskTier(str, Enum):
    LOW = "LOW"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    REVIEWED = "REVIEWED"
    APPROVED = "APPROVED"
    SETTLED = "SETTLED"
    SUPERSEDED = "SUPERSEDED"


class StatementType(str, Enum):
    DRAFT_CLOSING = "DRAFT_CLOSING"
    FINAL_CLOSING = "FINAL_CLOSING"
    POST_CLOSING_TRUEUP = "POST_CLOSING_TRUEUP"


class DayCountMethod(str, Enum):
    ACTUAL_365 = "ACTUAL_365"
    BANKERS_30_360 = "BANKERS_30_360"


class LineType(str, Enum):
    RENT = "RENT"
    TAX = "TAX"
    PREPAID_EXPENSE = "PREPAID_EXPENSE"
    DEPOSIT_TRANSFER = "DEPOSIT_TRANSFER"
    PAYROLL = "PAYROLL"
    ADJUSTMENT = "ADJUSTMENT"


class LineDirection(str, Enum):
    CREDIT_BUYER = "CREDIT_BUYER"
    CREDIT_SELLER = "CREDIT_SELLER"


class AdjustmentStatus(str, Enum):
    ASSERTED = "ASSERTED"
    EVIDENCED = "EVIDENCED"
    ACCEPTED = "ACCEPTED"
    DISPUTED = "DISPUTED"
    RESOLVED = "RESOLVED"
    APPLIED = "APPLIED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# common_fields entities carry id/created_at/updated_at/version (PRD §2.5);
# the rent roll entry and the proration line carry only id and created_at.
# ---------------------------------------------------------------------------
class Acquisition(TypedDict, total=False):
    id: str
    property_name: str
    address: str
    agreed_purchase_price_cents: int
    earnest_money_cents: int
    closing_date: str
    diligence_deadline: str
    true_up_window_days: int
    assessment_ratio: float
    millage_rate: float
    prior_year_tax_cents: int
    maintenance_estimate_basis: str
    interest_accrual_method: str
    status: str
    readiness_posture: str
    deferred_maintenance_total_cents: int
    rent_roll_variance_cents: int
    deposit_variance_cents: int
    payroll_accrual_cents: int
    net_proration_cents: int
    closing_executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict, total=False):
    id: str
    acquisition_id: str
    unit_number: str
    floor_plan: str
    sqft: int
    market_rent_cents: int
    status: str
    lease_audited: bool
    walk_accepted: bool
    deposit_reconciled: bool
    created_at: str
    updated_at: str
    version: int


class LeaseFile(TypedDict, total=False):
    id: str
    unit_id: str
    resident_name: str
    lease_start_date: str
    lease_end_date: str
    contract_rent_cents: int
    term_months: int
    deposit_amount_cents: int
    supersedes_lease_id: Optional[str]
    status: str
    variance_cents: Optional[int]
    audit_result: str
    net_effective_rent_cents: Optional[int]
    waived_variance_cents: int
    created_at: str
    updated_at: str
    version: int


class RentRollEntry(TypedDict, total=False):
    # Lean record: id + created_at only; no updated_at, no version (PRD §2.5).
    id: str
    unit_id: str
    reported_resident_name: str
    reported_rent_cents: int
    reported_concession_cents: int
    reported_deposit_cents: int
    move_in_date: str
    verification_status: str
    created_at: str


class Concession(TypedDict, total=False):
    id: str
    lease_file_id: str
    concession_type: str
    value_cents: int
    coverage_start_date: str
    coverage_end_date: str
    verification_status: str
    verified_value_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class UnitWalkInspection(TypedDict, total=False):
    id: str
    unit_id: str
    inspector_ref: str
    walk_start: str
    walk_end: str
    condition_rating: Optional[int]
    no_findings_declared: Optional[bool]
    completed_by_user_id: Optional[str]
    reschedule_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DeficiencyFinding(TypedDict, total=False):
    id: str
    inspection_id: str
    category: str
    severity: int
    seller_estimate_cents: int
    inspector_estimate_cents: int
    verified_cost_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class UtilityExpenseRecord(TypedDict, total=False):
    id: str
    acquisition_id: str
    period_month: str
    category: str
    amount_cents: int
    source: str
    is_outlier: bool
    normalized_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class TaxReassessmentProjection(TypedDict, total=False):
    id: str
    acquisition_id: str
    method: str
    cap_rate: Optional[float]
    noi_t12_cents: Optional[int]
    status: str
    projected_value_cents: Optional[int]
    projected_assessed_value_cents: Optional[int]
    projected_annual_tax_cents: Optional[int]
    delta_vs_prior_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class SecurityDepositLedgerEntry(TypedDict, total=False):
    id: str
    lease_file_id: str
    seller_stated_amount_cents: int
    interest_required: bool
    annual_interest_rate: float
    verified_amount_cents: Optional[int]
    accrued_interest_cents: Optional[int]
    variance_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class EmployeeDecision(TypedDict, total=False):
    id: str
    acquisition_id: str
    employee_ref: str
    position: str
    hire_date: str
    annual_salary_cents: int
    accrued_pto_hours: float
    decision: str
    notice_date: str
    effective_date: str
    required_notice_days: int
    proposed_by_user_id: str
    approved_by_user_id: Optional[str]
    severance_cents: Optional[int]
    pto_payout_cents: Optional[int]
    assumed_pto_liability_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceContract(TypedDict, total=False):
    id: str
    acquisition_id: str
    vendor_name: str
    service_type: str
    monthly_cost_cents: int
    term_end_date: str
    auto_renew: bool
    cancellation_notice_days: int
    cancellation_penalty_cents: int
    prepaid_through_date: Optional[str]
    decision_deadline: str
    cancellation_effective_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict, total=False):
    id: str
    acquisition_id: str
    policy_type: str
    carrier_name: str
    annual_premium_cents: int
    expiration_date: str
    prepaid_through_date: str
    loss_run_total_cents: int
    open_claims_count: int
    loss_ratio: Optional[float]
    risk_tier: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProrationStatement(TypedDict, total=False):
    id: str
    acquisition_id: str
    statement_type: str
    day_count_method: str
    status: str
    created_by_user_id: str
    reviewed_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    total_buyer_credits_cents: int
    total_seller_credits_cents: int
    net_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class ProrationLine(TypedDict, total=False):
    # Lean record: id + created_at only; no updated_at, no version (PRD §2.5).
    id: str
    statement_id: str
    line_type: str
    direction: str
    amount_cents: int
    source_kind: str
    source_ref_type: Optional[str]
    source_ref_id: Optional[str]
    memo: Optional[str]
    created_at: str


class PostClosingAdjustment(TypedDict, total=False):
    id: str
    acquisition_id: str
    adjustment_type: str
    amount_cents: int
    direction: str
    evidence_note: Optional[str]
    pre_closing_arrears_cents: Optional[int]
    collections_applied_cents: Optional[int]
    resolved_amount_cents: Optional[int]
    asserted_date: str
    status: str
    created_at: str
    updated_at: str
    version: int
