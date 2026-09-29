"""Domain types for the Senior Games & Masters Competition API.

Entity shapes, lifecycle status enums and the role enum, all named exactly as
the PRD names them.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Dict, Any


# --------------------------------------------------------------------------
# Roles (PRD §2.1 — the seven role names the system recognises)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    GAMES_ADMIN = "GamesAdmin"
    REGISTRATION_OFFICER = "RegistrationOfficer"
    ATHLETE = "Athlete"
    MEDICAL_DIRECTOR = "MedicalDirector"
    SPORT_OFFICIAL = "SportOfficial"
    RECORDS_RATIFIER = "RecordsRatifier"
    SPONSOR_LIAISON = "SponsorLiaison"


ALL_ROLES = [r.value for r in UserRole]


# --------------------------------------------------------------------------
# Lifecycle status enums
# --------------------------------------------------------------------------
class GamesEditionStatus(str, Enum):
    DRAFT = "DRAFT"
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    REGISTRATION_CLOSED = "REGISTRATION_CLOSED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    IMPACT_FINALIZED = "IMPACT_FINALIZED"


class SportEventStatus(str, Enum):
    OPEN = "OPEN"
    SEEDED = "SEEDED"
    UNDERSUBSCRIBED = "UNDERSUBSCRIBED"
    SCHEDULE_HOLD = "SCHEDULE_HOLD"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class VenueStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class SessionSlotStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    DISPLACED = "DISPLACED"
    RELEASED = "RELEASED"


class AthleteRegistrationStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    REGISTERED = "REGISTERED"
    CHECKED_IN = "CHECKED_IN"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class AthleteMedicalStatus(str, Enum):
    NOT_SCREENED = "NOT_SCREENED"
    SCREENED_CLEARED = "SCREENED_CLEARED"
    SCREENED_RESTRICTED = "SCREENED_RESTRICTED"
    SCREENED_HOLD = "SCREENED_HOLD"
    CLEARED_BY_APPEAL = "CLEARED_BY_APPEAL"


class SportEntryStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    ACCEPTED = "ACCEPTED"
    WAITLISTED = "WAITLISTED"
    MEDICAL_HOLD = "MEDICAL_HOLD"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class PersonnelAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"
    NO_SHOW = "NO_SHOW"


class CompetitionResultStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    RECORD_PENDING = "RECORD_PENDING"
    PUBLISHED = "PUBLISHED"
    PROTESTED = "PROTESTED"
    VOIDED = "VOIDED"


class AgeGroupRecordStatus(str, Enum):
    PENDING_RATIFICATION = "PENDING_RATIFICATION"
    RATIFIED = "RATIFIED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class VillageStayStatus(str, Enum):
    RESERVED = "RESERVED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SponsorshipCommitmentStatus(str, Enum):
    PLEDGED = "PLEDGED"
    ALLOCATED = "ALLOCATED"
    WITHDRAWN = "WITHDRAWN"


# --------------------------------------------------------------------------
# Value enums
# --------------------------------------------------------------------------
class AgeBasis(str, Enum):
    REFERENCE_DATE = "REFERENCE_DATE"
    FIRST_COMPETITION_DAY = "FIRST_COMPETITION_DAY"


class ContactClass(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class MarkDirection(str, Enum):
    LOWER_IS_BETTER = "LOWER_IS_BETTER"
    HIGHER_IS_BETTER = "HIGHER_IS_BETTER"


class GenderDivision(str, Enum):
    MEN = "MEN"
    WOMEN = "WOMEN"
    MIXED = "MIXED"


class EmergencyProtocolCode(str, Enum):
    EP_BASIC = "EP_BASIC"
    EP_ADVANCED = "EP_ADVANCED"
    EP_CARDIAC = "EP_CARDIAC"


class MeetLevel(str, Enum):
    LOCAL = "LOCAL"
    STATE = "STATE"


class QualificationSource(str, Enum):
    STATE_QUALIFIER = "STATE_QUALIFIER"
    LOCAL_QUALIFIER = "LOCAL_QUALIFIER"
    AGE_EXEMPT = "AGE_EXEMPT"
    ORGANIZER_INVITE = "ORGANIZER_INVITE"


class ReviewDecision(str, Enum):
    TAKE_UP = "TAKE_UP"
    ACCEPT = "ACCEPT"
    WAITLIST = "WAITLIST"
    REQUEST_REVISION = "REQUEST_REVISION"
    REJECT = "REJECT"


class PersonnelType(str, Enum):
    OFFICIAL = "OFFICIAL"
    VOLUNTEER = "VOLUNTEER"


class RoleAtEvent(str, Enum):
    CHIEF_JUDGE = "CHIEF_JUDGE"
    JUDGE = "JUDGE"
    TIMER = "TIMER"
    MARSHAL = "MARSHAL"
    RUNNER = "RUNNER"


class Recommendation(str, Enum):
    CLEARED = "CLEARED"
    CLEARED_WITH_RESTRICTION = "CLEARED_WITH_RESTRICTION"
    HOLD_PENDING_PHYSICIAN_REVIEW = "HOLD_PENDING_PHYSICIAN_REVIEW"


class SponsorKind(str, Enum):
    CORPORATE = "CORPORATE"
    MUNICIPAL = "MUNICIPAL"
    FOUNDATION = "FOUNDATION"


class SponsorTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class RecognitionBucket(str, Enum):
    VENUE_SIGNAGE = "VENUE_SIGNAGE"
    ATHLETE_SERVICES = "ATHLETE_SERVICES"
    MEDICAL_COVERAGE = "MEDICAL_COVERAGE"
    SOCIAL_PROGRAM = "SOCIAL_PROGRAM"


# --------------------------------------------------------------------------
# Entity shapes.
#
# Resources carrying the four server-managed properties (PRD §2.5) list
# id / created_at / updated_at / version.  The two immutable resources —
# QualifyingResult and MedicalScreening — expose only id and created_at.
# --------------------------------------------------------------------------
class GamesEdition(TypedDict):
    id: str
    name: str
    host_city: str
    host_state_code: str
    competition_start_date: str
    competition_end_date: str
    age_reference_date: str
    age_basis: str
    registration_deadline_utc: str
    municipal_support_cents: int
    status: str
    ops_epoch: int
    sponsorship_recognized_cents: int
    provisional_impact_cents: int
    final_impact_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Sport(TypedDict):
    id: str
    sport_code: str
    name: str
    contact_class: str
    mark_direction: str
    required_certification_level: int
    min_age: int
    equipment_profile: Dict[str, Any]
    format_modifications: Dict[str, Any]
    created_at: str
    updated_at: str
    version: int


class SportEvent(TypedDict):
    id: str
    sport_id: str
    games_edition_id: str
    event_code: str
    age_group_code: str
    gender_division: str
    entry_fee_cents: int
    capacity: int
    min_entries_to_stage: int
    national_qualifying_standard: Optional[float]
    accepted_entry_count: int
    available_slots: int
    current_record_id: Optional[str]
    status: str
    seeded_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict):
    id: str
    games_edition_id: str
    name: str
    competition_area_count: int
    spectator_capacity: int
    has_onsite_medical_bay: bool
    emergency_protocol_code: str
    status: str
    closed_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SessionSlot(TypedDict):
    id: str
    venue_id: str
    sport_event_id: str
    start_utc: str
    end_utc: str
    teardown_buffer_minutes: int
    required_official_count: int
    confirmed_official_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Athlete(TypedDict):
    id: str
    games_edition_id: str
    full_name: str
    email: str
    date_of_birth: str
    residency_state_code: str
    age_at_reference: int
    age_at_first_day: int
    age_group_code: str
    registration_status: str
    medical_status: str
    fee_total_cents: int
    fee_paid_cents: int
    fee_breakdown: Dict[str, Any]
    created_at: str
    updated_at: str
    version: int


# Immutable row (PRD §2.5): only id and created_at.
class QualifyingResult(TypedDict):
    id: str
    athlete_id: str
    sport_id: str
    event_code: str
    mark_value: float
    meet_date: str
    meet_level: str
    sanctioned: bool
    created_at: str


class SportEntry(TypedDict):
    id: str
    athlete_id: str
    sport_event_id: str
    qualifying_result_id: Optional[str]
    qualification_source: str
    qualification_priority: int
    qualifying_mark: Optional[float]
    revision_round: int
    review_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Immutable row (PRD §2.5): only id and created_at.
class MedicalScreening(TypedDict):
    id: str
    athlete_id: str
    screened_by_user_id: str
    systolic_bp: int
    resting_hr: int
    prior_cardiac_event: bool
    contact_sport_count: int
    risk_score: float
    recommendation: str
    screened_at_utc: str
    created_at: str


class Personnel(TypedDict):
    id: str
    games_edition_id: str
    full_name: str
    personnel_type: str
    certification_level: int
    certified_sport_codes: List[str]
    assigned_minutes_total: int
    no_show_count: int
    created_at: str
    updated_at: str
    version: int


class PersonnelAssignment(TypedDict):
    id: str
    personnel_id: str
    session_slot_id: str
    role_at_event: str
    duration_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CompetitionResult(TypedDict):
    id: str
    sport_entry_id: str
    session_slot_id: str
    submitted_by_personnel_id: str
    mark_value: float
    placement: int
    verified_by_user_id: Optional[str]
    national_qualifying: bool
    protest_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AgeGroupRecord(TypedDict):
    id: str
    sport_event_id: str
    competition_result_id: str
    holder_athlete_id: str
    superseded_record_id: Optional[str]
    age_group_code: str
    mark_value: float
    claimed_by_user_id: str
    ratified_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AccommodationBlock(TypedDict):
    id: str
    games_edition_id: str
    name: str
    bed_capacity: int
    nightly_rate_cents: int
    accessible_units: int
    reserved_bed_nights: int
    created_at: str
    updated_at: str
    version: int


class VillageStay(TypedDict):
    id: str
    athlete_id: str
    accommodation_block_id: str
    check_in_date: str
    check_out_date: str
    nights: int
    total_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SponsorshipCommitment(TypedDict):
    id: str
    games_edition_id: str
    sponsor_name: str
    sponsor_kind: str
    tier: str
    pledged_cents: int
    recognized_cents: int
    allocation_map: Dict[str, int]
    status: str
    created_at: str
    updated_at: str
    version: int
