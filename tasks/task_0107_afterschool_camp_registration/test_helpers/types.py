"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 distinguishes two common-fields shapes:

- Entities that participate in update workflows carry id, created_at,
  updated_at, version (PRD §2.4: "Every entity that participates in
  update workflows — Family, Guardian, Child, EmergencyContact, Session,
  Enrollment, ScholarshipAward — carries four system-managed properties:
  id, created_at, updated_at, and version").

- Authorization and SessionDay are leaner — they carry only id and
  created_at (PRD §2.4: "Authorization and SessionDay carry only id and
  created_at — both updated_at and version are absent on these rows").
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    GUARDIAN = "Guardian"


# ---------------------------------------------------------------------------
# Enums for entity fields — PRD §2.12
# ---------------------------------------------------------------------------
class SessionStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class SessionKind(str, Enum):
    AFTERSCHOOL = "AFTERSCHOOL"
    SUMMER_CAMP = "SUMMER_CAMP"


class EnrollmentStatus(str, Enum):
    PENDING_AUTH = "PENDING_AUTH"
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class AuthorizationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class AuthorizationKind(str, Enum):
    MEDICAL = "MEDICAL"
    PICKUP = "PICKUP"


class ChildAuthStatus(str, Enum):
    NONE = "NONE"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class ScholarshipAwardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    REVOKED = "REVOKED"


class ScholarshipKind(str, Enum):
    AFTERSCHOOL = "AFTERSCHOOL"
    SUMMER_CAMP = "SUMMER_CAMP"
    ANY = "ANY"


class SessionDayWeatherStatus(str, Enum):
    NORMAL = "NORMAL"
    RAINY = "RAINY"
    CLOSED = "CLOSED"


class ResidencyStatus(str, Enum):
    STANDARD = "STANDARD"
    IN_DISTRICT = "IN_DISTRICT"
    OUT_OF_DISTRICT = "OUT_OF_DISTRICT"


class GuardianRelationship(str, Enum):
    PARENT = "PARENT"
    STEP_PARENT = "STEP_PARENT"
    LEGAL_GUARDIAN = "LEGAL_GUARDIAN"
    OTHER = "OTHER"


# ---------------------------------------------------------------------------
# Entities carrying the four common fields (id, created_at, updated_at, version)
# ---------------------------------------------------------------------------
class Family(TypedDict, total=False):
    id: str
    household_name: str
    primary_email: str
    residency_status: str
    archived: bool
    created_at: str
    updated_at: str
    version: int


class Guardian(TypedDict, total=False):
    id: str
    family_id: str
    full_name: str
    phone: str
    relationship: str
    is_primary: bool
    created_at: str
    updated_at: str
    version: int


class Child(TypedDict, total=False):
    id: str
    family_id: str
    full_name: str
    date_of_birth: str
    medical_authorization_status: str
    pickup_authorization_status: str
    emergency_contact_count: int
    created_at: str
    updated_at: str
    version: int


class EmergencyContact(TypedDict, total=False):
    id: str
    child_id: str
    full_name: str
    phone: str
    relationship: str
    priority: int
    archived: bool
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict, total=False):
    id: str
    title: str
    kind: str
    age_min: int
    age_max: int
    reference_date: str
    weekly_capacity: int
    week_start: str
    week_count: int
    base_weekly_fee_cents: int
    rainy_day_pool_per_week: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    child_id: str
    session_id: str
    week_index: int
    status: str
    list_fee_cents: int
    sibling_discount_cents: int
    scholarship_discount_cents: int
    final_fee_cents: int
    scholarship_award_id: Optional[str]
    waitlist_position: Optional[int]
    cancelled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScholarshipAward(TypedDict, total=False):
    id: str
    family_id: str
    total_credit_cents: int
    consumed_credit_cents: int
    granted_for_kind: str
    status: str
    revoked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Lean entities — id + created_at ONLY (no updated_at, no version)
# PRD §2.4: "Authorization and SessionDay carry only id and created_at —
# both updated_at and version are absent on these rows."
# ---------------------------------------------------------------------------
class Authorization(TypedDict, total=False):
    id: str
    child_id: str
    guardian_id: str
    kind: str
    scope_text: str
    effective_at: str
    expires_at: str
    status: str
    revoked_at: Optional[str]
    created_at: str


class SessionDay(TypedDict, total=False):
    id: str
    session_id: str
    week_index: int
    day_date: str
    weather_status: str
    rainy_day_used: int
    outdoor_headcount: int
    created_at: str


__all__ = [
    "UserRole",
    "SessionStatus",
    "SessionKind",
    "EnrollmentStatus",
    "AuthorizationStatus",
    "AuthorizationKind",
    "ChildAuthStatus",
    "ScholarshipAwardStatus",
    "ScholarshipKind",
    "SessionDayWeatherStatus",
    "ResidencyStatus",
    "GuardianRelationship",
    "Family",
    "Guardian",
    "Child",
    "EmergencyContact",
    "Session",
    "Enrollment",
    "ScholarshipAward",
    "Authorization",
    "SessionDay",
]
