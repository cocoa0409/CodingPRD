"""Domain types: entity TypedDicts, status enums, role enum.

Field membership follows the PRD's common-resource rule (§2.4): every record except
the fee schedule carries id/created_at/updated_at/version; the fee schedule carries
only id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CODE_OFFICER = "CodeOfficer"
    HEARING_OFFICER = "HearingOfficer"
    FINANCE_CLERK = "FinanceClerk"
    REGISTRANT = "Registrant"


# --------------------------------------------------------------------------
# Status / enum value sets
# --------------------------------------------------------------------------
class OwnerRepeatTier(str, Enum):
    FIRST = "FIRST"
    REPEAT = "REPEAT"
    CHRONIC = "CHRONIC"


class PropertyOccupancy(str, Enum):
    OCCUPIED = "OCCUPIED"
    VACANT = "VACANT"


class PropertyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class ViolationClass(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    HAZARD = "HAZARD"


class CasePosture(str, Enum):
    INTAKE = "INTAKE"
    ACTIVE = "ACTIVE"
    ABATEMENT = "ABATEMENT"
    LIENED = "LIENED"
    CLOSED = "CLOSED"


class ComplaintStatus(str, Enum):
    RECEIVED = "RECEIVED"
    TRIAGED = "TRIAGED"
    DISMISSED = "DISMISSED"


class ReporterKind(str, Enum):
    RESIDENT = "RESIDENT"
    ANONYMOUS = "ANONYMOUS"
    OFFICER_OBSERVED = "OFFICER_OBSERVED"


class InspectionKind(str, Enum):
    INITIAL = "INITIAL"
    REINSPECTION = "REINSPECTION"


class InspectionOutcome(str, Enum):
    PENDING = "PENDING"
    VIOLATION_FOUND = "VIOLATION_FOUND"
    NO_VIOLATION = "NO_VIOLATION"
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"


class NoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    COMPLIED = "COMPLIED"
    OVERDUE = "OVERDUE"
    CONTESTED = "CONTESTED"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"
    SETTLED = "SETTLED"


class ReinspectionResult(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class FineSourceKind(str, Enum):
    CITATION = "CITATION"
    ABATEMENT_COST = "ABATEMENT_COST"


class FineSettlementStatus(str, Enum):
    OPEN = "OPEN"
    SETTLED = "SETTLED"
    WAIVED = "WAIVED"


class HearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD_UPHELD = "HELD_UPHELD"
    HELD_DISMISSED = "HELD_DISMISSED"
    CONTINUED = "CONTINUED"


class AbatementActionKind(str, Enum):
    BOARD_UP = "BOARD_UP"
    DEMOLITION = "DEMOLITION"


class AbatementStatus(str, Enum):
    ORDERED = "ORDERED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class LienStatus(str, Enum):
    PENDING = "PENDING"
    RECORDED = "RECORDED"
    RELEASED = "RELEASED"
    FORECLOSED = "FORECLOSED"


# --------------------------------------------------------------------------
# Entity TypedDicts — full records carry id/created_at/updated_at/version
# --------------------------------------------------------------------------
class Owner(TypedDict):
    id: str
    full_name: str
    mailing_email: str
    repeat_tier: str
    prior_violation_count: int
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    owner_id: str
    parcel_number: str
    street_address: str
    occupancy: str
    status: str
    created_at: str
    updated_at: str
    version: int


# FeeSchedule carries ONLY id + created_at (reference configuration; §2.4).
class FeeSchedule(TypedDict):
    id: str
    violation_class: str
    base_fine_cents: int
    daily_accrual_cents: int
    max_total_cents: int
    cure_days: int
    created_at: str


class Case(TypedDict):
    id: str
    property_id: str
    opened_by_user_id: str
    posture: str
    outstanding_balance_cents: int
    payments_applied_cents: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    case_id: str
    reporter_kind: str
    narrative: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    case_id: str
    kind: str
    notice_id: Optional[str]
    outcome: str
    inspected_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ViolationNotice(TypedDict):
    id: str
    case_id: str
    owner_id: str
    source_inspection_id: str
    violation_class: str
    escalation_multiplier: float
    effective_date: Optional[str]
    compliance_deadline: Optional[str]
    status: str
    fine_total_cents: int
    days_overdue: int
    created_at: str
    updated_at: str
    version: int


class Reinspection(TypedDict):
    id: str
    notice_id: str
    requested_by_user_id: str
    result: str
    result_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Fine(TypedDict):
    id: str
    notice_id: str
    source_kind: str
    assessed_cents: int
    settlement_status: str
    created_at: str
    updated_at: str
    version: int


class Hearing(TypedDict):
    id: str
    notice_id: str
    requested_by_user_id: str
    scheduled_for: str
    status: str
    continuance_count: int
    created_at: str
    updated_at: str
    version: int


class AbatementOrder(TypedDict):
    id: str
    case_id: str
    action_kind: str
    estimated_cost_cents: int
    actual_cost_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Lien(TypedDict):
    id: str
    case_id: str
    property_id: str
    principal_cents: int
    admin_fee_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
