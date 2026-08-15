"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    HR_ADMIN = "HRAdmin"
    FINANCE_ADMIN = "FinanceAdmin"
    PAYROLL_SPECIALIST = "PayrollSpecialist"
    MANAGER = "Manager"
    EMPLOYEE = "Employee"
    VENDOR_OPS = "VendorOps"


class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class AccrualMethod(str, Enum):
    STRAIGHT_LINE = "STRAIGHT_LINE"
    UTILIZATION_WEIGHTED = "UTILIZATION_WEIGHTED"


class EmployeeProgramStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    SUSPENDED = "SUSPENDED"


class RecognitionTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class LedgerEntryType(str, Enum):
    GRANT_NOMINATION = "GRANT_NOMINATION"
    GRANT_ANNIVERSARY = "GRANT_ANNIVERSARY"
    GRANT_ADJUSTMENT = "GRANT_ADJUSTMENT"
    HOLD = "HOLD"
    SETTLE_REDEEM = "SETTLE_REDEEM"
    REFUND = "REFUND"
    RESTOCKING_FEE = "RESTOCKING_FEE"
    EXPIRY = "EXPIRY"
    CLAWBACK = "CLAWBACK"


class LedgerReferenceType(str, Enum):
    AWARD = "AWARD"
    REDEMPTION_ORDER = "REDEMPTION_ORDER"
    ABUSE_FLAG = "ABUSE_FLAG"


class BudgetPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    EXHAUSTED = "EXHAUSTED"
    CLOSED = "CLOSED"


class NominationType(str, Enum):
    PEER = "PEER"
    MANAGER = "MANAGER"


class ReasonCode(str, Enum):
    TEAMWORK = "TEAMWORK"
    INNOVATION = "INNOVATION"
    CUSTOMER_SAVE = "CUSTOMER_SAVE"
    DELIVERY = "DELIVERY"
    MENTORSHIP = "MENTORSHIP"
    OTHER = "OTHER"


class NominationStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    RETURNED_FOR_REVISION = "RETURNED_FOR_REVISION"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class AwardSource(str, Enum):
    NOMINATION = "NOMINATION"
    ANNIVERSARY = "ANNIVERSARY"
    ADJUSTMENT = "ADJUSTMENT"


class AwardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FULLY_REDEEMED = "FULLY_REDEEMED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TaxableClass(str, Enum):
    MERCHANDISE = "MERCHANDISE"
    GIFT_CARD = "GIFT_CARD"
    EXPERIENCE = "EXPERIENCE"


class CatalogItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class FulfillmentStatus(str, Enum):
    PENDING_SUBMISSION = "PENDING_SUBMISSION"
    SUBMITTED = "SUBMITTED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    RETURN_REQUESTED = "RETURN_REQUESTED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class EscrowStatus(str, Enum):
    HELD = "HELD"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"
    SETTLED_WITH_FEE = "SETTLED_WITH_FEE"


class TaxRecordStatus(str, Enum):
    ESTIMATED = "ESTIMATED"
    FINALIZED = "FINALIZED"
    AMENDED = "AMENDED"
    VOIDED = "VOIDED"


class AccrualRunStatus(str, Enum):
    OPEN = "OPEN"
    RECONCILED = "RECONCILED"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"


class AbuseFlagRuleCode(str, Enum):
    VELOCITY_EXCEEDED = "VELOCITY_EXCEEDED"
    DUPLICATE_ATTEMPT = "DUPLICATE_ATTEMPT"
    SELF_NOMINATION = "SELF_NOMINATION"
    MANAGER_QUID_PRO_QUO = "MANAGER_QUID_PRO_QUO"
    REDEMPTION_ANOMALY = "REDEMPTION_ANOMALY"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class AbuseFlagStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


class AnniversaryEventStatus(str, Enum):
    PROCESSED = "PROCESSED"
    SKIPPED_INELIGIBLE = "SKIPPED_INELIGIBLE"
    SKIPPED_DUPLICATE = "SKIPPED_DUPLICATE"
    SKIPPED_NO_MILESTONE = "SKIPPED_NO_MILESTONE"
    SKIPPED_BUDGET_EXHAUSTED = "SKIPPED_BUDGET_EXHAUSTED"


# --- Entity TypedDicts ---
# Common-field entities carry id + created_at + updated_at + version.
# PointLedgerEntry is the sole exception (immutable journal record):
# it carries only id + created_at; updated_at and version are absent.


