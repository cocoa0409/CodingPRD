"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    OPERATIONS_MANAGER = "OperationsManager"
    ENTRY_SUPERVISOR = "EntrySupervisor"
    ATTENDANT = "Attendant"
    RESCUE_TEAM_LEAD = "RescueTeamLead"
    SAFETY_OFFICER = "SafetyOfficer"
    BILLING_CLERK = "BillingClerk"


class Qualification(str, Enum):
    ENTRY_SUPERVISOR = "ENTRY_SUPERVISOR"
    ATTENDANT = "ATTENDANT"
    RESCUE_LEAD = "RESCUE_LEAD"
    SAFETY_OFFICER = "SAFETY_OFFICER"
    RESCUER = "RESCUER"


class Certification(str, Enum):
    CONFINED_SPACE_RESCUE = "CONFINED_SPACE_RESCUE"
    HIGH_ANGLE = "HIGH_ANGLE"
    HAZMAT = "HAZMAT"
    MEDIC = "MEDIC"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------

class PersonnelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class BillingMode(str, Enum):
    HOURLY_STANDBY = "HOURLY_STANDBY"
    EVENT = "EVENT"


class SpaceClassification(str, Enum):
    NON_PERMIT = "NON_PERMIT"
    PERMIT_REQUIRED = "PERMIT_REQUIRED"
    PERMIT_REQUIRED_HAZARDOUS = "PERMIT_REQUIRED_HAZARDOUS"


class SpaceStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class ExposureStandard(str, Enum):
    TWA8 = "TWA8"
    PEAK_CEILING = "PEAK_CEILING"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class RetrievalSystemType(str, Enum):
    MECHANICAL_RETRIEVAL = "MECHANICAL_RETRIEVAL"
    TRIPOD = "TRIPOD"
    HORIZONTAL_HAUL = "HORIZONTAL_HAUL"
    ENTRY_RESCUE = "ENTRY_RESCUE"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class CloseReason(str, Enum):
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    INCIDENT = "INCIDENT"


class IsolationType(str, Enum):
    VENTILATION = "VENTILATION"
    BLIND_FLANGE = "BLIND_FLANGE"
    LOCKOUT_TAGOUT = "LOCKOUT_TAGOUT"


class VerificationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class AssignmentRole(str, Enum):
    ENTRANT = "ENTRANT"
    ATTENDANT = "ATTENDANT"


class RosterStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ON_DUTY = "ON_DUTY"
    RELIEVED = "RELIEVED"
    COMPLETED = "COMPLETED"
    EVACUATED = "EVACUATED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class ExposureClass(str, Enum):
    OK = "OK"
    ACTION = "ACTION"
    EXCEEDANCE = "EXCEEDANCE"


class ReadingKind(str, Enum):
    PRE_ENTRY = "PRE_ENTRY"
    CONTINUOUS = "CONTINUOUS"


class StandbyStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ON_STANDBY = "ON_STANDBY"
    DEPLOYED = "DEPLOYED"
    RELEASED = "RELEASED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    SERIOUS = "SERIOUS"
    CRITICAL = "CRITICAL"


class IncidentKind(str, Enum):
    ENTRAPMENT = "ENTRAPMENT"
    ATMOSPHERE = "ATMOSPHERE"
    MEDICAL = "MEDICAL"
    EQUIPMENT = "EQUIPMENT"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    TRIAGED = "TRIAGED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"


class StatementStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"
    VOID = "VOID"


class LineKind(str, Enum):
    STANDBY_HOURLY = "STANDBY_HOURLY"
    EVENT_BASE = "EVENT_BASE"
    EVENT_RESCUER = "EVENT_RESCUER"
    CANCELLATION_FEE = "CANCELLATION_FEE"
    DEPLOYMENT_SURCHARGE = "DEPLOYMENT_SURCHARGE"
    CREDIT_ADJUSTMENT = "CREDIT_ADJUSTMENT"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.4 common fields; §3 entity fields)
# ---------------------------------------------------------------------------

