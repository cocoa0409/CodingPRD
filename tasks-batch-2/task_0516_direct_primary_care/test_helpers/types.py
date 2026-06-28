"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Status / enum domains ---

class MembershipStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class PlanType(str, Enum):
    MONTHLY = "MONTHLY"
    ANNUAL_PREPAID = "ANNUAL_PREPAID"


class PanelLoadBucket(str, Enum):
    UNDER_TARGET = "UNDER_TARGET"
    AT_TARGET = "AT_TARGET"
    FULL = "FULL"


class SeatStatus(str, Enum):
    OPEN = "OPEN"
    OCCUPIED = "OCCUPIED"
    RELEASED = "RELEASED"


class SlotType(str, Enum):
    IN_PERSON = "IN_PERSON"
    VIRTUAL = "VIRTUAL"


class SlotState(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"


class VisitType(str, Enum):
    SAME_DAY = "SAME_DAY"
    VIRTUAL = "VIRTUAL"
    ANNUAL_PHYSICAL = "ANNUAL_PHYSICAL"


class ClinicalStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class BillingStatus(str, Enum):
    NOT_BILLABLE = "NOT_BILLABLE"
    BILLABLE = "BILLABLE"
    INVOICED = "INVOICED"
    WRITTEN_OFF = "WRITTEN_OFF"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    UNDER_REVISION = "UNDER_REVISION"
    ARCHIVED = "ARCHIVED"


class ReferralStatus(str, Enum):
    REQUESTED = "REQUESTED"
    AUTHORIZED = "AUTHORIZED"
    SENT = "SENT"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class ThreadPriority(str, Enum):
    ROUTINE = "ROUTINE"
    AFTER_HOURS = "AFTER_HOURS"


class ThreadStatus(str, Enum):
    OPEN = "OPEN"
    ANSWERED = "ANSWERED"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class ChargeKind(str, Enum):
    MEMBERSHIP_FEE = "MEMBERSHIP_FEE"
    INVOICE = "INVOICE"


class PaymentOutcome(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PROVIDER = "Provider"
    MEMBER = "Member"
    EMPLOYER = "Employer"
    ANONYMOUS = "Anonymous"


# --- Entity TypedDicts ---
# Entities below carry common fields id/created_at/updated_at/version,
# except Payment which is immutable (id + created_at only).

class Practice(TypedDict):
    id: str
    name: str
    panel_target: int
    panel_hard_cap: int
    monthly_fee_cents: int
    annual_fee_discount_pct: float
    dpc_covered_service_codes: List[str]
    insurance_coinsurance_pct: float
    late_fee_cents: int
    grace_period_days: int
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict):
    id: str
    practice_id: str
    full_name: str
    npi: str
    panel_capacity: Optional[int]
    accepting_new_members: bool
    active_panel_count: int
    panel_load_bucket: str
    created_at: str
    updated_at: str
    version: int


class Employer(TypedDict):
    id: str
    practice_id: str
    company_name: str
    sponsored_seat_limit: int
    sponsorship_pct: float
    occupied_seat_count: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    practice_id: str
    assigned_provider_id: Optional[str]
    email: str
    full_name: str
    plan_type: str
    membership_status: str
    has_insurance: bool
    wallet_credit_cents: int
    annual_physical_due_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    member_id: str
    plan_type: str
    monthly_fee_cents: int
    employer_seat_id: Optional[str]
    member_share_cents: int
    current_period_start: Optional[str]
    current_period_end: Optional[str]
    past_due_since: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EmployerSeat(TypedDict):
    id: str
    employer_id: str
    member_id: Optional[str]
    seat_status: str
    created_at: str
    updated_at: str
    version: int


class VisitSlot(TypedDict):
    id: str
    provider_id: str
    slot_type: str
    starts_at: str
    ends_at: str
    virtual_capacity: int
    booked_count: int
    slot_state: str
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict):
    id: str
    member_id: str
    provider_id: str
    slot_id: str
    visit_type: str
    clinical_status: str
    billing_status: str
    service_lines: list
    checked_in_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CarePlan(TypedDict):
    id: str
    member_id: str
    origin_visit_id: str
    plan_status: str
    goal_count: int
    revision_number: int
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    member_id: str
    origin_visit_id: str
    specialty: str
    referral_status: str
    authorized_at: Optional[str]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MessageThread(TypedDict):
    id: str
    member_id: str
    provider_id: str
    priority: str
    thread_status: str
    response_deadline: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    member_id: str
    visit_id: str
    gross_charge_cents: int
    dpc_covered_cents: int
    insurance_billed_cents: int
    member_responsibility_cents: int
    invoice_status: str
    created_at: str
    updated_at: str
    version: int


# Payment is immutable: id + created_at only (no updated_at, no version).
class Payment(TypedDict):
    id: str
    member_id: str
    membership_id: Optional[str]
    invoice_id: Optional[str]
    charge_kind: str
    amount_cents: int
    outcome: str
    wallet_applied_cents: int
    created_at: str
