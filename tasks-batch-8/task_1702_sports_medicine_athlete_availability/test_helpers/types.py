"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class Sport(str, Enum):
    FOOTBALL = "FOOTBALL"
    BASKETBALL = "BASKETBALL"
    SOCCER = "SOCCER"
    HOCKEY = "HOCKEY"
    BASEBALL = "BASEBALL"


class HipaaMode(str, Enum):
    STRICT = "STRICT"
    STANDARD = "STANDARD"


class AcwrVariant(str, Enum):
    ROLLING = "ROLLING"
    EWMA = "EWMA"


class UserRole(str, Enum):
    TEAM_ADMIN = "TeamAdmin"
    MEDICAL_STAFF = "MedicalStaff"
    TEAM_PHYSICIAN = "TeamPhysician"
    PERFORMANCE_STAFF = "PerformanceStaff"
    BILLING_STAFF = "BillingStaff"
    COACHING_STAFF = "CoachingStaff"


class RosterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    RELEASED = "RELEASED"


class AvailabilityTier(str, Enum):
    FULL = "FULL"
    MODIFIED = "MODIFIED"
    LIMITED = "LIMITED"
    OUT = "OUT"


class LoadFlag(str, Enum):
    NONE = "NONE"
    ELEVATED = "ELEVATED"
    SPIKE = "SPIKE"


class BodyRegion(str, Enum):
    HEAD_NECK = "HEAD_NECK"
    SHOULDER = "SHOULDER"
    ARM = "ARM"
    HAND = "HAND"
    TRUNK = "TRUNK"
    HIP = "HIP"
    KNEE = "KNEE"
    LOWER_LEG = "LOWER_LEG"
    ANKLE_FOOT = "ANKLE_FOOT"
    SYSTEMIC = "SYSTEMIC"


