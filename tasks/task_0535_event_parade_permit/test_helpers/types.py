"""Domain types: entity TypedDicts, status enums, role enum.

Field names and status values follow the Event Parade Permit PRD exactly.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    APPLICANT = "Applicant"
    DEPARTMENT_REVIEWER = "DepartmentReviewer"
    PERMIT_OFFICER = "PermitOfficer"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class VenueStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DECOMMISSIONED = "DECOMMISSIONED"


class ClosureScheduleStatus(str, Enum):
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"


class PermitApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    CONDITIONALLY_APPROVED = "CONDITIONALLY_APPROVED"
    ISSUED = "ISSUED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"
    CLOSED = "CLOSED"


class RouteSegmentStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class DepartmentReviewStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    VETOED = "VETOED"


class Department(str, Enum):
    POLICE = "POLICE"
    FIRE = "FIRE"
    EMS = "EMS"
    PUBLIC_WORKS = "PUBLIC_WORKS"


class PermitConditionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    WAIVED = "WAIVED"


class InsuranceCertificateStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class DepositStatus(str, Enum):
    HELD = "HELD"
    FORFEITED_PARTIAL = "FORFEITED_PARTIAL"
    REFUNDED = "REFUNDED"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    SETTLED = "SETTLED"


class CleanupDebriefStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"


class VenueType(str, Enum):
    PARK = "PARK"
    PLAZA = "PLAZA"
    STADIUM = "STADIUM"
    STREET_CORRIDOR = "STREET_CORRIDOR"


class EventKind(str, Enum):
    PARADE = "PARADE"
    FESTIVAL = "FESTIVAL"
    RACE = "RACE"
    RALLY = "RALLY"


# --------------------------------------------------------------------------
# Entity TypedDicts
# common_fields: true  -> id + created_at + updated_at + version
# common_fields: false -> id + created_at only (EventClock is the exception:
#                         a singleton carrying only current_utc)
# --------------------------------------------------------------------------
class Applicant(TypedDict):
    id: str
    org_name: str
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict):
    id: str
    name: str
    venue_type: str
    max_capacity: int
    setup_buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ClosureSchedule(TypedDict):
    id: str
    corridor_name: str
    min_gap_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PermitApplication(TypedDict):
    id: str
    applicant_org: str
    applicant_user_id: str
    venue_id: str
    event_kind: str
    permit_class: str
    expected_attendance: int
    occupy_start: str
    occupy_end: str
    status: str
    coi_on_file: bool
    required_coverage_min: int
    application_fee: float
    deposit_required: float
    quorum_met: bool
    has_veto: bool
    created_at: str
    updated_at: str
    version: int


class RouteSegment(TypedDict):
    id: str
    application_id: str
    closure_schedule_id: str
    segment_label: str
    closure_start: str
    closure_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DepartmentReview(TypedDict):
    id: str
    application_id: str
    department: str
    status: str
    planned_personnel: int
    planned_hours: float
    hourly_rate: float
    actual_hours: float
    note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PermitCondition(TypedDict):
    id: str
    application_id: str
    department_review_id: str
    text: str
    mandatory: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class InsuranceCertificate(TypedDict):
    id: str
    application_id: str
    carrier: str
    coverage_amount: int
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Deposit(TypedDict):
    id: str
    application_id: str
    amount: float
    status: str
    forfeited_amount: float
    refunded_amount: float
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    application_id: str
    fee_component: float
    cost_recovery_estimate: float
    cost_recovery_actual: float
    balance_due: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CleanupDebrief(TypedDict):
    id: str
    application_id: str
    actual_attendance: int
    cleanup_charges: float
    incident_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EventClock(TypedDict):
    current_utc: str
