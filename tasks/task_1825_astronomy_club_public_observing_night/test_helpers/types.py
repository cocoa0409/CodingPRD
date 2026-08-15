"""Domain types: entity TypedDicts, status enums, role enum.

All field names follow the PRD exactly. Entities with the standard four
system-managed fields carry id + created_at + updated_at + version.
DuesPayment and SkyQualityReading are append-only records and carry only
id + created_at (no updated_at, no version).
"""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    CLUB_OFFICER = "ClubOfficer"
    MEMBER = "Member"
    EVENT_COORDINATOR = "EventCoordinator"
    EQUIPMENT_CHAIR = "EquipmentChair"


# ---------------------------------------------------------------------------
# Status / class enums
# ---------------------------------------------------------------------------

class TierCode(str, Enum):
    STUDENT = "STUDENT"
    INDIVIDUAL = "INDIVIDUAL"
    FAMILY = "FAMILY"
    PATRON = "PATRON"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    LAPSED = "LAPSED"
    RESIGNED = "RESIGNED"


class DuesInvoiceStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"
    VOID = "VOID"


class EquipmentClass(str, Enum):
    REFRACTOR = "REFRACTOR"
    REFLECTOR = "REFLECTOR"
    SCT = "SCT"
    DOBSONIAN = "DOBSONIAN"
    SOLAR_SCOPE = "SOLAR_SCOPE"


class TelescopeStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    ON_LOAN = "ON_LOAN"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class CertificationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class LoanStatus(str, Enum):
    RESERVED = "RESERVED"
    CHECKED_OUT = "CHECKED_OUT"
    RETURNED = "RETURNED"
    OVERDUE = "OVERDUE"
    CANCELLED = "CANCELLED"


class TicketKind(str, Enum):
    COLLIMATION = "COLLIMATION"
    REPAIR = "REPAIR"
    CLEANING = "CLEANING"


class TicketSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class TicketStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    VERIFICATION = "VERIFICATION"
    CLOSED = "CLOSED"


class EventKind(str, Enum):
    PUBLIC_NIGHT = "PUBLIC_NIGHT"
    MEMBER_NIGHT = "MEMBER_NIGHT"
    SOLAR_SESSION = "SOLAR_SESSION"


class EventStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class CancellationReason(str, Enum):
    WEATHER = "WEATHER"
    LOW_COVERAGE = "LOW_COVERAGE"
    MOON = "MOON"
    OTHER = "OTHER"


class AssignmentStatus(str, Enum):
    INVITED = "INVITED"
    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"
    NO_SHOW = "NO_SHOW"
    WITHDRAWN = "WITHDRAWN"


class BookingStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"


class ReportStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"


class AdvocacyGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    F = "F"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class MembershipTier(TypedDict, total=False):
    id: str
    code: str
    annual_dues_cents: int
    observatory_access_level: int
    loan_privilege: bool
    max_concurrent_loans: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    tier_id: str
    status: str
    dues_paid_through: str
    effective_access_level: int
    no_show_strikes: int
    joined_at: str
    created_at: str
    updated_at: str
    version: int


class DuesInvoice(TypedDict, total=False):
    id: str
    member_id: str
    period_start: str
    period_end: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DuesPayment(TypedDict, total=False):
    # Append-only: id + created_at only (no updated_at, no version)
    id: str
    invoice_id: str
    member_id: str
    amount_cents: int
    posted_at: str
    credit_applied_cents: int
    created_at: str


class Telescope(TypedDict, total=False):
    id: str
    name: str
    equipment_class: str
    status: str
    collimation_due_at: str
    condition_score: int
    created_at: str
    updated_at: str
    version: int


class TrainingCertification(TypedDict, total=False):
    id: str
    member_id: str
    equipment_class: str
    issued_at: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LoanReservation(TypedDict, total=False):
    id: str
    member_id: str
    telescope_id: str
    window_start: str
    window_end: str
    status: str
    checkout_at: Optional[str]
    returned_at: Optional[str]
    overdue_fees_cents: int
    created_at: str
    updated_at: str
    version: int


class MaintenanceTicket(TypedDict, total=False):
    id: str
    telescope_id: str
    kind: str
    severity: str
    status: str
    opened_at: str
    closed_at: Optional[str]
    condition_delta: int
    created_at: str
    updated_at: str
    version: int


class ObservingEvent(TypedDict, total=False):
    id: str
    title: str
    event_kind: str
    window_start: str
    window_end: str
    status: str
    moon_illumination_pct: int
    weather_cancellation_pct: int
    min_operators: int
    confirmed_operator_count: int
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EventOperatorAssignment(TypedDict, total=False):
    id: str
    event_id: str
    member_id: str
    telescope_id: str
    status: str
    invited_at: str
    created_at: str
    updated_at: str
    version: int


class GroupVisitBooking(TypedDict, total=False):
    id: str
    event_id: str
    group_name: str
    party_size: int
    contact_member_id: str
    deposit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SkyQualityReading(TypedDict, total=False):
    # Append-only: id + created_at only (no updated_at, no version)
    id: str
    taken_by_member_id: str
    event_id: str
    sqm_value: float
    taken_at: str
    created_at: str


class DarkSkyReport(TypedDict, total=False):
    id: str
    period_start: str
    period_end: str
    status: str
    reading_count: int
    median_sqm: Optional[float]
    advocacy_grade: Optional[str]
    created_at: str
    updated_at: str
    version: int
