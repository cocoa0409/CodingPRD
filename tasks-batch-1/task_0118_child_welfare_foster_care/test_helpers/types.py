"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this API carry id + created_at + updated_at + version
(PRD §2.4), so every entity TypedDict lists the four common fields.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    ADMIN = "Admin"
    INTAKE_SCREENER = "IntakeScreener"
    INVESTIGATOR = "Investigator"
    CASEWORKER = "Caseworker"
    LICENSING_WORKER = "LicensingWorker"
    JUDGE = "Judge"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class CaseworkerRoleType(str, Enum):
    SCREENER = "SCREENER"
    INVESTIGATOR = "INVESTIGATOR"
    CASEWORKER = "CASEWORKER"
    LICENSING = "LICENSING"


class ReferralStatus(str, Enum):
    RECEIVED = "RECEIVED"
    SCREENED_IN = "SCREENED_IN"
    SCREENED_OUT = "SCREENED_OUT"
    LINKED = "LINKED"


class ResponsePriority(str, Enum):
    P1_24H = "P1_24H"
    P2_72H = "P2_72H"
    P3_10D = "P3_10D"


class InvestigationStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    SAFE = "SAFE"
    UNSAFE = "UNSAFE"
    CONDITIONALLY_SAFE = "CONDITIONALLY_SAFE"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    IN_PLACEMENT = "IN_PLACEMENT"
    PERMANENCY_PLANNING = "PERMANENCY_PLANNING"
    CLOSED_REUNIFIED = "CLOSED_REUNIFIED"
    CLOSED_ADOPTED = "CLOSED_ADOPTED"
    CLOSED_APPLA = "CLOSED_APPLA"


class PermanencyGoal(str, Enum):
    REUNIFICATION = "REUNIFICATION"
    ADOPTION = "ADOPTION"
    APPLA = "APPLA"


class ChildStatus(str, Enum):
    IN_HOME = "IN_HOME"
    REMOVED = "REMOVED"
    PLACED = "PLACED"
    TRIAL_HOME_VISIT = "TRIAL_HOME_VISIT"
    PERMANENT = "PERMANENT"
    AGED_OUT = "AGED_OUT"


class LicenseStatus(str, Enum):
    PENDING = "PENDING"
    LICENSED = "LICENSED"
    PROVISIONAL = "PROVISIONAL"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class ScreeningStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"


class PlacementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISRUPTED = "DISRUPTED"
    ENDED_REUNIFIED = "ENDED_REUNIFIED"
    ENDED_ADOPTED = "ENDED_ADOPTED"


class CasePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    REVISION = "REVISION"
    COMPLETED = "COMPLETED"


class VisitationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OCCURRED = "OCCURRED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class Supervision(str, Enum):
    SUPERVISED = "SUPERVISED"
    UNSUPERVISED = "UNSUPERVISED"


class HearingType(str, Enum):
    SHELTER = "SHELTER"
    ADJUDICATION = "ADJUDICATION"
    DISPOSITION = "DISPOSITION"
    REVIEW = "REVIEW"
    PERMANENCY = "PERMANENCY"
    TPR = "TPR"


class HearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    CONTINUED = "CONTINUED"
    VACATED = "VACATED"


class HearingRuling(str, Enum):
    CONTINUE_PLACEMENT = "CONTINUE_PLACEMENT"
    RETURN_HOME = "RETURN_HOME"
    CHANGE_GOAL_ADOPTION = "CHANGE_GOAL_ADOPTION"
    TERMINATE_RIGHTS = "TERMINATE_RIGHTS"


# --------------------------------------------------------------------------
# Entity TypedDicts (all carry id + created_at + updated_at + version)
# --------------------------------------------------------------------------
class Caseworker(TypedDict):
    id: str
    full_name: str
    role_type: str
    email: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    status: str
    reporter_type: str
    child_name: str
    alleged_maltreatment: str
    priority_factors: List[str]
    response_priority: Optional[str]
    screening_score: Optional[int]
    screened_in_by: Optional[str]
    linked_case_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Investigation(TypedDict):
    id: str
    referral_id: str
    investigator_id: str
    status: str
    safety_factors: List[str]
    protective_capacity: Optional[int]
    safety_decision_score: Optional[int]
    removal_recommended: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict):
    id: str
    investigation_id: str
    status: str
    removal_date: Optional[str]
    permanency_goal: str
    months_in_care: int
    tpr_clock_breached: bool
    created_at: str
    updated_at: str
    version: int


class Child(TypedDict):
    id: str
    case_id: str
    full_name: str
    date_of_birth: str
    status: str
    current_placement_id: Optional[str]
    age_years: int
    created_at: str
    updated_at: str
    version: int


class FosterHome(TypedDict):
    id: str
    licensing_worker_id: str
    home_name: str
    bed_capacity: int
    license_status: str
    license_expires_at: Optional[str]
    max_age_years: int
    accepts_maltreatment: List[str]
    active_placement_count: int
    clearances_complete: bool
    created_at: str
    updated_at: str
    version: int


class CaregiverScreening(TypedDict):
    id: str
    foster_home_id: str
    member_name: str
    status: str
    disqualifying: bool
    created_at: str
    updated_at: str
    version: int


class Placement(TypedDict):
    id: str
    child_id: str
    foster_home_id: str
    case_id: str
    status: str
    start_at: str
    end_at: Optional[str]
    match_score: int
    created_at: str
    updated_at: str
    version: int


class CasePlan(TypedDict):
    id: str
    case_id: str
    status: str
    required_visits_per_month: int
    objectives_total: int
    objectives_met: int
    compliance_pct: float
    created_at: str
    updated_at: str
    version: int


class Visitation(TypedDict):
    id: str
    case_plan_id: str
    child_id: str
    status: str
    supervision: str
    window_start: str
    window_end: str
    created_at: str
    updated_at: str
    version: int


class Hearing(TypedDict):
    id: str
    case_id: str
    hearing_type: str
    status: str
    scheduled_at: str
    ruling: Optional[str]
    created_at: str
    updated_at: str
    version: int
