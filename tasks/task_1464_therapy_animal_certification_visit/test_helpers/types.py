"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    HANDLER = "Handler"
    EVALUATOR = "Evaluator"
    FACILITY_COORDINATOR = "FacilityCoordinator"
    PROGRAM_ADMIN = "ProgramAdmin"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# ---------------------------------------------------------------------------
# Status / enum vocabularies (PRD §3)
# ---------------------------------------------------------------------------

class HandlerStatus(str, Enum):
    APPLICANT = "APPLICANT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"
    REJECTED = "REJECTED"


class AnimalStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    WELFARE_HOLD = "WELFARE_HOLD"
    RETIRED = "RETIRED"


class AnimalSpecies(str, Enum):
    DOG = "DOG"
    CAT = "CAT"
    RABBIT = "RABBIT"
    GUINEA_PIG = "GUINEA_PIG"
    BIRD = "BIRD"
    MINIATURE_HORSE = "MINIATURE_HORSE"


class TeamStatus(str, Enum):
    FORMING = "FORMING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DISSOLVED = "DISSOLVED"


class EvaluatorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class EvaluationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    APPEALED = "APPEALED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class CertificationStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    ACTIVE = "ACTIVE"
    RENEWAL_DUE = "RENEWAL_DUE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class CertSuspensionReason(str, Enum):
    MANUAL = "MANUAL"
    INCIDENT_PRECAUTION = "INCIDENT_PRECAUTION"
    INCIDENT_SUSPENSION = "INCIDENT_SUSPENSION"
    INSURANCE_LAPSE = "INSURANCE_LAPSE"
    LATE_CANCELLATIONS = "LATE_CANCELLATIONS"


class VaccineType(str, Enum):
    RABIES = "RABIES"
    DISTEMPER = "DISTEMPER"
    BORDETELLA = "BORDETELLA"
    CANINE_INFLUENZA = "CANINE_INFLUENZA"
    FELINE_FVRCP = "FELINE_FVRCP"


class VaccinationStatus(str, Enum):
    VALID = "VALID"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class FacilityType(str, Enum):
    HOSPITAL = "HOSPITAL"
    SCHOOL = "SCHOOL"
    NURSING_HOME = "NURSING_HOME"
    REHAB_CENTER = "REHAB_CENTER"
    HOSPICE = "HOSPICE"


class FacilityStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_FACILITY_SIGNATURE = "PENDING_FACILITY_SIGNATURE"
    PENDING_PROGRAM_SIGNATURE = "PENDING_PROGRAM_SIGNATURE"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"
    WITHDRAWN = "WITHDRAWN"


class OrientationStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


class PolicyStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class WaiverStatus(str, Enum):
    SIGNED = "SIGNED"
    VOIDED = "VOIDED"


class RequestStatus(str, Enum):
    OPEN = "OPEN"
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    FULFILLED = "FULFILLED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class VisitProgram(str, Enum):
    READING = "READING"
    REHAB = "REHAB"
    STRESS_RELIEF = "STRESS_RELIEF"
    GENERAL = "GENERAL"


class RequestPriority(str, Enum):
    ROUTINE = "ROUTINE"
    HIGH = "HIGH"
    URGENT = "URGENT"


class VisitLifecycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class VisitVerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"


class VisitCancelReason(str, Enum):
    HANDLER_CANCEL = "HANDLER_CANCEL"
    ADMIN_CANCEL = "ADMIN_CANCEL"
    FACILITY_CANCEL = "FACILITY_CANCEL"
    AGREEMENT_ENDED = "AGREEMENT_ENDED"
    CERT_SUSPENDED = "CERT_SUSPENDED"
    CERT_REVOKED = "CERT_REVOKED"
    TEAM_DISSOLVED = "TEAM_DISSOLVED"
    INCIDENT_PRECAUTION = "INCIDENT_PRECAUTION"


class WelfareHoldReason(str, Enum):
    MANUAL = "MANUAL"
    INCIDENT_PRECAUTION = "INCIDENT_PRECAUTION"


class IncidentSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentCategory(str, Enum):
    ANIMAL_STRESS = "ANIMAL_STRESS"
    BITE_SCRATCH = "BITE_SCRATCH"
    INJURY = "INJURY"
    PROPERTY_DAMAGE = "PROPERTY_DAMAGE"
    PROTOCOL_BREACH = "PROTOCOL_BREACH"


class IncidentStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class ResolutionCode(str, Enum):
    NO_ACTION = "NO_ACTION"
    WARNING = "WARNING"
    SUSPENSION = "SUSPENSION"
    REVOCATION = "REVOCATION"


