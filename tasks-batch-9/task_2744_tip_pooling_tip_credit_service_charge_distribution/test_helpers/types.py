"""Domain types for the tip pooling, tip credit and service charge API.

Entity TypedDicts, status enums and the role enum. Append-only ledger rows
carry only ``id`` and ``created_at``; every other entity carries the common
audit quartet ``id`` / ``created_at`` / ``updated_at`` / ``version``.
"""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PAYROLL_ADMIN = "PayrollAdmin"
    PAYROLL_PREPARER = "PayrollPreparer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    SHIFT_MANAGER = "ShiftManager"
    EMPLOYEE = "Employee"


# ---------------------------------------------------------------------------
# Enumerated domains
# ---------------------------------------------------------------------------
class StateCode(str, Enum):
    CA = "CA"
    NY = "NY"
    TX = "TX"
    MA = "MA"


class CcFeePolicy(str, Enum):
    PROHIBITED = "PROHIBITED"
    ACTUAL_ONLY = "ACTUAL_ONLY"
    CAPPED_BPS = "CAPPED_BPS"


class ServiceChargeTreatment(str, Enum):
    WAGES = "WAGES"
    TIPS = "TIPS"


class TipStatus(str, Enum):
    TIPPED = "TIPPED"
    NON_TIPPED = "NON_TIPPED"


class PoolType(str, Enum):
    TIPPED_ONLY = "TIPPED_ONLY"
    ALL_NON_MANAGEMENT = "ALL_NON_MANAGEMENT"


class ContributionBasis(str, Enum):
    TIPS_RECEIVED_PCT = "TIPS_RECEIVED_PCT"
    GROSS_SALES_PCT = "GROSS_SALES_PCT"


class ShareBasis(str, Enum):
    POINTS_ONLY = "POINTS_ONLY"
    HOURS_WEIGHTED_POINTS = "HOURS_WEIGHTED_POINTS"


class TipPoolPolicyStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class PayPeriodStatus(str, Enum):
    OPEN = "OPEN"
    COMPUTED = "COMPUTED"
    APPROVED = "APPROVED"


class ComputeVariant(str, Enum):
    WEEKLY_AGGREGATE = "WEEKLY_AGGREGATE"
    PER_SHIFT = "PER_SHIFT"


class ShiftTimeStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"


class ShiftDeclarationStatus(str, Enum):
    UNDECLARED = "UNDECLARED"
    DECLARED = "DECLARED"
    AMENDED = "AMENDED"


class ServiceChargeStatus(str, Enum):
    RECORDED = "RECORDED"
    ALLOCATED = "ALLOCATED"
    VOIDED = "VOIDED"


class PoolContributionStatus(str, Enum):
    CONTRIBUTED = "CONTRIBUTED"
    REVERSED = "REVERSED"


class PoolDistributionStatus(str, Enum):
    PENDING = "PENDING"
    DISTRIBUTED = "DISTRIBUTED"
    REVERSED = "REVERSED"


class PoolAllocationEntryType(str, Enum):
    DISTRIBUTION = "DISTRIBUTION"
    REVERSAL = "REVERSAL"


class PayLineStatus(str, Enum):
    DRAFT = "DRAFT"
    FINAL = "FINAL"
    SUPERSEDED = "SUPERSEDED"


class DisputeCategory(str, Enum):
    POOL_SHARE = "POOL_SHARE"
    TIP_CREDIT = "TIP_CREDIT"
    CC_FEE = "CC_FEE"
    SERVICE_CHARGE = "SERVICE_CHARGE"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UPHELD = "UPHELD"
    PARTIALLY_UPHELD = "PARTIALLY_UPHELD"
    DENIED = "DENIED"
    CLOSED = "CLOSED"


class DisputeResolution(str, Enum):
    UPHELD = "UPHELD"
    PARTIALLY_UPHELD = "PARTIALLY_UPHELD"
    DENIED = "DENIED"


class CorrectionReasonCode(str, Enum):
    POOL_SHARE_SHORTFALL = "POOL_SHARE_SHORTFALL"
    TIP_CREDIT_INVALID = "TIP_CREDIT_INVALID"
    CC_FEE_OVERDEDUCTION = "CC_FEE_OVERDEDUCTION"
    SERVICE_CHARGE_MISCLASSIFIED = "SERVICE_CHARGE_MISCLASSIFIED"
    SIDE_WORK_OVERAGE = "SIDE_WORK_OVERAGE"


class CorrectionStatus(str, Enum):
    PENDING = "PENDING"
    APPLIED = "APPLIED"
    VOIDED = "VOIDED"


# ---------------------------------------------------------------------------
# Entities carrying the common audit quartet
# ---------------------------------------------------------------------------
class Location(TypedDict):
    id: str
    name: str
    state_code: str
    state_min_wage_cents: int
    cash_wage_cents: int
    tip_credit_enabled: bool
    cc_fee_policy: str
    cc_fee_cap_bps: Optional[int]
    service_charge_treatment: str
    applicable_min_wage_cents: int
    max_tip_credit_per_hour_cents: int
    pending_pool_cents: int
    created_at: str
    updated_at: str
    version: int


