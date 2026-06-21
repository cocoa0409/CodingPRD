"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity descriptions. Entities that carry the standard
system-managed fields (id, created_at, updated_at, version) per PRD §2.4 are
typed with all four; the Dependent resource carries only id and created_at
(PRD §2.4 — "neither an updated_at nor a version field").
"""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    CLAIMS_ADMIN = "ClaimsAdmin"
    RATING_SPECIALIST = "RatingSpecialist"
    SCHOOL_CERTIFYING_OFFICIAL = "SchoolCertifyingOfficial"
    VETERAN = "Veteran"


class AwardStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    DEVELOPMENT = "DEVELOPMENT"
    RATED = "RATED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    REMANDED = "REMANDED"
    CLOSED = "CLOSED"


class ClaimType(str, Enum):
    ORIGINAL = "ORIGINAL"
    INCREASE = "INCREASE"
    SECONDARY = "SECONDARY"


class ServiceConnection(str, Enum):
    PROPOSED = "PROPOSED"
    SERVICE_CONNECTED = "SERVICE_CONNECTED"
    NOT_CONNECTED = "NOT_CONNECTED"


class BodySide(str, Enum):
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    NONE = "NONE"


class DependentRelationship(str, Enum):
    SPOUSE = "SPOUSE"
    CHILD = "CHILD"
    PARENT = "PARENT"


class DependentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class EnrollmentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CERTIFIED = "CERTIFIED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class VocRehabStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


class VocRehabTrack(str, Enum):
    REEMPLOYMENT = "REEMPLOYMENT"
    EMPLOYMENT_THROUGH_LONG_TERM = "EMPLOYMENT_THROUGH_LONG_TERM"
    SELF_EMPLOYMENT = "SELF_EMPLOYMENT"


# ─── Entities with full system-managed fields (PRD §2.4) ───

class Veteran(TypedDict):
    id: str
    full_name: str
    file_number: str
    total_active_duty_days: int
    discharged_for_service_disability: bool
    combined_rating_pct: int
    provisional_combined_rating_pct: int
    gi_bill_tier_pct: int
    monthly_compensation_cents: int
    voc_rehab_entitlement_months: float
    award_status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    veteran_id: str
    claim_type: str
    received_date: str
    status: str
    remand_count: int
    created_at: str
    updated_at: str
    version: int


class Condition(TypedDict):
    id: str
    veteran_id: str
    claim_id: str
    diagnostic_code: str
    body_side: str
    is_extremity: bool
    proposed_rating_pct: int
    final_rating_pct: int
    service_connection: str
    created_at: str
    updated_at: str
    version: int


class School(TypedDict):
    id: str
    name: str
    is_public: bool
    yellow_ribbon_participant: bool
    yellow_ribbon_max_contribution_cents: int
    yellow_ribbon_slots_total: int
    yellow_ribbon_slots_used: int
    monthly_housing_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    veteran_id: str
    school_id: str
    term_start: str
    term_end: str
    credit_hours: float
    full_time_credit_hours: float
    tuition_charged_cents: int
    requests_yellow_ribbon: bool
    rate_of_pursuit_pct: int
    monthly_housing_allowance_cents: int
    estimated_mha_cents: int
    yellow_ribbon_match_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class VocRehabPlan(TypedDict):
    id: str
    veteran_id: str
    planned_months: float
    track: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Append-and-retire entity (PRD §2.4): id + created_at only ───

class Dependent(TypedDict):
    id: str
    veteran_id: str
    relationship: str
    in_school_18_to_23: bool
    status: str
    created_at: str
