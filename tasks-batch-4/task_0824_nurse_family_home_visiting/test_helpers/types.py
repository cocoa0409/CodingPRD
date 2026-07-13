"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this program carry the common resource properties described in the
PRD (id, created_at, updated_at, version); none are append-only.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────
class UserRole(str, Enum):
    INTAKE_COORDINATOR = "IntakeCoordinator"
    HOME_VISIT_NURSE = "HomeVisitNurse"
    SUPERVISOR = "Supervisor"
    PROGRAM_ADMIN = "ProgramAdmin"


# ─── Status enums ─────────────────────────────────────
class NurseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    INACTIVE = "INACTIVE"


class SupervisorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class RiskTier(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class EnrollmentStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ENROLLED = "ENROLLED"
    ACTIVE = "ACTIVE"
    GRADUATED = "GRADUATED"
    EXITED = "EXITED"


class ProgramPhase(str, Enum):
    PREGNANCY = "PREGNANCY"
    INFANCY = "INFANCY"
    TODDLERHOOD = "TODDLERHOOD"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    CANCELED = "CANCELED"
    RESCHEDULED = "RESCHEDULED"


class InstrumentType(str, Enum):
    INTAKE = "INTAKE"
    ASQ = "ASQ"
    EDINBURGH = "EDINBURGH"
    ASQ_SE = "ASQ_SE"


class ResultBand(str, Enum):
    ON_TRACK = "ON_TRACK"
    MONITOR = "MONITOR"
    REFER = "REFER"


class BenefitType(str, Enum):
    WIC = "WIC"
    MEDICAID = "MEDICAID"
    HOUSING = "HOUSING"
    CHILDCARE = "CHILDCARE"
    MENTAL_HEALTH = "MENTAL_HEALTH"


class ReferralStatus(str, Enum):
    OPEN = "OPEN"
    CONTACTED = "CONTACTED"
    CONNECTED = "CONNECTED"
    DECLINED = "DECLINED"
    CLOSED = "CLOSED"


class SupervisionStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"


class MeasureType(str, Enum):
    ON_TIME_VISIT_RATE = "ON_TIME_VISIT_RATE"
    DOSAGE_TO_DATE = "DOSAGE_TO_DATE"
    BREASTFEEDING_INITIATED = "BREASTFEEDING_INITIATED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


# ─── Entity TypedDicts ────────────────────────────────
class Nurse(TypedDict):
    id: str
    full_name: str
    credential_type: str
    status: str
    max_caseload_weight: float
    current_caseload_weight: float
    pending_supervision_count: int
    created_at: str
    updated_at: str
    version: int


class Supervisor(TypedDict):
    id: str
    full_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    full_name: str
    mother_dob: str
    first_time_mother: bool
    gestational_age_weeks: int
    consent_signed: bool
    child_dob: Optional[str]
    risk_tier: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    client_id: str
    status: str
    program_phase: str
    gestational_age_at_enrollment: int
    completed_visit_count: int
    dosage_alert: bool
    risk_tier_at_enrollment: str
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict):
    id: str
    enrollment_id: str
    nurse_id: str
    phase_at_assignment: str
    high_needs: bool
    caseload_weight: float
    status: str
    review_required: bool
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict):
    id: str
    enrollment_id: str
    nurse_id: str
    phase: str
    target_date: str
    scheduled_start: str
    scheduled_end: str
    status: str
    completed_date: Optional[str]
    on_time: bool
    rescheduled_from_visit_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict):
    id: str
    visit_id: str
    enrollment_id: str
    instrument_type: str
    raw_scores: dict
    result_band: str
    domain_flags: List[str]
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    enrollment_id: str
    benefit_type: str
    status: str
    attempts: int
    connected_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupervisionSession(TypedDict):
    id: str
    nurse_id: str
    supervisor_id: str
    period_start: str
    period_end: str
    reviewed_enrollment_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class OutcomeMeasure(TypedDict):
    id: str
    enrollment_id: str
    measure_type: str
    period_start: str
    period_end: str
    numerator: int
    denominator: int
    rate_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class MiechvReport(TypedDict):
    id: str
    period_start: str
    period_end: str
    status: str
    program_on_time_rate_pct: Optional[float]
    enrolled_count: int
    dosage_alert_count: int
    created_at: str
    updated_at: str
    version: int