class JobRole(TypedDict):
    id: str
    code: str
    title: str
    tip_status: str
    is_management: bool
    pool_contribution_pct_bps: int
    pool_share_points: int
    side_work_eligible: bool
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict):
    id: str
    location_id: str
    full_name: str
    external_payroll_ref: str
    monthly_tip_baseline_cents: int
    separation_date: Optional[str]
    trailing_pool_receipts_cents: int
    created_at: str
    updated_at: str
    version: int


class EmployeeRoleAssignment(TypedDict):
    id: str
    employee_id: str
    job_role_id: str
    effective_from: str
    effective_to: Optional[str]
    tip_credit_notice_acknowledged_at: Optional[str]
    is_primary: bool
    dual_job: bool
    created_at: str
    updated_at: str
    version: int


class TipPoolPolicy(TypedDict):
    id: str
    location_id: str
    pool_type: str
    contribution_basis: str
    share_basis: str
    cc_fee_pass_through: bool
    status: str
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayPeriod(TypedDict):
    id: str
    location_id: str
    start_date: str
    end_date: str
    status: str
    compute_variant: Optional[str]
    computed_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    total_credited_minutes: int
    total_tip_credit_cents: int
    total_topup_cents: int
    total_correction_cents: int
    gross_receipts_cents: int
    reported_tips_cents: int
    allocation_shortfall_cents: int
    created_at: str
    updated_at: str
    version: int


class Shift(TypedDict):
    id: str
    employee_id: str
    location_id: str
    job_role_id: str
    pay_period_id: str
    shift_tip_pool_id: Optional[str]
    business_date: str
    start_at: str
    end_at: str
    scheduled_minutes: int
    side_work_minutes: int
    max_continuous_side_work_minutes: int
    non_tip_credit_minutes: int
    tip_credit_eligible_minutes: int
    gross_sales_cents: int
    charged_sales_cents: int
    cc_processing_fee_bps: int
    declared_cash_tips_cents: int
    declared_charged_tips_cents: int
    declaration_count: int
    time_status: str
    declaration_status: str
    pool_contribution_cents: int
    retained_tips_cents: int
    shift_tip_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class ServiceChargeEvent(TypedDict):
    id: str
    location_id: str
    allocated_pool_id: Optional[str]
    allocated_pay_period_id: Optional[str]
    business_date: str
    amount_cents: int
    description: str
    treatment_override: Optional[str]
    treatment: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ShiftTipPool(TypedDict):
    id: str
    location_id: str
    tip_pool_policy_id: str
    policy_version_pinned: int
    business_date: str
    contribution_status: str
    distribution_status: str
    contributing_shift_count: int
    participant_count: int
    total_contributed_cents: int
    service_charge_tips_cents: int
    cc_fee_deducted_cents: int
    net_pool_cents: int
    total_share_weight: int
    distributed_cents: int
    distributed_at: Optional[str]
    reversed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayLine(TypedDict):
    id: str
    pay_period_id: str
    employee_id: str
    variant: str
    status: str
    total_minutes: int
    tip_credit_eligible_minutes: int
    non_tip_credit_minutes: int
    regular_minutes: int
    overtime_minutes: int
    straight_cash_cents: int
    service_charge_wages_cents: int
    regular_rate_cents_per_hour: int
    overtime_premium_cents: int
    minimum_wage_obligation_cents: int
    tips_available_cents: int
    pool_tips_cents: int
    retained_tips_cents: int
    tipped_employee_qualified: bool
    tip_credit_cents: int
    topup_cents: int
    total_gross_cents: int
    reported_tips_cents: int
    allocated_tips_cents: int
    correction_applied_cents: int
    pending_correction_cents: int
    open_dispute_count: int
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    pay_line_id: str
    raised_by_employee_id: str
    category: str
    claimed_amount_cents: int
    narrative: str
    status: str
    adjudicated_amount_cents: int
    adjudicated_by_user_id: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BackWageCorrection(TypedDict):
    id: str
    pay_line_id: str
    dispute_id: Optional[str]
    supersedes_correction_id: Optional[str]
    amount_cents: int
    reason_code: str
    status: str
    issued_by_user_id: str
    applied_by_user_id: Optional[str]
    applied_at: Optional[str]
    voided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only ledger row: id + created_at only, no updated_at and no version
# ---------------------------------------------------------------------------
class PoolAllocation(TypedDict):
    id: str
    shift_tip_pool_id: str
    employee_id: str
    shift_id: str
    entry_type: str
    share_weight: int
    allocated_cents: int
    remainder_cent_awarded: bool
    business_date: str
    created_at: str
