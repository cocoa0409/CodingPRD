"""Domain types: entity TypedDicts, status enums, role enum for the COBRA
Administration API.

All monetary fields are integers denominated in whole cents (PRD §2.6).
The HIPAA certificate is the one immutable record: it carries only id +
created_at, with no updated_at and no version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLAN_ADMINISTRATOR = "PlanAdministrator"
    PLAN_SPONSOR = "PlanSponsor"
    BILLING_AGENT = "BillingAgent"
    QUALIFIED_BENEFICIARY = "QualifiedBeneficiary"
    SYSTEM = "System"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class BeneficiaryStatus(str, Enum):
    ACTIVE_EMPLOYEE_COVERAGE = "ACTIVE_EMPLOYEE_COVERAGE"
    COBRA_ELIGIBLE = "COBRA_ELIGIBLE"
    COBRA_ENROLLED = "COBRA_ENROLLED"
    COVERAGE_ENDED = "COVERAGE_ENDED"


class EventType(str, Enum):
    TERMINATION = "TERMINATION"
    REDUCTION_OF_HOURS = "REDUCTION_OF_HOURS"
    DIVORCE = "DIVORCE"
    DEATH_OF_EMPLOYEE = "DEATH_OF_EMPLOYEE"
    MEDICARE_ENTITLEMENT = "MEDICARE_ENTITLEMENT"
    DEPENDENT_AGE_OUT = "DEPENDENT_AGE_OUT"


class EventStatus(str, Enum):
    RECORDED = "RECORDED"
    NOTICE_SENT = "NOTICE_SENT"
    ELECTED = "ELECTED"
    LAPSED = "LAPSED"
    VOID = "VOID"


class NoticeStatus(str, Enum):
    OUTSTANDING = "OUTSTANDING"
    ELECTED = "ELECTED"
    EXPIRED = "EXPIRED"


class EnrollmentStatus(str, Enum):
    PENDING_INITIAL_PREMIUM = "PENDING_INITIAL_PREMIUM"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class TerminationReason(str, Enum):
    RUN_TO_TERM = "RUN_TO_TERM"
    NONPAYMENT = "NONPAYMENT"
    OTHER_GROUP_COVERAGE = "OTHER_GROUP_COVERAGE"
    MEDICARE_ENTITLEMENT = "MEDICARE_ENTITLEMENT"
    PLAN_TERMINATED = "PLAN_TERMINATED"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"
    VOID = "VOID"


class ProrationMode(str, Enum):
    FULL_MONTH = "FULL_MONTH"
    DAILY_PRORATED = "DAILY_PRORATED"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"
    REFUNDED = "REFUNDED"


class SubsidyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class Relationship(str, Enum):
    EMPLOYEE = "EMPLOYEE"
    SPOUSE = "SPOUSE"
    DEPENDENT = "DEPENDENT"


# ---------------------------------------------------------------------------
# Entity TypedDicts — common_fields:true carry id/created_at/updated_at/version
# ---------------------------------------------------------------------------
class GroupHealthPlan(TypedDict):
    id: str
    name: str
    applicable_premium_cents: int
    standard_admin_fee_pct: float
    disability_admin_fee_pct: float
    employer_notice_days: int
    election_notice_days: int
    election_window_days: int
    initial_premium_grace_days: int
    recurring_premium_grace_days: int
    insignificant_shortfall_floor_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class QualifiedBeneficiary(TypedDict):
    id: str
    plan_id: str
    full_name: str
    relationship: str
    original_coverage_start: str
    status: str
    created_at: str
    updated_at: str
    version: int


class QualifyingEvent(TypedDict):
    id: str
    plan_id: str
    beneficiary_id: str
    event_type: str
    event_date: str
    coverage_loss_date: str
    max_coverage_months: int
    reported_at: str
    employer_notice_deadline: Optional[str]
    late_reported: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ElectionNotice(TypedDict):
    id: str
    event_id: str
    beneficiary_id: str
    notice_sent_date: str
    election_window_anchor: str
    election_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CobraEnrollment(TypedDict):
    id: str
    notice_id: str
    beneficiary_id: str
    event_id: str
    elected_at: str
    coverage_start_date: str
    base_max_months: int
    extension_months: int
    scheduled_end_date: str
    disability_extension: bool
    actual_end_date: Optional[str]
    termination_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PremiumAccount(TypedDict):
    id: str
    enrollment_id: str
    beneficiary_id: str
    monthly_premium_cents: int
    amount_invoiced_cents: int
    amount_paid_cents: int
    amount_subsidized_cents: int
    amount_refunded_cents: int
    credit_balance_cents: int
    paid_through_date: Optional[str]
    initial_premium_due_date: str
    created_at: str
    updated_at: str
    version: int


class PremiumInvoice(TypedDict):
    id: str
    account_id: str
    coverage_month: str
    coverage_month_index: int
    gross_premium_cents: int
    proration_mode: str
    amount_due_cents: int
    subsidy_applied_cents: int
    beneficiary_owed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    account_id: str
    amount_cents: int
    received_date: str
    target_coverage_month: str
    deemed_full_payment: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class SubsidyGrant(TypedDict):
    id: str
    enrollment_id: str
    subsidy_pct: float
    start_month: str
    end_month: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields:false — immutable, carries ONLY id + created_at (PRD §2.4)
class HipaaCertificate(TypedDict):
    id: str
    beneficiary_id: str
    enrollment_id: str
    coverage_from: str
    coverage_through: str
    creditable_months: int
    issued_reason: str
    created_at: str
