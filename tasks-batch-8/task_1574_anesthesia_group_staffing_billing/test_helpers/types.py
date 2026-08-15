"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    GROUP_ADMINISTRATOR = "GroupAdministrator"
    SCHEDULER = "Scheduler"
    ATTENDING_ANESTHESIOLOGIST = "AttendingAnesthesiologist"
    CRNA = "CRNA"
    BILLING_SPECIALIST = "BillingSpecialist"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"


class ProviderType(str, Enum):
    ANESTHESIOLOGIST = "ANESTHESIOLOGIST"
    CRNA = "CRNA"
    AA = "AA"


class ProviderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SiteStatus(str, Enum):
    ACTIVE = "ACTIVE"


class RosterLifecycle(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    LOCKED = "LOCKED"


class RosterPosture(str, Enum):
    UNDERSTAFFED = "UNDERSTAFFED"
    STAFFED = "STAFFED"


class CaseStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PhysicalStatus(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"
    P5 = "P5"
    P6 = "P6"


class AssignmentRole(str, Enum):
    CASE_PRIMARY = "CASE_PRIMARY"
    CASE_DIRECTING = "CASE_DIRECTING"


class CaseAssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"
    COMPLETED = "COMPLETED"


class CallAssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"


class AttestationStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ModifierCode(str, Enum):
    PERSONAL = "PERSONAL"
    QY = "QY"
    QK = "QK"
    AD = "AD"
    QX = "QX"
    QZ = "QZ"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    READY = "READY"
    SUBMITTED = "SUBMITTED"
    DENIED = "DENIED"
    PAID = "PAID"
    WRITTEN_OFF = "WRITTEN_OFF"


class StipendEntryType(str, Enum):
    CALL = "CALL"
    LATE_STAY = "LATE_STAY"
    STANDBY = "STANDBY"


class StipendEntryStatus(str, Enum):
    ACCRUED = "ACCRUED"
    VOIDED = "VOIDED"


class AuditStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class FindingType(str, Enum):
    TEFRA_GAP = "TEFRA_GAP"
    CONCURRENCY_RETRO_BREACH = "CONCURRENCY_RETRO_BREACH"
    CREDENTIAL_LAPSE = "CREDENTIAL_LAPSE"


class FindingSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class RiskBand(str, Enum):
    LOW = "LOW"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# --- Entity TypedDicts (all entities carry the four common fields per PRD §2.5) ---


class Site(TypedDict):
    id: str
    name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict):
    id: str
    full_name: str
    provider_type: str
    npi: str
    credential_expires_on: str
    dea_expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DailyRoster(TypedDict):
    id: str
    site_id: str
    service_date: str
    required_primary_slots: int
    scheduled_day_end_minute: int
    lifecycle: str
    posture: str
    created_at: str
    updated_at: str
    version: int


class AnesthesiaCase(TypedDict):
    id: str
    roster_id: str
    procedure_code: str
    physical_status: str
    emergency_flag: bool
    scheduled_start_minute: int
    scheduled_end_minute: int
    actual_start_minute: Optional[int]
    actual_end_minute: Optional[int]
    status: str
    cancellation_reason: Optional[str]
    cancellation_notice_minutes: Optional[int]
    provisional_charge_cents: Optional[int]
    final_charge_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CaseAssignment(TypedDict):
    id: str
    case_id: str
    roster_id: str
    provider_id: str
    assignment_role: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CallAssignment(TypedDict):
    id: str
    roster_id: str
    provider_id: str
    window_start_minute: int
    window_end_minute: int
    status: str
    released_at_minute: Optional[int]
    created_at: str
    updated_at: str
    version: int


class DirectionAttestation(TypedDict):
    id: str
    case_id: str
    physician_id: str
    step_preanesthetic_exam: bool
    step_prescribes_plan: bool
    step_participates_key_portions: bool
    step_ensures_qualified_personnel: bool
    step_monitors_course: bool
    step_available_for_emergencies: bool
    step_post_anesthesia_care: bool
    submitted_count: int
    rejection_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BillingClaim(TypedDict):
    id: str
    case_id: str
    provider_id: str
    modifier_code: str
    units_total: float
    charge_cents: int
    status: str
    denial_reason: Optional[str]
    paid_amount_cents: Optional[int]
    resubmission_count: int
    created_at: str
    updated_at: str
    version: int


class ProcedureFeeSchedule(TypedDict):
    id: str
    procedure_code: str
    base_units: int
    contracted_max_cents: int
    description: str
    created_at: str
    updated_at: str
    version: int


class StipendAgreement(TypedDict):
    id: str
    site_id: str
    effective_from: str
    effective_to: str
    call_stipend_cents: int
    late_stay_rate_cents_per_minute: int
    standby_full_cents: int
    standby_partial_cents: int
    created_at: str
    updated_at: str
    version: int


class StipendLedgerEntry(TypedDict):
    id: str
    provider_id: str
    roster_id: str
    entry_type: str
    occurred_date: str
    amount_cents: int
    applied_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceAudit(TypedDict):
    id: str
    roster_id: str
    status: str
    realtime_score: int
    period_score: int
    risk_band: str
    created_at: str
    updated_at: str
    version: int


class AuditFinding(TypedDict):
    id: str
    audit_id: str
    case_id: Optional[str]
    assignment_id: Optional[str]
    finding_type: str
    severity: str
    status: str
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StipendSummary(TypedDict):
    provider_id: str
    month: str
    gross_cents: int
    applied_cents: int
    capped_cents: int
    entry_count: int
