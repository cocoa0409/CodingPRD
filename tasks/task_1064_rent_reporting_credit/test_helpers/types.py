"""Domain types: entity TypedDicts, status enums, role enum.

All names mirror the Rent-Reporting & Credit API contract (PRD §2-§3).
"""
from enum import Enum
from typing import TypedDict, Optional, List, Dict


# --------------------------------------------------------------------------
# Role enum (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    TENANT = "Tenant"
    LANDLORD = "Landlord"
    COMPLIANCE_ANALYST = "ComplianceAnalyst"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class EnrollmentStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class LeaseVerificationStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    TERMINATED = "TERMINATED"


class RentPaymentStatus(str, Enum):
    RECORDED = "RECORDED"
    REPORTED = "REPORTED"


class ReportedItemStatus(str, Enum):
    REPORTED = "REPORTED"
    DISPUTED = "DISPUTED"
    CORRECTED = "CORRECTED"
    RETRACTED = "RETRACTED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED_CORRECTED = "RESOLVED_CORRECTED"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    WITHDRAWN = "WITHDRAWN"


class BackReportStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


class InvoiceStatus(str, Enum):
    DUE = "DUE"
    PAID = "PAID"
    VOID = "VOID"


class InvoiceKind(str, Enum):
    SUBSCRIPTION = "SUBSCRIPTION"
    BACK_REPORT = "BACK_REPORT"


class Bureau(str, Enum):
    EQUIFAX = "EQUIFAX"
    EXPERIAN = "EXPERIAN"
    TRANSUNION = "TRANSUNION"


class PlanTier(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    PREMIUM = "PREMIUM"


class DisputeReason(str, Enum):
    NOT_MINE = "NOT_MINE"
    INCORRECT_AMOUNT = "INCORRECT_AMOUNT"
    INCORRECT_STATUS = "INCORRECT_STATUS"
    PAID_ON_TIME = "PAID_ON_TIME"


# --------------------------------------------------------------------------
# Entity TypedDicts
# common_fields:true entities carry id + created_at + updated_at + version.
# ScoreSnapshot is append-only (common_fields:false) -> only id + created_at.
# --------------------------------------------------------------------------
class Tenant(TypedDict):
    id: str
    full_name: str
    email: str
    phone: Optional[str]
    reported_on_time_rate_pct: Optional[int]
    effective_reported_items: int
    created_at: str
    updated_at: str
    version: int


class Landlord(TypedDict):
    id: str
    company_name: str
    email: str
    contact_name: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubscriptionPlan(TypedDict):
    id: str
    name: str
    tier: str
    monthly_fee_cents: int
    back_reporting_included_months: int
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    tenant_id: str
    plan_id: str
    status: str
    monthly_fee_cents: int
    current_period_start: Optional[str]
    current_period_end: Optional[str]
    cancelled_at: Optional[str]
    refund_cents: int
    earned_cents: int
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict):
    id: str
    tenant_id: str
    landlord_id: str
    property_address: str
    rent_amount_cents: int
    monthly_due_day: int
    lease_start: str
    lease_end: str
    verification_status: str
    created_at: str
    updated_at: str
    version: int


class RentPayment(TypedDict):
    id: str
    lease_id: str
    period_month: str
    due_date: str
    paid_date: Optional[str]
    amount_paid_cents: int
    on_time: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ReportedItem(TypedDict):
    id: str
    rent_payment_id: str
    tenant_id: str
    lease_id: str
    supersedes_item_id: Optional[str]
    period_month: str
    on_time: bool
    amount_reported_cents: int
    source: str
    status: str
    bureau_statuses: Dict[str, str]
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    reported_item_id: str
    tenant_id: str
    reason_code: str
    status: str
    analyst_user_id: Optional[str]
    officer_user_id: Optional[str]
    investigation_deadline: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BackReportRequest(TypedDict):
    id: str
    lease_id: str
    requested_months: List[str]
    billable_months: int
    fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    enrollment_id: str
    back_report_request_id: Optional[str]
    kind: str
    amount_cents: int
    period_month: Optional[str]
    status: str
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScoreSnapshot(TypedDict):
    id: str
    tenant_id: str
    bureau: str
    score: int
    as_of_month: str
    created_at: str
