"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this API carry the common fields id, created_at, updated_at and
version.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    FACILITY_SCHEDULER = "FacilityScheduler"
    FACILITY_VERIFIER = "FacilityVerifier"
    CLINICIAN = "Clinician"
    BILLING_AGENT = "BillingAgent"


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #
class CredentialType(str, Enum):
    RN_LICENSE = "RN_LICENSE"
    BLS = "BLS"
    ACLS = "ACLS"
    TB_SCREENING = "TB_SCREENING"
    FIT_TEST = "FIT_TEST"


class Specialty(str, Enum):
    RN = "RN"
    LPN = "LPN"
    CNA = "CNA"
    RT = "RT"
    PT = "PT"


class CredentialStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ClinicianStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class Urgency(str, Enum):
    STANDARD = "STANDARD"
    CRISIS = "CRISIS"


class OrderStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ShiftStatus(str, Enum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    PENDING = "PENDING"
    AWARDED = "AWARDED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class WorkStatus(str, Enum):
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    WORKED = "WORKED"
    CANCELLED_BY_CLINICIAN = "CANCELLED_BY_CLINICIAN"
    CANCELLED_BY_FACILITY = "CANCELLED_BY_FACILITY"
    NO_SHOW = "NO_SHOW"


class PayStatus(str, Enum):
    UNBILLED = "UNBILLED"
    TIMESHEET_PENDING = "TIMESHEET_PENDING"
    PAYABLE = "PAYABLE"
    INVOICED = "INVOICED"
    PAID = "PAID"
    WAIVED = "WAIVED"


class TimesheetStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    DISPUTED = "DISPUTED"
    VERIFIED = "VERIFIED"
    INVOICED = "INVOICED"
    PAID = "PAID"


class EventType(str, Enum):
    SHIFT_COMPLETED = "SHIFT_COMPLETED"
    LATE_CANCELLATION = "LATE_CANCELLATION"
    VERY_LATE_CANCELLATION = "VERY_LATE_CANCELLATION"
    NO_SHOW = "NO_SHOW"
    FACILITY_CANCELLATION_CREDIT = "FACILITY_CANCELLATION_CREDIT"


class AdjudicationStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    OVERTURNED = "OVERTURNED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    SETTLED = "SETTLED"
    VOID = "VOID"


class MarkupTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


# --------------------------------------------------------------------------- #
# Entity TypedDicts (all entities carry id/created_at/updated_at/version)
# --------------------------------------------------------------------------- #
class Facility(TypedDict):
    id: str
    name: str
    unit_name: str
    unit_capacity: int
    required_credential_types: List[str]
    pending_pay_cents: int
    outstanding_balance_cents: int
    lifetime_billed_cents: int
    created_at: str
    updated_at: str
    version: int


class Clinician(TypedDict):
    id: str
    full_name: str
    email: str
    specialty: str
    status: str
    reliability_score: int
    provisional_reliability_score: int
    no_show_count: int
    completed_shift_count: int
    created_at: str
    updated_at: str
    version: int


class Credential(TypedDict):
    id: str
    clinician_id: str
    credential_type: str
    license_number: str
    issued_on: str
    expires_on: str
    status: str
    verified_at: Optional[str]
    verified_by_user_id: Optional[str]
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RateCard(TypedDict):
    id: str
    facility_id: str
    specialty: str
    base_pay_rate_cents_per_hour: int
    effective_from: str
    effective_to: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StaffingOrder(TypedDict):
    id: str
    facility_id: str
    specialty: str
    headcount: int
    urgency: str
    window_start: str
    window_end: str
    status: str
    shift_count: int
    open_count: int
    filled_count: int
    completed_count: int
    cancelled_count: int
    created_at: str
    updated_at: str
    version: int


class Shift(TypedDict):
    id: str
    order_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    claim_count: int
    scheduled_hours: float
    estimated_hours: float
    estimated_pay_cents: int
    base_pay_rate_cents_per_hour: int
    effective_rate_cents_per_hour: int
    created_at: str
    updated_at: str
    version: int


class ShiftClaim(TypedDict):
    id: str
    shift_id: str
    clinician_id: str
    status: str
    note: Optional[str]
    claimed_at: str
    reliability_snapshot: int
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict):
    id: str
    shift_id: str
    clinician_id: str
    claim_id: str
    replaces_assignment_id: Optional[str]
    work_status: str
    pay_status: str
    awarded_at: str
    confirmed_at: Optional[str]
    estimated_pay_cents: int
    final_pay_cents: Optional[int]
    cancellation_lead_hours: Optional[float]
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Timesheet(TypedDict):
    id: str
    assignment_id: str
    invoice_id: Optional[str]
    clock_in: str
    clock_out: str
    break_minutes: int
    raw_minutes: int
    unpaid_break_minutes: int
    worked_hours: float
    night_hours: float
    weekend_hours: float
    regular_hours: float
    overtime_hours: float
    gross_pay_cents: int
    status: str
    dispute_count: int
    dispute_reason: Optional[str]
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReliabilityEvent(TypedDict):
    id: str
    clinician_id: str
    assignment_id: Optional[str]
    event_type: str
    penalty_points: int
    credit_points: int
    occurred_at: str
    adjudication_status: str
    adjudicated_at: Optional[str]
    reason: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    facility_id: str
    period_start: str
    period_end: str
    status: str
    markup_tier: str
    markup_multiplier: float
    lines: list
    line_count: int
    pay_total_cents: int
    bill_total_cents: int
    margin_cents: int
    issued_by_user_id: Optional[str]
    issued_at: Optional[str]
    due_at: Optional[str]
    settled_by_user_id: Optional[str]
    paid_amount_cents: Optional[int]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
