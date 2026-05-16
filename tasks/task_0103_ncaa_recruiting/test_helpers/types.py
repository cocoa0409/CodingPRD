"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 distinguishes two common-fields shapes:

- Entities with the four common properties (id, created_at, updated_at,
  version): Program, Athlete, ScholarshipSlot, NILDeal,
  TransferPortalEntry, ComplianceViolation.
- Append-only entities that carry ONLY id and created_at:
  RecruitingCalendar, RecruitingContact, EligibilityRecord.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    COACH = "Coach"
    ATHLETE = "Athlete"
    BOOSTER = "Booster"
    AUDITOR = "Auditor"


# ---------------------------------------------------------------------------
# Enums for Program — PRD §3.1
# ---------------------------------------------------------------------------
class Sport(str, Enum):
    FOOTBALL = "FOOTBALL"
    MENS_BASKETBALL = "MENS_BASKETBALL"
    WOMENS_BASKETBALL = "WOMENS_BASKETBALL"
    BASEBALL = "BASEBALL"
    SOFTBALL = "SOFTBALL"


class Division(str, Enum):
    DI = "DI"
    DII = "DII"
    DIII = "DIII"


class ComplianceStatus(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


# ---------------------------------------------------------------------------
# Enums for Athlete — PRD §3.2
# ---------------------------------------------------------------------------
class AthleteStatus(str, Enum):
    PROSPECTIVE = "PROSPECTIVE"
    COMMITTED = "COMMITTED"
    ENROLLED = "ENROLLED"
    TRANSFER_PORTAL = "TRANSFER_PORTAL"
    INELIGIBLE = "INELIGIBLE"


class AmateurStatus(str, Enum):
    AMATEUR = "AMATEUR"
    AT_RISK = "AT_RISK"
    FORFEITED = "FORFEITED"


# ---------------------------------------------------------------------------
# Enums for EligibilityRecord — PRD §3.2
# ---------------------------------------------------------------------------
class EligibilityDecision(str, Enum):
    QUALIFIER = "QUALIFIER"
    PARTIAL_QUALIFIER = "PARTIAL_QUALIFIER"
    NON_QUALIFIER = "NON_QUALIFIER"
    INCOMPLETE = "INCOMPLETE"


# ---------------------------------------------------------------------------
# Enums for RecruitingCalendar / RecruitingContact — PRD §3.1, §3.8
# ---------------------------------------------------------------------------
class CalendarPeriodType(str, Enum):
    QUIET = "QUIET"
    CONTACT = "CONTACT"
    DEAD = "DEAD"
    EVALUATION = "EVALUATION"


class ContactType(str, Enum):
    PHONE_CALL = "PHONE_CALL"
    IN_PERSON_OFF_CAMPUS = "IN_PERSON_OFF_CAMPUS"
    IN_PERSON_ON_CAMPUS = "IN_PERSON_ON_CAMPUS"
    TEXT_MESSAGE = "TEXT_MESSAGE"
    EVALUATION = "EVALUATION"


# ---------------------------------------------------------------------------
# Enums for ScholarshipSlot — PRD §3.3
# ---------------------------------------------------------------------------
class ScholarshipSlotStatus(str, Enum):
    OFFERED = "OFFERED"
    SIGNED = "SIGNED"
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"
    RELEASED = "RELEASED"
    REVOKED = "REVOKED"


# ---------------------------------------------------------------------------
# Enums for NILDeal — PRD §3.5, §3.6
# ---------------------------------------------------------------------------
class NILDealStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class DealCategory(str, Enum):
    ENDORSEMENT = "ENDORSEMENT"
    APPEARANCE = "APPEARANCE"
    SOCIAL_MEDIA_POST = "SOCIAL_MEDIA_POST"
    AUTOGRAPH_SIGNING = "AUTOGRAPH_SIGNING"
    CAMP_INSTRUCTION = "CAMP_INSTRUCTION"


# ---------------------------------------------------------------------------
# Enums for TransferPortalEntry — PRD §3.4
# ---------------------------------------------------------------------------
class PortalEntryStatus(str, Enum):
    ENTERED = "ENTERED"
    CONTACT_WINDOW = "CONTACT_WINDOW"
    COMMITTED = "COMMITTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class PortalReason(str, Enum):
    PLAYING_TIME = "PLAYING_TIME"
    COACHING_CHANGE = "COACHING_CHANGE"
    FAMILY = "FAMILY"
    ACADEMIC = "ACADEMIC"
    OTHER = "OTHER"


# ---------------------------------------------------------------------------
# Enums for ComplianceViolation — PRD §3.7
# ---------------------------------------------------------------------------
class ViolationStatus(str, Enum):
    REPORTED = "REPORTED"
    INVESTIGATING = "INVESTIGATING"
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"
    APPEALED = "APPEALED"
    SUSTAINED = "SUSTAINED"
    OVERTURNED = "OVERTURNED"


class ViolationOutcome(str, Enum):
    PENDING = "PENDING"
    SUSTAINED = "SUSTAINED"
    CLEARED = "CLEARED"


class ViolationSeverity(str, Enum):
    LEVEL_I = "LEVEL_I"
    LEVEL_II = "LEVEL_II"
    LEVEL_III = "LEVEL_III"
    LEVEL_IV = "LEVEL_IV"


class ViolationSubjectType(str, Enum):
    BOOSTER = "BOOSTER"
    COACH = "COACH"
    ATHLETE = "ATHLETE"
    PROGRAM_ADMIN = "PROGRAM_ADMIN"


class ViolationType(str, Enum):
    IMPERMISSIBLE_BENEFIT = "IMPERMISSIBLE_BENEFIT"
    RECRUITING_CONTACT = "RECRUITING_CONTACT"
    NIL_COLLECTIVE_PAYFORPLAY = "NIL_COLLECTIVE_PAYFORPLAY"
    ACADEMIC_FRAUD = "ACADEMIC_FRAUD"
    OTHER = "OTHER"


# ---------------------------------------------------------------------------
# Entities carrying the four common fields (id, created_at, updated_at, version)
# ---------------------------------------------------------------------------
class Program(TypedDict, total=False):
    id: str
    institution_name: str
    sport: str
    division: str
    scholarship_cap_equivalencies: float
    roster_cap_count: int
    total_equivalencies_used: float
    active_roster_count: int
    compliance_status: str
    penalty_points_total: int
    created_at: str
    updated_at: str
    version: int


class Athlete(TypedDict, total=False):
    id: str
    full_name: str
    high_school: str
    graduation_year: int
    status: str
    current_program_id: Optional[str]
    eligibility_record_id: Optional[str]
    amateur_status: str
    years_of_eligibility_remaining: int
    nil_deal_lifetime_value_cents: int
    created_at: str
    updated_at: str
    version: int


class ScholarshipSlot(TypedDict, total=False):
    id: str
    program_id: str
    athlete_id: str
    fractional_equivalency: float
    annual_value_cents: int
    status: str
    signed_at: Optional[str]
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NILDeal(TypedDict, total=False):
    id: str
    athlete_id: str
    sponsor_name: str
    sponsor_is_booster: bool
    deal_category: str
    stated_value_cents: int
    deliverables_hours: float
    market_rate_cents_per_hour: int
    fmv_calculated_cents: int
    pay_for_play_flag: bool
    approved_value_cents: Optional[int]
    status: str
    review_started_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransferPortalEntry(TypedDict, total=False):
    id: str
    athlete_id: str
    origin_program_id: str
    destination_program_id: Optional[str]
    entered_at: str
    window_closes_at: str
    reason: str
    status: str
    immediate_eligibility: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class ComplianceViolation(TypedDict, total=False):
    id: str
    program_id: str
    subject_type: str
    subject_ref: str
    violation_type: str
    severity: str
    related_athlete_id: Optional[str]
    related_deal_id: Optional[str]
    status: str
    outcome: str
    penalty_points: int
    reviewer_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities — id + created_at ONLY (no updated_at, no version per
# PRD §2.4: "the RecruitingCalendar (an immutable window declaration) and the
# RecruitingContact (an immutable contact event log). Likewise, the
# EligibilityRecord is append-only").
# ---------------------------------------------------------------------------
class RecruitingCalendar(TypedDict, total=False):
    id: str
    program_id: str
    period_type: str
    start_date: str
    end_date: str
    note: Optional[str]
    created_at: str


class RecruitingContact(TypedDict, total=False):
    id: str
    program_id: str
    athlete_id: str
    contact_type: str
    contact_at: str
    contact_period_type: str
    was_permitted: bool
    created_at: str


class EligibilityRecord(TypedDict, total=False):
    id: str
    athlete_id: str
    core_gpa: float
    standardized_test_score: int
    core_courses_completed: int
    decision: str
    decided_at: str
    created_at: str


__all__ = [
    "UserRole",
    "Sport",
    "Division",
    "ComplianceStatus",
    "AthleteStatus",
    "AmateurStatus",
    "EligibilityDecision",
    "CalendarPeriodType",
    "ContactType",
    "ScholarshipSlotStatus",
    "NILDealStatus",
    "DealCategory",
    "PortalEntryStatus",
    "PortalReason",
    "ViolationStatus",
    "ViolationOutcome",
    "ViolationSeverity",
    "ViolationSubjectType",
    "ViolationType",
    "Program",
    "Athlete",
    "ScholarshipSlot",
    "NILDeal",
    "TransferPortalEntry",
    "ComplianceViolation",
    "RecruitingCalendar",
    "RecruitingContact",
    "EligibilityRecord",
]
