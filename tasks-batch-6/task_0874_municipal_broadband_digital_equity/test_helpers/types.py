"""Domain types: entity TypedDicts, status enums, role enum.

All types reflect the field names and enumerations defined in the PRD.
"""
from enum import Enum
from typing import TypedDict, List, Optional


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    COMPLIANCE_ANALYST = "ComplianceAnalyst"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CUSTOMER_CARE = "CustomerCare"
    ELIGIBILITY_WORKER = "EligibilityWorker"
    DISPATCHER = "Dispatcher"
    FIELD_TECH = "FieldTech"
    NOC_OPERATOR = "NocOperator"
    BILLING = "Billing"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class GrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MILESTONE_MET = "MILESTONE_MET"
    CLOSED = "CLOSED"


class ServiceAreaStatus(str, Enum):
    PLANNED = "PLANNED"
    CONSTRUCTION = "CONSTRUCTION"
    SERVICEABLE = "SERVICEABLE"
    SUSPENDED = "SUSPENDED"


class SubscriberStatus(str, Enum):
    ACTIVE = "ACTIVE"


class SubscriptionServiceStatus(str, Enum):
    PENDING_INSTALL = "PENDING_INSTALL"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class SubscriptionBillingStatus(str, Enum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"


class EnrollmentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACTIVE = "ACTIVE"
    DENIED = "DENIED"
    RECERT_DUE = "RECERT_DUE"
    TERMINATED = "TERMINATED"


class TechnicianStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    INACTIVE = "INACTIVE"


class InstallOrderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DeviceStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    ASSIGNED = "ASSIGNED"
    DEPLOYED = "DEPLOYED"
    RETURNED = "RETURNED"


class DeviceClass(str, Enum):
    CPE_MODEM = "CPE_MODEM"
    TABLET = "TABLET"
    LAPTOP = "LAPTOP"
    HOTSPOT = "HOTSPOT"


class OutageStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class OutageSeverity(str, Enum):
    PARTIAL = "PARTIAL"
    FULL = "FULL"


class SlaCreditStatus(str, Enum):
    PENDING = "PENDING"
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class GrantClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# --------------------------------------------------------------------------
# Entity TypedDicts (all entities carry id/created_at/updated_at/version)
# --------------------------------------------------------------------------
class Grant(TypedDict):
    id: str
    funding_source: str
    program_name: str
    award_amount_cents: int
    match_required_pct: float
    take_rate_milestone_pct: float
    take_rate_floor_pct: float
    committed_balance_cents: int
    disbursed_balance_cents: int
    available_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceArea(TypedDict):
    id: str
    grant_id: str
    name: str
    census_block_group: str
    homes_passed: int
    fiber_ready: bool
    reported_take_rate_pct: float
    verified_take_rate_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ServicePlan(TypedDict):
    id: str
    tier: str
    name: str
    download_mbps: int
    upload_mbps: int
    monthly_price_cents: int
    sla_uptime_pct: float
    created_at: str
    updated_at: str
    version: int


class SubsidyProgram(TypedDict):
    id: str
    name: str
    monthly_discount_cents: int
    device_benefit_cents: int
    eligibility_fpl_pct: float
    created_at: str
    updated_at: str
    version: int


class Subscriber(TypedDict):
    id: str
    service_area_id: str
    full_name: str
    email: str
    service_address: str
    household_size: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    subscriber_id: str
    plan_id: str
    service_area_id: str
    monthly_price_cents: int
    service_status: str
    billing_status: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    subscriber_id: str
    subsidy_program_id: str
    household_size: int
    annual_income_cents: int
    fpl_pct: float
    certification_expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    name: str
    region: str
    job_duration_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InstallOrder(TypedDict):
    id: str
    subscription_id: str
    technician_id: str
    scheduled_start_at: str
    scheduled_end_at: str
    reschedule_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Device(TypedDict):
    id: str
    device_class: str
    model: str
    serial_number: str
    value_cents: int
    subscription_id: Optional[str]
    enrollment_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class OutageEvent(TypedDict):
    id: str
    service_area_id: str
    started_at: str
    ended_at: Optional[str]
    severity: str
    estimated_credit_total_cents: int
    final_credit_total_cents: Optional[int]
    affected_subscription_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SlaCredit(TypedDict):
    id: str
    subscription_id: str
    outage_id: str
    downtime_minutes: int
    credit_cents: int
    applied_invoice_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    subscription_id: str
    period_start: str
    period_end: str
    base_amount_cents: int
    subsidy_discount_cents: int
    sla_credit_cents: int
    total_due_cents: int
    amount_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GrantClaim(TypedDict):
    id: str
    grant_id: str
    claim_period_start: str
    claim_period_end: str
    service_area_ids: List[str]
    reported_take_rate_pct: float
    subsidized_subscriber_count: int
    amount_claimed_cents: int
    submitted_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
