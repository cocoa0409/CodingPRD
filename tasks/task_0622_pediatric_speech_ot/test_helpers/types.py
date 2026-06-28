"""Domain types: entity TypedDicts, status enums, role enum.

All field names match the Pediatric Speech & OT Clinic PRD exactly.
Entities that carry the common system-managed fields (id, created_at,
updated_at, version) are full first-class resources. GoalProgressEntry is an
append-only event-log record and carries ONLY id + created_at (no updated_at,
no version).
"""
from enum import Enum
from typing import TypedDict, List


# ─── Status enums ─────────────────────────────────────────────────────────

class ChildStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCHARGED = "DISCHARGED"


class CoordinationProgram(str, Enum):
    NONE = "NONE"
    EARLY_INTERVENTION = "EARLY_INTERVENTION"
    SCHOOL = "SCHOOL"


class TherapistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class Discipline(str, Enum):
    SLP = "SLP"
    OT = "OT"


class EvaluationStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class PlanOfCareStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    DISCHARGED = "DISCHARGED"


class GoalStatus(str, Enum):
    OPEN = "OPEN"
    MET = "MET"
    DISCONTINUED = "DISCONTINUED"


class AuthorizationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REAUTH_REQUESTED = "REAUTH_REQUESTED"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class CoordinationPlanType(str, Enum):
    IFSP = "IFSP"
    IEP = "IEP"


class CoordinationPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TRANSITIONING = "TRANSITIONING"
    CLOSED = "CLOSED"


class HomeProgramStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class WaitlistEntryStatus(str, Enum):
    WAITING = "WAITING"
    OFFERED = "OFFERED"
    PLACED = "PLACED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class UserRole(str, Enum):
    CLINIC_ADMIN = "ClinicAdmin"
    SCHEDULING_COORDINATOR = "SchedulingCoordinator"
    EVALUATOR = "Evaluator"
    THERAPIST = "Therapist"


# ─── Entity TypedDicts (common_fields: true) ────────────────────────────────

class Child(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    age_months_at_intake: int
    coordination_program: str
    active_appointment_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Therapist(TypedDict):
    id: str
    full_name: str
    discipline: str
    max_caseload: int
    weekly_visit_minutes_cap: int
    current_caseload: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Evaluation(TypedDict):
    id: str
    child_id: str
    evaluator_id: str
    discipline: str
    severity_score: int
    recommended_weekly_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PlanOfCare(TypedDict):
    id: str
    child_id: str
    evaluation_id: str
    primary_therapist_id: str
    discipline: str
    planned_weekly_minutes: int
    goal_count: int
    overall_progress_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Goal(TypedDict):
    id: str
    plan_of_care_id: str
    description: str
    weight: int
    baseline_pct: int
    target_pct: int
    latest_progress_pct: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Authorization(TypedDict):
    id: str
    child_id: str
    discipline: str
    payer_name: str
    authorized_visits: int
    valid_from: str
    valid_until: str
    reserved_visits: int
    committed_visits: int
    available_visits: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    child_id: str
    therapist_id: str
    authorization_id: str
    plan_of_care_id: str
    start_time: str
    end_time: str
    duration_minutes: int
    from_waitlist_entry_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SessionNote(TypedDict):
    id: str
    appointment_id: str
    narrative: str
    minutes_delivered: int
    goal_progress_entries: list
    created_at: str
    updated_at: str
    version: int


class CoordinationPlan(TypedDict):
    id: str
    child_id: str
    plan_type: str
    jurisdiction: str
    review_due_time: str
    status: str
    created_at: str
    updated_at: str
    version: int


class HomeProgram(TypedDict):
    id: str
    plan_of_care_id: str
    assigned_by_therapist_id: str
    title: str
    weekly_target_sessions: int
    parent_training_completed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict):
    id: str
    child_id: str
    therapist_id: str
    discipline: str
    evaluation_id: str
    priority_score: int
    requested_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Append-only event-log record (common_fields: false) ────────────────────
# Carries ONLY id + created_at — no updated_at, no version.

class GoalProgressEntry(TypedDict):
    id: str
    goal_id: str
    session_note_id: str
    recorded_pct: int
    recorded_session_time: str
    created_at: str