class Program(TypedDict, total=False):
    id: str
    name: str
    status: str
    peer_nomination_enabled: bool
    manager_nomination_enabled: bool
    max_points_per_nomination: int
    point_cost_rate_cents: float
    state_rate_map: Dict[str, float]
    grossup_enabled: bool
    anniversary_milestones: List[Dict[str, int]]
    nomination_review_sla_days: int
    duplicate_window_days: int
    velocity_limit_per_7_days: int
    accrual_method: str
    fiscal_year_start_month: int
    created_at: str
    updated_at: str
    version: int


class Department(TypedDict, total=False):
    id: str
    name: str
    chargeback_account_code: str
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict, total=False):
    id: str
    employee_ref: str
    full_name: str
    department_id: str
    manager_id: Optional[str]
    hire_date: str
    state_code: str
    program_status: str
    recognition_tier: str
    available_points: int
    held_points: int
    lifetime_granted_points: int
    lifetime_redeemed_points: int
    lifetime_expired_points: int
    ytd_supplemental_wages_cents: int
    ytd_de_minimis_cents: int
    created_at: str
    updated_at: str
    version: int


class PointLedgerEntry(TypedDict, total=False):
    # Append-only journal record: id + created_at ONLY. No updated_at, no version.
    id: str
    employee_id: str
    entry_type: str
    points: int
    reference_type: str
    reference_id: str
    idempotency_key: str
    note: str
    created_at: str


class PointBudget(TypedDict, total=False):
    id: str
    program_id: str
    department_id: str
    period_start_date: str
    period_end_date: str
    allocated_points: int
    reserved_points: int
    committed_points: int
    posture: str
    created_at: str
    updated_at: str
    version: int


class Nomination(TypedDict, total=False):
    id: str
    program_id: str
    nominator_id: str
    nominee_id: str
    type: str
    points_requested: int
    reason_code: str
    message: str
    idempotency_key: str
    status: str
    revision_count: int
    review_deadline: str
    budget_id: str
    award_id: Optional[str]
    reviewer_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Award(TypedDict, total=False):
    id: str
    program_id: str
    employee_id: str
    nomination_id: Optional[str]
    source: str
    points: int
    points_remaining: int
    status: str
    granted_at: str
    expires_at: str
    revoked_by_flag_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FulfillmentVendor(TypedDict, total=False):
    id: str
    name: str
    vendor_code: str
    daily_ship_capacity: int
    lead_time_business_days: int
    restocking_fee_percent: int
    supported_categories: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CatalogItem(TypedDict, total=False):
    id: str
    vendor_id: str
    sku: str
    name: str
    category: str
    point_cost: int
    cash_value_cents: int
    taxable_class: str
    de_minimis_eligible: bool
    active_window_start: str
    active_window_end: str
    inventory_quantity: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class RedemptionOrder(TypedDict, total=False):
    id: str
    employee_id: str
    program_id: str
    catalog_item_id: str
    quantity: int
    points_total: int
    fulfillment_status: str
    escrow_status: str
    ship_date: Optional[str]
    idempotency_key: str
    tax_record_id: Optional[str]
    restocking_fee_points: int
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TaxRecord(TypedDict, total=False):
    id: str
    employee_id: str
    program_id: str
    redemption_order_id: str
    tax_year: int
    taxable_value_cents: int
    de_minimis_applied: bool
    federal_rate_applied: float
    state_rate_applied: float
    estimated_gross_up_cents: int
    final_gross_up_cents: Optional[int]
    delta_cents: Optional[int]
    employer_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AccrualRun(TypedDict, total=False):
    id: str
    program_id: str
    period_year: int
    period_month: int
    status: str
    accrual_method_used: str
    department_breakdown: List[Dict[str, Any]]
    total_accrual_cents: int
    total_net_chargeback_cents: int
    variance_cents: int
    created_at: str
    updated_at: str
    version: int


class AbuseFlag(TypedDict, total=False):
    id: str
    employee_id: str
    program_id: str
    rule_code: str
    details: Dict[str, Any]
    status: str
    raised_by: str
    resolved_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AnniversaryEvent(TypedDict, total=False):
    id: str
    program_id: str
    employee_id: str
    milestone_years: int
    scheduled_date: str
    status: str
    award_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