class SeverityClass(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    REHAB = "REHAB"
    RTP = "RTP"
    LONG_TERM = "LONG_TERM"
    CLEARED = "CLEARED"
    CLOSED = "CLOSED"


class Surface(str, Enum):
    GRASS = "GRASS"
    TURF = "TURF"
    COURT = "COURT"
    ICE = "ICE"
    TRAINING_ROOM = "TRAINING_ROOM"


class Mechanism(str, Enum):
    CONTACT = "CONTACT"
    NON_CONTACT = "NON_CONTACT"
    OVERUSE = "OVERUSE"
    UNKNOWN = "UNKNOWN"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"


class Designation(str, Enum):
    OUT = "OUT"
    LIMITED = "LIMITED"
    MODIFIED = "MODIFIED"
    FULL = "FULL"


class ProtocolStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_CLEARANCE = "AWAITING_CLEARANCE"
    REGRESSED = "REGRESSED"
    SUSPENDED_CONCUSSION = "SUSPENDED_CONCUSSION"
    CLEARED = "CLEARED"


class AdvanceKind(str, Enum):
    ADVANCE = "ADVANCE"
    REGRESSION = "REGRESSION"


class ClearanceDecision(str, Enum):
    GRANTED = "GRANTED"
    RETURNED_FOR_REVIEW = "RETURNED_FOR_REVIEW"


class ClearanceStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    RETURNED_FOR_REVIEW = "RETURNED_FOR_REVIEW"
    EXPIRED = "EXPIRED"


class SessionType(str, Enum):
    PRACTICE = "PRACTICE"
    GAME = "GAME"
    CONDITIONING = "CONDITIONING"
    REHAB_SESSION = "REHAB_SESSION"


class PolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ADJUDICATED = "ADJUDICATED"
    PAID = "PAID"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    VOID = "VOID"


class GranteeRole(str, Enum):
    COACHING = "COACHING"
    FRONT_OFFICE = "FRONT_OFFICE"


class GrantScope(str, Enum):
    TIER_ONLY = "TIER_ONLY"
    GENERAL = "GENERAL"
    FULL = "FULL"


class GrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class Audience(str, Enum):
    COACHING = "COACHING"
    FRONT_OFFICE = "FRONT_OFFICE"
    MEDICAL = "MEDICAL"


# --- Entity TypedDicts -------------------------------------------------------
# Entities with the full common-field set carry id + created_at + updated_at +
# version (PRD §2.4). The five immutable/append-only entities (DiagnosisCode,
# DailyStatusEntry, RTPStageAdvance, WorkloadSession, AvailabilityReport) carry
# only id + created_at (PRD §2.4).


class Team(TypedDict, total=False):
    id: str
    name: str
    sport: str
    season_start_date: str
    season_end_date: str
    hipaa_mode: str
    acwr_variant: str
    current_utc: str
    created_at: str
    updated_at: str
    version: int


class Athlete(TypedDict, total=False):
    id: str
    team_id: str
    full_name: str
    position: str
    enrollment_date: str
    roster_status: str
    availability_tier: str
    acute_chronic_workload_ratio: Optional[float]
    load_flag: str
    created_at: str
    updated_at: str
    version: int


class DiagnosisCode(TypedDict, total=False):
    id: str
    code: str
    body_region: str
    severity_class: str
    is_concussion: bool
    created_at: str


class InjuryCase(TypedDict, total=False):
    id: str
    athlete_id: str
    team_id: str
    diagnosis_code_id: str
    occurred_on: str
    surface: str
    mechanism: str
    status: str
    reported_by_user_id: str
    severity_class_snapshot: str
    is_concussion_snapshot: bool
    cleared_on: Optional[str]
    closed_on: Optional[str]
    days_lost: Optional[int]
    created_at: str
    updated_at: str
    version: int


class TreatmentPlan(TypedDict, total=False):
    id: str
    injury_case_id: str
    athlete_id: str
    title: str
    planned_sessions_per_week: int
    estimated_duration_weeks: int
    status: str
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DailyStatusEntry(TypedDict, total=False):
    id: str
    injury_case_id: str
    athlete_id: str
    entry_date: str
    designation: str
    symptom_free: bool
    functional_test_score: int
    notes: Optional[str]
    recorded_by_user_id: str
    supersedes_entry_id: Optional[str]
    is_current: bool
    created_at: str


class RTPProtocol(TypedDict, total=False):
    id: str
    injury_case_id: str
    athlete_id: str
    total_stages: int
    current_stage_index: int
    current_stage_entered_on: str
    regression_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RTPStageAdvance(TypedDict, total=False):
    id: str
    rtp_protocol_id: str
    from_stage_index: int
    to_stage_index: int
    kind: str
    advanced_by_user_id: str
    readiness_snapshot: Optional[Dict[str, Any]]
    created_at: str


class ClearanceAuthorization(TypedDict, total=False):
    id: str
    rtp_protocol_id: str
    injury_case_id: str
    athlete_id: str
    requested_by_user_id: str
    decided_by_user_id: Optional[str]
    decision: Optional[str]
    status: str
    requested_at: str
    decided_at: Optional[str]
    expires_at: Optional[str]
    request_notes: Optional[str]
    decision_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WorkloadSession(TypedDict, total=False):
    id: str
    athlete_id: str
    team_id: str
    session_date: str
    session_type: str
    surface: str
    duration_minutes: int
    rpe: int
    session_load: int
    counts_as_exposure: bool
    ingested_by_user_id: str
    created_at: str


class InsurancePolicy(TypedDict, total=False):
    id: str
    athlete_id: str
    payer_name: str
    policy_number: str
    deductible_cents: int
    deductible_met_cents: int
    coinsurance_pct: int
    oop_max_cents: int
    oop_accrued_cents: int
    policy_year_start: str
    policy_year_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ClaimLineItem(TypedDict):
    cpt_code: str
    charge_cents: int
    service_date: str


class Claim(TypedDict, total=False):
    id: str
    injury_case_id: str
    athlete_id: str
    insurance_policy_id: str
    billed_amount_cents: int
    line_items: List[ClaimLineItem]
    status: str
    submitted_at: Optional[str]
    adjudicated_at: Optional[str]
    payer_paid_cents: Optional[int]
    patient_resp_cents: Optional[int]
    deductible_applied_cents: Optional[int]
    appeals_count: int
    supersedes_claim_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisclosureGrant(TypedDict, total=False):
    id: str
    athlete_id: str
    grantee_role: str
    scope: str
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AvailabilityReport(TypedDict, total=False):
    id: str
    team_id: str
    report_date: str
    generated_by_user_id: str
    generated_for_role: str
    rows: List[Dict[str, Any]]
    created_at: str
