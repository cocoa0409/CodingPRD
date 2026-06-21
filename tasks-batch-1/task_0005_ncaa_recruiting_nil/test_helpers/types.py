"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional


# ─── Role enum (PRD §2.1) ──────────────────────────────


class UserRole(str, Enum):
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    COACH = "Coach"
    STUDENT_ATHLETE = "StudentAthlete"
    NIL_REVIEWER = "NILReviewer"
    ELIGIBILITY_CENTER = "EligibilityCenter"


# ─── Status / enum types (PRD §3) ──────────────────────


class SportCode(str, Enum):
    FOOTBALL = "FOOTBALL"
    MBB = "MBB"
    WBB = "WBB"
    BASEBALL = "BASEBALL"
    SOFTBALL = "SOFTBALL"


class PeriodType(str, Enum):
    CONTACT = "CONTACT"
    QUIET = "QUIET"
    DEAD = "DEAD"


class ContactChannel(str, Enum):
    IN_PERSON = "IN_PERSON"
    PHONE = "PHONE"
    DM = "DM"
    EMAIL = "EMAIL"


class EligibilityStatus(str, Enum):
    UNCERTIFIED = "UNCERTIFIED"
    CERTIFIED = "CERTIFIED"
    INELIGIBLE = "INELIGIBLE"


class EligibilityCertificationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class DenialReason(str, Enum):
    GPA_BELOW_MIN = "GPA_BELOW_MIN"
    AMATEURISM_LOST = "AMATEURISM_LOST"
    INCOMPLETE_RECORDS = "INCOMPLETE_RECORDS"


class ScholarshipOfferStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class NILDealStatus(str, Enum):
    PROPOSED = "PROPOSED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class NILDealTier(str, Enum):
    DE_MINIMIS = "DE_MINIMIS"
    STANDARD = "STANDARD"
    HIGH_VALUE = "HIGH_VALUE"


class NILRejectionReason(str, Enum):
    BRAND_PROHIBITED = "BRAND_PROHIBITED"
    ATHLETE_INELIGIBLE = "ATHLETE_INELIGIBLE"
    EXCEEDS_PROGRAM_LIMIT = "EXCEEDS_PROGRAM_LIMIT"


class TransferPortalEntryStatus(str, Enum):
    ENTERED = "ENTERED"
    MATCHED = "MATCHED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class BoosterIncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    INVESTIGATING = "INVESTIGATING"
    SUSTAINED = "SUSTAINED"
    DISMISSED = "DISMISSED"


class PenaltyTier(str, Enum):
    NONE = "NONE"
    LEVEL_I = "LEVEL_I"
    LEVEL_II = "LEVEL_II"
    POSTSEASON_BAN = "POSTSEASON_BAN"


# ─── Entity TypedDicts (PRD §2.4, §3) ───────────────────
# Every primary resource carries id, created_at, updated_at, version per PRD §2.4.


class Program(TypedDict):
    id: str
    sport_code: str
    school_name: str
    scholarship_slot_cap: int
    slots_committed: int
    slots_projected: int
    penalty_tier: str
    created_at: str
    updated_at: str
    version: int


class Period(TypedDict):
    id: str
    program_id: str
    period_type: str
    starts_at: str
    ends_at: str
    created_at: str
    updated_at: str
    version: int


class StudentAthlete(TypedDict):
    id: str
    full_name: str
    sport_code: str
    gpa: float
    amateurism_flag: bool
    enrolled_program_id: Optional[str]
    eligibility_status: str
    in_transfer_portal: bool
    created_at: str
    updated_at: str
    version: int


class EligibilityCertification(TypedDict):
    id: str
    student_athlete_id: str
    status: str
    gpa_at_review: float
    amateurism_at_review: bool
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecruitingContact(TypedDict):
    id: str
    program_id: str
    student_athlete_id: str
    coach_user_id: str
    contact_at: str
    channel: str
    period_type_at_contact: str
    created_at: str
    updated_at: str
    version: int


class ScholarshipOffer(TypedDict):
    id: str
    program_id: str
    student_athlete_id: str
    status: str
    annual_value_cents: int
    sent_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NILDeal(TypedDict):
    id: str
    student_athlete_id: str
    brand_name: str
    gross_value_cents: int
    agent_fee_pct: float
    net_value_cents: int
    tier: str
    review_round: int
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransferPortalEntry(TypedDict):
    id: str
    student_athlete_id: str
    source_program_id: str
    matched_program_id: Optional[str]
    entered_at: str
    window_closes_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BoosterIncident(TypedDict):
    id: str
    program_id: str
    booster_name: str
    student_athlete_id: str
    alleged_value_cents: int
    severity_weight: int
    status: str
    created_at: str
    updated_at: str
    version: int
