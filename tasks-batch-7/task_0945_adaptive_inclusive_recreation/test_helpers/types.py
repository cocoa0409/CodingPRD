"""Domain types: status enums, role enum and entity TypedDicts.

Two entities carry only `id` and `created_at` and have neither `updated_at`
nor `version`: FeeScaleBand and GoalRating (PRD 2.6).
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    INTAKE_COORDINATOR = "IntakeCoordinator"
    ACTIVITY_LEAD = "ActivityLead"
    FUNDING_OFFICER = "FundingOfficer"
    TRANSPORT_DISPATCHER = "TransportDispatcher"
    CAREGIVER_USER = "CaregiverUser"


class OperatingPeriodStatus(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class ParticipantStatus(str, Enum):
    INTAKE = "INTAKE"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    EXITED = "EXITED"


class SupportTier(str, Enum):
    INDEPENDENT = "INDEPENDENT"
    INTERMITTENT = "INTERMITTENT"
    SUBSTANTIAL = "SUBSTANTIAL"
    ONE_TO_ONE = "ONE_TO_ONE"


class SupportAssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class ConsentStatus(str, Enum):
    PENDING_SIGNATURE = "PENDING_SIGNATURE"
    SIGNED = "SIGNED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ConsentType(str, Enum):
    MEDIA_RELEASE = "MEDIA_RELEASE"
    EMERGENCY_MEDICAL = "EMERGENCY_MEDICAL"
    BEHAVIOR_SUPPORT_PLAN = "BEHAVIOR_SUPPORT_PLAN"
    MEDICATION_ADMIN = "MEDICATION_ADMIN"


class SessionStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    STAFFING_LOCKED = "STAFFING_LOCKED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class EnrollmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    WAITLISTED = "WAITLISTED"
    CONFIRMED = "CONFIRMED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"


class FundingStatus(str, Enum):
    QUOTED = "QUOTED"
    ENCUMBERED = "ENCUMBERED"
    DISBURSED = "DISBURSED"
    RELEASED = "RELEASED"
    UNFUNDED = "UNFUNDED"


class ChargeStatus(str, Enum):
    QUOTED = "QUOTED"
    OUTSTANDING = "OUTSTANDING"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class CertificationStatus(str, Enum):
    VALID = "VALID"
    EXPIRED = "EXPIRED"


class AssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    LAPSED = "LAPSED"
    WITHDRAWN = "WITHDRAWN"
    DELIVERED = "DELIVERED"


class ItemConditionStatus(str, Enum):
    SERVICEABLE = "SERVICEABLE"
    INSPECTION_DUE = "INSPECTION_DUE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    RETIRED = "RETIRED"


class ReservationStatus(str, Enum):
    HELD = "HELD"
    CHECKED_OUT = "CHECKED_OUT"
    RETURNED_GOOD = "RETURNED_GOOD"
    RETURNED_DAMAGED = "RETURNED_DAMAGED"
    RELEASED = "RELEASED"
    VOIDED_INSPECTION_FAIL = "VOIDED_INSPECTION_FAIL"


class TransportRunStatus(str, Enum):
    PLANNED = "PLANNED"
    BOARDING_FULL = "BOARDING_FULL"
    CANCELLED = "CANCELLED"


class TransportBookingStatus(str, Enum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    RIDDEN = "RIDDEN"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class FundingSourceStatus(str, Enum):
    OPEN = "OPEN"
    EXHAUSTED = "EXHAUSTED"
    CLOSED = "CLOSED"


class AwardStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ENCUMBERED = "ENCUMBERED"
    PARTIALLY_DISBURSED = "PARTIALLY_DISBURSED"
    DISBURSED = "DISBURSED"
    RELEASED = "RELEASED"
    LAPSED_NO_FUNDS = "LAPSED_NO_FUNDS"


class GoalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MASTERED = "MASTERED"
    DISCONTINUED = "DISCONTINUED"


class EnrollmentPosture(str, Enum):
    NOT_ACTIVE = "NOT_ACTIVE"
    CONSENT_BLOCKED = "CONSENT_BLOCKED"
    ASSESSMENT_STALE = "ASSESSMENT_STALE"
    FINANCIALLY_BLOCKED = "FINANCIALLY_BLOCKED"
    CLEARED = "CLEARED"


class Participant(TypedDict):
    id: str
    legal_name: str
    date_of_birth: str
    household_id: str
    household_size: int
    income_band: str
    weight_kg: int
    mobility_profile: str
    guardianship_status: str
    status: str
    age_years: int
    effective_support_tier: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProgramSession(TypedDict):
    id: str
    program_id: str
    start_at: str
    end_at: str
    sequence_number: int
    slot_capacity: int
    slots_committed: int
    slots_available: int
    one_to_one_pool_size: int
    one_to_one_committed: int
    one_to_one_available: int
    one_to_one_staffed: int
    assigned_group_staff_count: int
    required_group_staff_planned: int
    required_group_staff_delivered: Optional[int]
    staffing_gap: int
    unlock_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    participant_id: str
    session_id: str
    enrollment_status: str
    funding_status: str
    transport_requested: bool
    waitlist_score: int
    promoted_at: Optional[str]
    effective_support_tier_at_session: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EnrollmentCharge(TypedDict):
    id: str
    enrollment_id: str
    fee_scale_band_id: str
    program_fee_cents: int
    scholarship_applied_cents: int
    copay_cents: int
    transport_fee_cents: int
    sibling_discount_bp: int
    family_responsibility_cents: int
    amount_paid_cents: int
    balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields false — id + created_at only.
class FeeScaleBand(TypedDict):
    id: str
    household_size_min: int
    household_size_max: int
    income_band: str
    per_session_cents: int
    series_cents: int
    created_at: str


# common_fields false — id + created_at only.
class GoalRating(TypedDict):
    id: str
    goal_id: str
    session_id: str
    score: int
    note: str
    rated_by_staff_id: str
    rated_session_start_at: str
    created_at: str


__all__ = [n for n in dir() if not n.startswith("_")]