class Personnel(TypedDict, total=False):
    id: str
    full_name: str
    role_qualifications: List[str]
    certifications: List[str]
    max_duty_hours: int
    status: str
    committed_standby_minutes: int
    created_at: str
    updated_at: str
    version: int


class ClientAccount(TypedDict, total=False):
    id: str
    name: str
    billing_mode: str
    hourly_standby_rate_cents: int
    event_base_fee_cents: int
    event_per_rescuer_cents: int
    deployment_surcharge_cents: int
    credit_limit_cents: int
    minimum_billable_hours: float
    tier1_hours_threshold: float
    tier2_multiplier: float
    after_hours_multiplier: float
    weekend_multiplier: float
    balance_cents: int
    on_credit_hold: bool
    created_at: str
    updated_at: str
    version: int


class ConfinedSpace(TypedDict, total=False):
    id: str
    client_account_id: str
    space_code: str
    classification: str
    requires_continuous_monitoring: bool
    max_entrants: int
    ventilation_required: bool
    blind_flange_required: bool
    exposure_standard: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RescuePlan(TypedDict, total=False):
    id: str
    space_id: str
    required_team_size: int
    required_certifications: List[str]
    retrieval_system_type: str
    plan_revision: int
    status: str
    approved_by: Optional[str]
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EntryPermit(TypedDict, total=False):
    id: str
    space_id: str
    client_account_id: str
    purpose: str
    planned_start_at: str
    planned_end_at: str
    issued_by: Optional[str]
    issued_at: Optional[str]
    actual_entry_at: Optional[str]
    last_suspended_at: Optional[str]
    closed_at: Optional[str]
    close_reason: Optional[str]
    suspension_count: int
    reentry_count: int
    event_base_billed: bool
    cancellation_fee_billed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class IsolationVerification(TypedDict, total=False):
    id: str
    permit_id: str
    isolation_type: str
    evidence_ref: str
    created_by: str
    verified_by: Optional[str]
    verified_at: Optional[str]
    expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RosterEntry(TypedDict, total=False):
    id: str
    permit_id: str
    personnel_id: str
    assignment_role: str
    scheduled_start_at: str
    scheduled_end_at: str
    relief_of_entry_id: Optional[str]
    checked_in_at: Optional[str]
    checked_out_at: Optional[str]
    exposure_twa_ppm: float
    exposure_peak_ppm: float
    exposure_class: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only record (PRD §2.4): carries only id + created_at of the common
# fields; updated_at and version are absent.
class AtmosphericReading(TypedDict, total=False):
    id: str
    permit_id: str
    recorded_by: str
    reading_kind: str
    o2_pct: float
    lel_pct: float
    h2s_ppm: float
    co_ppm: float
    recorded_at: str
    within_limits: bool
    created_at: str


class StandbyAssignment(TypedDict, total=False):
    id: str
    permit_id: str
    rescuer_id: str
    standby_start_at: str
    standby_end_at: str
    checked_in_at: Optional[str]
    checked_out_at: Optional[str]
    deployed_at: Optional[str]
    billable_minutes: Optional[int]
    line_amount_cents: Optional[int]
    billed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict, total=False):
    id: str
    permit_id: str
    reported_by: str
    severity: str
    kind: str
    description: str
    triaged_by: Optional[str]
    resolved_by: Optional[str]
    resolution_notes: Optional[str]
    escalation_level: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BillingStatement(TypedDict, total=False):
    id: str
    client_account_id: str
    period_start: str
    period_end: str
    status: str
    total_cents: int
    line_count: int
    finalized_at: Optional[str]
    billed_balance_contribution_cents: int
    created_at: str
    updated_at: str
    version: int


# Append-only record (PRD §2.4): carries only id + created_at of the common
# fields; updated_at and version are absent.
class StatementLine(TypedDict, total=False):
    id: str
    statement_id: str
    line_kind: str
    reference_permit_id: Optional[str]
    reference_assignment_id: Optional[str]
    quantity: float
    unit_rate_cents: float
    amount_cents: int
    description: str
    created_at: str
