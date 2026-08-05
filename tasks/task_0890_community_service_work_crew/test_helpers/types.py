"""Domain types: entity TypedDicts, status enums, and the role enum.

Derived from the PRD's resource definitions. Two resources — ComplianceAction and
Certificate — are immutable append-only records that carry only ``id`` and
``created_at`` (no ``updated_at``, no ``version``); their TypedDicts omit those fields.
"""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------- roles
class UserRole(str, Enum):
    COURT_CLERK = "CourtClerk"
    PROGRAM_COORDINATOR = "ProgramCoordinator"
    SITE_SUPERVISOR = "SiteSupervisor"
    PARTICIPANT = "Participant"


# --------------------------------------------------------------------------- enums
class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AgencyType(str, Enum):
    NONPROFIT = "NONPROFIT"
    GOVERNMENT = "GOVERNMENT"
    FAITH_BASED = "FAITH_BASED"
    OTHER = "OTHER"


class SiteStatus(str, Enum):
    PROSPECTIVE = "PROSPECTIVE"
    ACCEPTING = "ACCEPTING"
    PAUSED = "PAUSED"


class InsuranceStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class OffenseClass(str, Enum):
    INFRACTION = "INFRACTION"
    MISDEMEANOR = "MISDEMEANOR"
    FELONY = "FELONY"


class IndigencyStatus(str, Enum):
    NONE = "NONE"
    PARTIAL = "PARTIAL"
    FULL = "FULL"


class ReferralStatus(str, Enum):
    ACTIVE = "ACTIVE"
    NON_COMPLIANT = "NON_COMPLIANT"
    COMPLETED = "COMPLETED"
    CONVERTED = "CONVERTED"
    TERMINATED = "TERMINATED"


class PlacementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class SessionCategory(str, Enum):
    STANDARD = "STANDARD"
    WEEKEND_CREW = "WEEKEND_CREW"
    ALTERNATIVE = "ALTERNATIVE"


class AttendanceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    VOIDED = "VOIDED"


class VerificationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    REJECTED = "REJECTED"


class FeeConversionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"
    REVERSED = "REVERSED"


class ComplianceActionType(str, Enum):
    WARNING = "WARNING"
    REPORT_BACK = "REPORT_BACK"


# ---------------------------------------------------------------------- entities
class Participant(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    contact_email: str
    risk_level: str
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict):
    id: str
    name: str
    agency_type: str
    address: str
    capacity_slots: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict):
    id: str
    site_id: str
    carrier: str
    coverage_amount_cents: int
    effective_date: str
    expiry_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Supervisor(TypedDict):
    id: str
    site_id: str
    full_name: str
    max_concurrent_participants: int
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    participant_id: str
    court_case_number: str
    offense_class: str
    hours_ordered: float
    deadline_date: str
    indigency_status: str
    hours_completed: float
    hours_converted: float
    hours_outstanding: float
    fees_settled_cents: int
    certificate_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Placement(TypedDict):
    id: str
    referral_id: str
    site_id: str
    supervisor_id: str
    waiver_signed: bool
    waiver_signed_at: Optional[str]
    waiver_signature_name: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkSession(TypedDict):
    id: str
    placement_id: str
    participant_id: str
    site_id: str
    session_category: str
    scheduled_start: str
    scheduled_end: str
    check_in_at: Optional[str]
    check_out_at: Optional[str]
    claimed_hours: Optional[float]
    verified_hours: Optional[float]
    attendance_status: str
    verification_status: str
    created_at: str
    updated_at: str
    version: int


class FeeConversion(TypedDict):
    id: str
    referral_id: str
    hours_to_convert: float
    indigency_status_snapshot: str
    quoted_fee_cents: int
    settlement_fee_cents: Optional[int]
    settled_hours: Optional[float]
    requested_by_user_id: str
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# append-only (id + created_at only)
class ComplianceAction(TypedDict):
    id: str
    referral_id: str
    action_type: str
    reason: str
    filed_by_user_id: str
    resulting_referral_status: str
    created_at: str


class Certificate(TypedDict):
    id: str
    referral_id: str
    certificate_number: str
    total_hours_credited: float
    issued_at: str
    created_at: str
