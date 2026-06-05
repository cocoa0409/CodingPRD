"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entities and their lifecycle states. Certificate and
Attestation are immutable (id + created_at only — no updated_at, no version).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    BOARD_ADMIN = "BoardAdmin"
    PROVIDER = "Provider"
    LICENSEE = "Licensee"
    AUDITOR = "Auditor"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class CreditUnit(str, Enum):
    CEU = "CEU"
    CME = "CME"
    CLE = "CLE"


class Category(str, Enum):
    ETHICS = "ETHICS"
    SUBSTANCE = "SUBSTANCE"
    GENERAL = "GENERAL"


class ProviderStatus(str, Enum):
    APPLIED = "APPLIED"
    ACCREDITED = "ACCREDITED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class CourseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"


class RenewalCycleStatus(str, Enum):
    OPEN = "OPEN"
    REQUIREMENTS_MET = "REQUIREMENTS_MET"
    AUDIT_HOLD = "AUDIT_HOLD"
    RENEWED = "RENEWED"
    LAPSED = "LAPSED"


class CompletionStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    INVALIDATED = "INVALIDATED"


class AuditStatus(str, Enum):
    INITIATED = "INITIATED"
    ATTESTATION_PENDING = "ATTESTATION_PENDING"
    UNDER_REVIEW = "UNDER_REVIEW"
    PASSED = "PASSED"
    FAILED = "FAILED"


class ReciprocityGrantStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ReminderStatus(str, Enum):
    NOT_DUE = "NOT_DUE"
    DUE = "DUE"
    OVERDUE = "OVERDUE"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true -> id/created_at/updated_at/version)
# ---------------------------------------------------------------------------
class LicenseBoard(TypedDict):
    id: str
    name: str
    jurisdiction_code: str
    credit_unit: str
    cycle_length_months: int
    total_required_hours: float
    carryover_cap_hours: float
    audit_cooldown_days: int
    reminder_lead_days: int
    created_at: str
    updated_at: str
    version: int


class CreditRequirement(TypedDict):
    id: str
    board_id: str
    category: str
    min_hours: float
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict):
    id: str
    name: str
    board_id: str
    status: str
    accredited_from: Optional[str]
    accredited_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Course(TypedDict):
    id: str
    provider_id: str
    title: str
    category: str
    credit_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Licensee(TypedDict):
    id: str
    full_name: str
    home_board_id: str
    license_number: str
    audit_risk_score: float
    created_at: str
    updated_at: str
    version: int


class RenewalCycle(TypedDict):
    id: str
    licensee_id: str
    board_id: str
    cycle_start: str
    cycle_end: str
    status: str
    carryover_in_hours: float
    carryover_out_hours: float
    provisional_earned_hours: float
    final_earned_hours: float
    reciprocity_hours: float
    reminder_status: str
    created_at: str
    updated_at: str
    version: int


class Completion(TypedDict):
    id: str
    licensee_id: str
    course_id: str
    cycle_id: str
    completed_at: str
    awarded_hours: float
    category: str
    status: str
    is_late: bool
    created_at: str
    updated_at: str
    version: int


class Audit(TypedDict):
    id: str
    cycle_id: str
    licensee_id: str
    initiated_by_user_id: str
    decided_by_user_id: Optional[str]
    status: str
    initiated_at: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReciprocityGrant(TypedDict):
    id: str
    licensee_id: str
    target_cycle_id: str
    source_jurisdiction_code: str
    category: str
    credit_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Immutable entities (common_fields: false -> id + created_at ONLY)
# ---------------------------------------------------------------------------
class Certificate(TypedDict):
    id: str
    cycle_id: str
    serial_number: str
    total_hours_certified: float
    issued_at: str
    created_at: str


class Attestation(TypedDict):
    id: str
    audit_id: str
    statement: str
    attested_hours: float
    created_at: str
