"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entities and their lifecycles. Entities that carry the full
mutable field set expose id/created_at/updated_at/version; the append-only ExitRecord
carries only id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    INTAKE_SPECIALIST = "IntakeSpecialist"
    SHELTER_MANAGER = "ShelterManager"
    HOUSING_NAVIGATOR = "HousingNavigator"
    HMIS_ADMIN = "HMISAdmin"


# ─── Status enums ─────────────────────────────────────────────────────────────
class ClientStatus(str, Enum):
    INTAKE = "INTAKE"
    ACTIVE = "ACTIVE"
    HOUSED = "HOUSED"
    INACTIVE = "INACTIVE"
    MERGED = "MERGED"


class AcuityTier(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


class RecommendedTrack(str, Enum):
    PREVENTION = "PREVENTION"
    RRH = "RRH"
    PSH = "PSH"


class ConsentStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class ConsentScope(str, Enum):
    SHARE_ALL = "SHARE_ALL"
    SHARE_LIMITED = "SHARE_LIMITED"


class ScreeningStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class ScreeningOutcome(str, Enum):
    DIVERTED = "DIVERTED"
    PROCEED_TO_SHELTER = "PROCEED_TO_SHELTER"
    PROCEED_TO_PRIORITIZATION = "PROCEED_TO_PRIORITIZATION"


class ProjectType(str, Enum):
    ES = "ES"
    TH = "TH"


class BedStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OFFLINE = "OFFLINE"


class ReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class WaitlistStatus(str, Enum):
    WAITING = "WAITING"
    PROMOTED = "PROMOTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class PrioritizationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MATCHED = "MATCHED"
    HOUSED = "HOUSED"
    DEFERRED = "DEFERRED"
    REMOVED = "REMOVED"


class ReferralStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    ENROLLED = "ENROLLED"
    EXPIRED = "EXPIRED"


class ExitDestination(str, Enum):
    PERMANENT_HOUSING = "PERMANENT_HOUSING"
    RRH = "RRH"
    TEMP_FAMILY = "TEMP_FAMILY"
    INSTITUTION = "INSTITUTION"
    EMERGENCY_SHELTER = "EMERGENCY_SHELTER"
    STREET = "STREET"
    UNKNOWN = "UNKNOWN"


class ExitOutcome(str, Enum):
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE = "NEGATIVE"


# ─── Entity TypedDicts (common_fields: true carry version + updated_at) ────────
class Client(TypedDict):
    id: str
    full_name: str
    dob: str
    ssn_last4: Optional[str]
    household_size: int
    months_homeless: int
    chronic_homeless: bool
    status: str
    master_client_id: Optional[str]
    vulnerability_score: Optional[int]
    acuity_tier: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict):
    id: str
    client_id: str
    tool: str
    self_report_points: int
    verification_delta: int
    provisional_score: Optional[int]
    verified_score: Optional[int]
    recommended_track: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ROIConsent(TypedDict):
    id: str
    client_id: str
    scope: str
    effective_date: str
    expiry_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DiversionScreening(TypedDict):
    id: str
    client_id: str
    has_safe_alternative: bool
    is_fleeing_dv: bool
    outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Shelter(TypedDict):
    id: str
    name: str
    project_type: str
    total_beds: int
    available_beds: int
    created_at: str
    updated_at: str
    version: int


class Bed(TypedDict):
    id: str
    shelter_id: str
    label: str
    status: str
    current_reservation_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BedReservation(TypedDict):
    id: str
    client_id: str
    shelter_id: str
    bed_id: str
    entry_date: str
    expected_exit_date: str
    exit_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict):
    id: str
    shelter_id: str
    client_id: str
    entry_date: str
    expected_exit_date: str
    priority_score: int
    promoted_reservation_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PrioritizationEntry(TypedDict):
    id: str
    client_id: str
    rank_score: int
    deferred_until: Optional[str]
    matched_referral_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class HousingNavigator(TypedDict):
    id: str
    name: str
    max_caseload: int
    current_caseload: int
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    client_id: str
    prioritization_entry_id: str
    navigator_id: str
    psh_project_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


# append-only outcome record: id + created_at only (no updated_at, no version)
class ExitRecord(TypedDict):
    id: str
    client_id: str
    reservation_id: Optional[str]
    referral_id: Optional[str]
    destination: str
    outcome: str
    bed_nights: int
    created_at: str
