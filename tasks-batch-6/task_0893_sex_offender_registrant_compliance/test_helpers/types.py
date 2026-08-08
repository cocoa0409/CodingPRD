"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    REGISTRY_ADMIN = "RegistryAdmin"
    REGISTRATION_OFFICER = "RegistrationOfficer"
    COMPLIANCE_REVIEWER = "ComplianceReviewer"
    REGISTRANT = "Registrant"


class JurisdictionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class RegistrantStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"
    ABSCONDER = "ABSCONDER"
    DEREGISTERED = "DEREGISTERED"


class RegistrantTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class OffenseClass(str, Enum):
    CLASS_A = "CLASS_A"
    CLASS_B = "CLASS_B"
    CLASS_C = "CLASS_C"


class AddressType(str, Enum):
    RESIDENCE = "RESIDENCE"
    EMPLOYMENT = "EMPLOYMENT"
    SCHOOL = "SCHOOL"
    TEMPORARY = "TEMPORARY"


class AddressStatus(str, Enum):
    VERIFIED = "VERIFIED"
    HISTORICAL = "HISTORICAL"


class VerificationType(str, Enum):
    INITIAL = "INITIAL"
    PERIODIC = "PERIODIC"
    ADDRESS_CHANGE = "ADDRESS_CHANGE"


class VerificationMethod(str, Enum):
    IN_PERSON = "IN_PERSON"
    MAIL = "MAIL"


class FlagType(str, Enum):
    LATE_VERIFICATION = "LATE_VERIFICATION"
    UNREPORTED_MOVE = "UNREPORTED_MOVE"
    EXCLUSION_VIOLATION = "EXCLUSION_VIOLATION"
    TRAVEL_VIOLATION = "TRAVEL_VIOLATION"
    ABSCONDED = "ABSCONDED"


class FlagSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class FlagStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class ExclusionZoneType(str, Enum):
    SCHOOL = "SCHOOL"
    PARK = "PARK"
    DAYCARE = "DAYCARE"


class TravelType(str, Enum):
    TEMPORARY = "TEMPORARY"
    RELOCATION = "RELOCATION"


class TravelNoticeStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    OVERDUE = "OVERDUE"
    CANCELLED = "CANCELLED"


class AudienceScope(str, Enum):
    LAW_ENFORCEMENT = "LAW_ENFORCEMENT"
    SCHOOLS_ONLY = "SCHOOLS_ONLY"
    PUBLIC = "PUBLIC"


class PetitionType(str, Enum):
    DEREGISTER = "DEREGISTER"
    TIER_REDUCTION = "TIER_REDUCTION"


class PetitionDecision(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


# --- Entities with common_fields: true (id, created_at, updated_at, version) ---

class Jurisdiction(TypedDict):
    id: str
    name: str
    state_code: str
    verification_grace_days: int
    est_households_per_notification: int
    status: str
    active_registrant_count: int
    active_travel_hold_count: int
    created_at: str
    updated_at: str
    version: int


class ExclusionZone(TypedDict):
    id: str
    jurisdiction_id: str
    name: str
    zone_type: str
    center_x: int
    center_y: int
    radius_meters: int
    buffer_meters: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Registrant(TypedDict):
    id: str
    jurisdiction_id: str
    full_name: str
    date_of_birth: str
    initial_registration_date: Optional[str]
    tier: Optional[str]
    tier_score: Optional[int]
    verification_interval_days: Optional[int]
    last_verified_date: Optional[str]
    next_verification_due: Optional[str]
    risk_score: int
    current_residence_address_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Address(TypedDict):
    id: str
    registrant_id: str
    address_type: str
    line1: str
    city: str
    state_code: str
    postal_code: str
    grid_x: int
    grid_y: int
    effective_from: Optional[str]
    effective_to: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceFlag(TypedDict):
    id: str
    registrant_id: str
    flag_type: str
    severity: str
    base_points: int
    opened_date: str
    resolved_date: Optional[str]
    status: str
    note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TravelNotice(TypedDict):
    id: str
    registrant_id: str
    destination_jurisdiction_id: str
    travel_type: str
    departure_date: str
    return_date: Optional[str]
    decision_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Petition(TypedDict):
    id: str
    registrant_id: str
    petition_type: str
    filed_date: str
    adjudicated_risk_score: int
    eligibility_met: bool
    reviewer_ref: Optional[str]
    decided_date: Optional[str]
    decision: str
    created_at: str
    updated_at: str
    version: int


# --- Entities with common_fields: false (id + created_at only) ---

class Offense(TypedDict):
    id: str
    registrant_id: str
    statute_code: str
    offense_class: str
    is_aggravated: bool
    victim_minor: bool
    conviction_date: str
    offense_points: int
    created_at: str


class VerificationEvent(TypedDict):
    id: str
    registrant_id: str
    verification_type: str
    method: str
    officer_ref: str
    completed_date: str
    result: str
    created_at: str


class NotificationRecord(TypedDict):
    id: str
    registrant_id: str
    audience_scope: str
    radius_meters: int
    estimated_recipients: int
    actual_recipients: int
    dispatched_date: str
    created_at: str
