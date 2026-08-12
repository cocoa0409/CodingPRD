"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Roles (PRD §2.1) ─────────────────────────────────

class UserRole(str, Enum):
    DISTRICT_ADMIN = "DistrictAdmin"
    SCHOOL_ADMINISTRATOR = "SchoolAdministrator"
    HEARING_OFFICER = "HearingOfficer"
    PARENT_GUARDIAN = "ParentGuardian"
    STUDENT_SERVICES_DIRECTOR = "StudentServicesDirector"


# ─── Enumerations (PRD §3) ────────────────────────────

class DemographicGroup(str, Enum):
    ASIAN = "ASIAN"
    BLACK = "BLACK"
    HISPANIC = "HISPANIC"
    WHITE = "WHITE"
    MULTIRACIAL = "MULTIRACIAL"
    OTHER = "OTHER"


class DisabilityStatus(str, Enum):
    NONE = "NONE"
    IEP = "IEP"
    SECTION_504 = "SECTION_504"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    ALT_ED_PENDING = "ALT_ED_PENDING"
    IN_ALT_ED = "IN_ALT_ED"


class OffenseCategory(str, Enum):
    DRUGS = "DRUGS"
    WEAPONS = "WEAPONS"
    VIOLENCE = "VIOLENCE"
    PROPERTY = "PROPERTY"
    DISRUPTION = "DISRUPTION"
    ATTENDANCE = "ATTENDANCE"
    TECHNOLOGY = "TECHNOLOGY"


class CaseStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CLASSIFIED = "CLASSIFIED"
    SANCTION_PROPOSED = "SANCTION_PROPOSED"
    NOTICE_ISSUED = "NOTICE_ISSUED"
    CONFIRMED = "CONFIRMED"
    EXPULSION_REFERRED = "EXPULSION_REFERRED"
    EXPULSION_ACTIVE = "EXPULSION_ACTIVE"
    CLOSED = "CLOSED"
    EXPUNGED = "EXPUNGED"


class SanctionType(str, Enum):
    IN_SCHOOL = "IN_SCHOOL"
    OUT_OF_SCHOOL = "OUT_OF_SCHOOL"


class DeliveryMethod(str, Enum):
    EMAIL = "EMAIL"
    CERTIFIED_MAIL = "CERTIFIED_MAIL"
    IN_PORTAL = "IN_PORTAL"


class NoticeStatus(str, Enum):
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class ConferenceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    WAIVED = "WAIVED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class ConferenceOutcome(str, Enum):
    HELD = "HELD"
    WAIVED = "WAIVED"
    NO_SHOW = "NO_SHOW"


class AppealStatus(str, Enum):
    FILED = "FILED"
    UPHELD = "UPHELD"
    REVERSED = "REVERSED"
    REMANDED = "REMANDED"


class AppealOutcome(str, Enum):
    UPHELD = "UPHELD"
    REVERSED = "REVERSED"
    REMANDED = "REMANDED"


class HearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EVIDENCE_SERVED = "EVIDENCE_SERVED"
    HELD = "HELD"
    EXPULSION_ORDERED = "EXPULSION_ORDERED"
    NOT_EXPELLED = "NOT_EXPELLED"


class HearingOutcome(str, Enum):
    EXPULSION_ORDERED = "EXPULSION_ORDERED"
    NOT_EXPELLED = "NOT_EXPELLED"


class EvidenceItemType(str, Enum):
    WITNESS_STATEMENT = "WITNESS_STATEMENT"
    DOCUMENT = "DOCUMENT"
    VIDEO = "VIDEO"
    OTHER = "OTHER"


class EvidenceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ADMITTED = "ADMITTED"
    EXCLUDED = "EXCLUDED"


class EvidenceRuling(str, Enum):
    ADMITTED = "ADMITTED"
    EXCLUDED = "EXCLUDED"


class MdrOrigin(str, Enum):
    AUTO_THRESHOLD = "AUTO_THRESHOLD"
    MANUAL = "MANUAL"


