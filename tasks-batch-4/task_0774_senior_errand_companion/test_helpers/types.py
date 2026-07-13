"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity model and lifecycle states.
"""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------
# Role enum
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    CARE_COORDINATOR = "CareCoordinator"
    CAREGIVER = "Caregiver"
    FAMILY_CONTACT = "FamilyContact"
    BILLING_CLERK = "BillingClerk"


# --------------------------------------------------------------------------
# Status enums (one per lifecycle-bearing entity)
# --------------------------------------------------------------------------
class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CaregiverStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class BackgroundCheckStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"
    EXPIRED = "EXPIRED"


class BondingRecordStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"


class RecurringScheduleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ENDED = "ENDED"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    ESCALATED = "ESCALATED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AssignmentStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class AddOnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    VOID = "VOID"


class LTCPolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"


class ReimbursementClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    NEEDS_INFO = "NEEDS_INFO"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class WellnessCheckStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


# --------------------------------------------------------------------------
# Value enums used in payloads
# --------------------------------------------------------------------------
class TaskType(str, Enum):
    GROCERY = "GROCERY"
    RX_PICKUP = "RX_PICKUP"
    TRANSPORT = "TRANSPORT"
    COMPANION = "COMPANION"


class BenefitType(str, Enum):
    INDEMNITY = "INDEMNITY"
    REIMBURSEMENT = "REIMBURSEMENT"


# --------------------------------------------------------------------------
# Entity TypedDicts. Entities carrying the full common-field set
# (id, created_at, updated_at, version) vs. the append-only VisitLogEntry
# (id + created_at only).
# --------------------------------------------------------------------------
class Client(TypedDict):
    id: str
    name: str
    timezone: str
    home_zip: str
    hourly_rate_cents: int
    mileage_rate_cents_per_mile: float
    ot_threshold_hours: float
    ot_multiplier: float
    min_visit_minutes: int
    status: str
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class FamilyContact(TypedDict):
    id: str
    client_id: str
    name: str
    email: str
    relationship: str
    created_at: str
    updated_at: str
    version: int


class Caregiver(TypedDict):
    id: str
    name: str
    home_zip: str
    hourly_pay_cents: int
    status: str
    committed_minutes: int
    created_at: str
    updated_at: str
    version: int


class BackgroundCheck(TypedDict):
    id: str
    caregiver_id: str
    status: str
    decided_at: Optional[str]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BondingRecord(TypedDict):
    id: str
    caregiver_id: str
    coverage_cents: int
    effective_date: str
    expiry_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RecurringSchedule(TypedDict):
    id: str
    client_id: str
    task_type: str
    frequency: str
    day_of_week: str
    start_time: str
    duration_minutes: int
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict):
    id: str
    client_id: str
    schedule_id: Optional[str]
    caregiver_id: Optional[str]
    task_type: str
    scheduled_start: str
    scheduled_end: str
    actual_start: Optional[str]
    actual_end: Optional[str]
    mileage_miles: float
    status: str
    hourly_rate_cents: int
    mileage_rate_cents_per_mile: float
    ot_threshold_hours: float
    ot_multiplier: float
    min_visit_minutes: int
    estimated_cost_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict):
    id: str
    visit_id: str
    caregiver_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict):
    id: str
    visit_id: str
    addon_type: str
    fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    client_id: str
    visit_id: str
    status: str
    labor_cents: int
    mileage_cents: int
    addon_cents: int
    total_cents: int
    created_at: str
    updated_at: str
    version: int


class LTCPolicy(TypedDict):
    id: str
    client_id: str
    payer_name: str
    benefit_type: str
    daily_benefit_cents: Optional[int]
    reimbursement_rate: Optional[float]
    daily_cap_cents: Optional[int]
    lifetime_max_cents: int
    reimbursed_to_date_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReimbursementClaim(TypedDict):
    id: str
    invoice_id: str
    ltc_policy_id: str
    benefit_type: str
    status: str
    eligible_cents: int
    reimbursed_cents: int
    client_responsibility_cents: int
    created_at: str
    updated_at: str
    version: int


class WellnessCheck(TypedDict):
    id: str
    visit_id: str
    client_id: str
    severity: str
    reason: str
    status: str
    acknowledged_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only, immutable: carries ONLY id + created_at (no updated_at, no version).
class VisitLogEntry(TypedDict):
    id: str
    visit_id: str
    entry_type: str
    note: str
    created_at: str