class HourCreditKind(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    REVERSAL = "REVERSAL"
    ADJUSTMENT = "ADJUSTMENT"


class RecognitionTier(str, Enum):
    NONE = "NONE"
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


# ---------------------------------------------------------------------------
# Entity TypedDicts.
# Every primary resource carries id + created_at + updated_at + version
# (PRD §2.5). The hour-credit ledger row is the single exception: it carries
# only id + created_at (updated_at and version are absent).
# All TypedDicts are total=False so optional/nullable system fields are fine.
# ---------------------------------------------------------------------------

class Handler(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    region_code: str
    volunteer_since: str
    phone: Optional[str]
    status: str
    suspension_reason: Optional[str]
    lifetime_minutes: int
    recognition_tier: str
    created_at: str
    updated_at: str
    version: int


class Animal(TypedDict, total=False):
    id: str
    handler_id: str
    name: str
    species: str
    breed: str
    date_of_birth: str
    status: str
    welfare_hold_until: Optional[str]
    welfare_hold_reason: Optional[str]
    welfare_blocked_until: Optional[str]
    forward_workload_minutes: int
    audit_workload_minutes: int
    created_at: str
    updated_at: str
    version: int


class Team(TypedDict, total=False):
    id: str
    handler_id: str
    animal_id: str
    team_name: str
    status: str
    late_cancel_count: int
    no_show_count: int
    warning_count: int
    created_at: str
    updated_at: str
    version: int


class Evaluator(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    region_code: str
    specializations: List[str]
    max_evaluations_per_day: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Evaluation(TypedDict, total=False):
    id: str
    team_id: str
    evaluator_id: Optional[str]
    attempt_number: int
    scheduled_start: Optional[str]
    scheduled_end: Optional[str]
    aptitude_score: Optional[int]
    obedience_score: Optional[int]
    composite_score: Optional[float]
    status: str
    requested_at: str
    scored_at: Optional[str]
    failed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict, total=False):
    id: str
    team_id: str
    evaluation_id: str
    status: str
    activated_on: Optional[str]
    expires_on: Optional[str]
    renewal_count: int
    suspension_reason: Optional[str]
    suspension_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VaccinationRecord(TypedDict, total=False):
    id: str
    animal_id: str
    vaccine_type: str
    administered_on: str
    valid_until: str
    veterinarian_name: str
    clinic_name: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Facility(TypedDict, total=False):
    id: str
    name: str
    facility_type: str
    region_code: str
    address: Optional[str]
    max_visit_minutes: int
    allowed_species: List[str]
    min_liability_coverage_cents: int
    max_overlapping_teams: int
    visits_per_week_cap: int
    required_waiver_version: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FacilityAgreement(TypedDict, total=False):
    id: str
    facility_id: str
    start_on: str
    end_on: str
    agreed_max_visit_minutes: int
    insurance_minimum_cents: int
    terms_version: str
    status: str
    terminated_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrientationRecord(TypedDict, total=False):
    id: str
    team_id: str
    facility_id: str
    status: str
    attended_on: Optional[str]
    expires_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict, total=False):
    id: str
    handler_id: str
    insurer_name: str
    policy_number: str
    coverage_cents: int
    effective_from: str
    effective_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LiabilityWaiver(TypedDict, total=False):
    id: str
    team_id: str
    facility_id: str
    waiver_version: str
    signed_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class VisitRequest(TypedDict, total=False):
    id: str
    facility_id: str
    requested_start: str
    requested_end: str
    species_preference: Optional[str]
    visit_program: str
    priority: str
    status: str
    offered_team_id: Optional[str]
    offered_at: Optional[str]
    offer_expires_at: Optional[str]
    decline_count: int
    expired_on: Optional[str]
    fulfilled_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict, total=False):
    id: str
    team_id: str
    facility_id: str
    request_id: Optional[str]
    scheduled_start: str
    scheduled_end: str
    actual_start: Optional[str]
    actual_end: Optional[str]
    actual_minutes: Optional[int]
    lifecycle_status: str
    verification_status: str
    cancel_reason: Optional[str]
    cancelled_at: Optional[str]
    verified_at: Optional[str]
    approved_minutes: Optional[int]
    created_at: str
    updated_at: str
    version: int


class IncidentReport(TypedDict, total=False):
    id: str
    visit_id: str
    severity: str
    category: str
    description: str
    status: str
    filed_by_role: str
    triaged_by: Optional[str]
    resolved_by: Optional[str]
    resolution_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HourCredit(TypedDict, total=False):
    # Append-only ledger row (PRD §2.5 exception): id + created_at only —
    # NO updated_at, NO version.
    id: str
    handler_id: str
    visit_id: Optional[str]
    kind: str
    minutes: int
    note: Optional[str]
    created_at: str
