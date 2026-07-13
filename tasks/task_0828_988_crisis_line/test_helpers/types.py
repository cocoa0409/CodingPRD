"""Domain types: entity TypedDicts, status enums, role enum for the Crisis Line Dispatch API."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role model ───────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    CRISIS_COUNSELOR = "CrisisCounselor"
    CRISIS_DISPATCHER = "CrisisDispatcher"
    CLINICAL_SUPERVISOR = "ClinicalSupervisor"


# ─── Status enums ─────────────────────────────────────────────────────────────
class ContactStatus(str, Enum):
    INTAKE = "INTAKE"
    SCREENED = "SCREENED"
    DE_ESCALATION = "DE_ESCALATION"
    DISPATCH_PENDING = "DISPATCH_PENDING"
    REFERRAL_PENDING = "REFERRAL_PENDING"
    EMERGENCY_911 = "EMERGENCY_911"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class RiskBand(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    IMMINENT = "IMMINENT"


class Disposition(str, Enum):
    DE_ESCALATION = "DE_ESCALATION"
    MOBILE_DISPATCH = "MOBILE_DISPATCH"
    EMERGENCY = "EMERGENCY"


class EmergencyStatus(str, Enum):
    NONE = "NONE"
    INITIATED = "INITIATED"


class Channel(str, Enum):
    PHONE = "PHONE"
    CHAT = "CHAT"
    TEXT = "TEXT"


class ScreeningType(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    COMPREHENSIVE = "COMPREHENSIVE"


class SafetyPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class TeamStatus(str, Enum):
    ON_SHIFT = "ON_SHIFT"
    OFF_SHIFT = "OFF_SHIFT"


class DispatchStatus(str, Enum):
    REQUESTED = "REQUESTED"
    EN_ROUTE = "EN_ROUTE"
    ON_SCENE = "ON_SCENE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CenterStatus(str, Enum):
    ONLINE = "ONLINE"
    DIVERTED = "DIVERTED"


class ReferralStatus(str, Enum):
    HELD = "HELD"
    ADMITTED = "ADMITTED"
    DISCHARGED = "DISCHARGED"
    VOIDED = "VOIDED"


class FollowUpStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ATTEMPTED = "ATTEMPTED"
    RESCHEDULED = "RESCHEDULED"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


class FollowUpOutcome(str, Enum):
    REACHED = "REACHED"
    NO_ANSWER = "NO_ANSWER"


# ─── Entity TypedDicts ────────────────────────────────────────────────────────
# All entities below carry the full common-field set (id, created_at, updated_at,
# version) EXCEPT EmergencyCoordination, which is append-only (id + created_at only).

class Contact(TypedDict):
    id: str
    channel: str
    caller_key: str
    caller_phone: Optional[str]
    caller_name: Optional[str]
    presenting_concern: Optional[str]
    status: str
    risk_score: Optional[int]
    risk_band: Optional[str]
    latest_screening_id: Optional[str]
    disposition: Optional[str]
    disposition_at: Optional[str]
    has_active_safety_plan: bool
    emergency_status: str
    repeat_caller_flag: bool
    created_at: str
    updated_at: str
    version: int


class RiskScreening(TypedDict):
    id: str
    contact_id: str
    screening_type: str
    suicidal_ideation: int
    plan_specificity: int
    means_access: bool
    prior_attempts: int
    protective_factors: int
    risk_score: int
    risk_band: str
    created_at: str
    updated_at: str
    version: int


class SafetyPlan(TypedDict):
    id: str
    contact_id: str
    coping_strategies: List[str]
    warning_signs: List[str]
    support_contacts: Optional[List[str]]
    lethal_means_counseling: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class MobileCrisisTeam(TypedDict):
    id: str
    name: str
    coverage_zone: str
    capacity: int
    shift_start: str
    shift_end: str
    status: str
    active_dispatch_count: int
    created_at: str
    updated_at: str
    version: int


class MobileDispatch(TypedDict):
    id: str
    contact_id: str
    team_id: str
    window_start: str
    window_end: str
    requested_acuity: str
    status: str
    on_scene_acuity: Optional[str]
    priority_score_estimated: int
    priority_score_reassessed: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CrisisCenter(TypedDict):
    id: str
    name: str
    bed_capacity: int
    accepted_acuities: List[str]
    status: str
    held_beds: int
    occupied_beds: int
    available_beds: int
    created_at: str
    updated_at: str
    version: int


class BedReferral(TypedDict):
    id: str
    contact_id: str
    crisis_center_id: str
    mobile_dispatch_id: Optional[str]
    acuity: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FollowUpTask(TypedDict):
    id: str
    contact_id: str
    scheduled_at: str
    channel: str
    outcome: Optional[str]
    attempt_count: int
    max_attempts: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only 911 hand-off record: carries ONLY id + created_at (no updated_at, no version).
class EmergencyCoordination(TypedDict):
    id: str
    contact_id: str
    psap_reference: str
    risk_band_at_escalation: str
    initiated_by_role: str
    created_at: str


class RepeatCaller(TypedDict):
    id: str
    caller_key: str
    contact_count: int
    last_risk_band: Optional[str]
    high_risk_flag: bool
    registry_status: str
    created_at: str
    updated_at: str
    version: int