class MdrStatus(str, Enum):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class MdrOutcome(str, Enum):
    MANIFESTATION_YES = "MANIFESTATION_YES"
    MANIFESTATION_NO = "MANIFESTATION_NO"


class PlacementStatus(str, Enum):
    PLACED = "PLACED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    EXITED_EARLY = "EXITED_EARLY"


class PlacementOutcome(str, Enum):
    COMPLETED = "COMPLETED"
    EXITED_EARLY = "EXITED_EARLY"


class ReEntryPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    VIOLATED = "VIOLATED"


class ReEntryOutcome(str, Enum):
    COMPLETED = "COMPLETED"
    VIOLATED = "VIOLATED"


class ExpungementStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ExpungementOutcome(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"


# ─── Entity TypedDicts (PRD §2.5, §3) ─────────────────
# Students, cases, notices, conferences, appeals, hearings, evidence items,
# determinations, sites, placements, re-entry plans and expungement requests
# carry id + created_at + updated_at + version. Offense codes and sanction
# bands are static policy definitions carrying ONLY id + created_at.

class Student(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    grade_level: int
    demographic_group: str
    disability_status: str
    guardian_id: str
    enrollment_status: str
    cumulative_suspension_days: int
    last_case_closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OffenseCode(TypedDict, total=False):
    # Static config resource: id + created_at only, no updated_at / version.
    id: str
    code: str
    title: str
    category: str
    severity_level: int
    expellable: bool
    created_at: str


class SanctionBand(TypedDict, total=False):
    # Static config resource: id + created_at only, no updated_at / version.
    id: str
    offense_code_id: str
    occurrence_index: int
    min_days: int
    max_days: int
    created_at: str


class DisciplineCase(TypedDict, total=False):
    id: str
    student_id: str
    incident_date: str
    description: str
    referrer_id: str
    offense_code_id: Optional[str]
    classified_by: Optional[str]
    occurrence_index: Optional[int]
    occurrence_index_ay: Optional[int]
    proposed_sanction_days: Optional[int]
    proposed_sanction_type: Optional[str]
    sanction_override: bool
    override_justification: Optional[str]
    proposed_at: Optional[str]
    mdr_required: bool
    sanction_days_final: Optional[int]
    confirmed_at: Optional[str]
    referred_to_expulsion_at: Optional[str]
    closed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SuspensionNotice(TypedDict, total=False):
    id: str
    case_id: str
    delivery_method: str
    issued_at: str
    appeal_deadline: str
    conference_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Conference(TypedDict, total=False):
    id: str
    case_id: str
    scheduled_at: str
    attempt_number: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    case_id: str
    filed_by: str
    grounds: str
    filed_at: str
    status: str
    decided_at: Optional[str]
    decision_rationale: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExpulsionHearing(TypedDict, total=False):
    id: str
    case_id: str
    hearing_officer_id: str
    scheduled_start: str
    scheduled_end: str
    packet_served_at: Optional[str]
    status: str
    decided_at: Optional[str]
    decision_rationale: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EvidenceItem(TypedDict, total=False):
    id: str
    hearing_id: str
    item_type: str
    description: str
    submitted_by: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ManifestationDetermination(TypedDict, total=False):
    id: str
    case_id: str
    origin: str
    due_at: str
    meeting_at: Optional[str]
    status: str
    outcome: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AltEdSite(TypedDict, total=False):
    id: str
    name: str
    capacity: int
    seats_occupied: int
    created_at: str
    updated_at: str
    version: int


class AltEdPlacement(TypedDict, total=False):
    id: str
    case_id: str
    site_id: str
    start_date: str
    planned_end_date: str
    status: str
    actual_end_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReEntryPlan(TypedDict, total=False):
    id: str
    placement_id: str
    conditions: List[str]
    conference_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ExpungementRequest(TypedDict, total=False):
    id: str
    student_id: str
    requested_by: str
    status: str
    decided_at: Optional[str]
    decision_rationale: Optional[str]
    created_at: str
    updated_at: str
    version: int
