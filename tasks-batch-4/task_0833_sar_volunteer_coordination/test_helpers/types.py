"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    COORDINATOR = "Coordinator"
    INCIDENT_COMMANDER = "IncidentCommander"
    FINANCE_OFFICER = "FinanceOfficer"
    MEMBER = "Member"


class IncidentStatus(str, Enum):
    PLANNING = "PLANNING"
    ACTIVE = "ACTIVE"
    DEMOBILIZING = "DEMOBILIZING"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class TaskStatus(str, Enum):
    DRAFT = "DRAFT"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    SUSPENDED = "SUSPENDED"
    DEBRIEFED = "DEBRIEFED"
    CANCELLED = "CANCELLED"


class TeamStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    STANDBY = "STANDBY"
    DEPLOYED = "DEPLOYED"


class CertificationStatus(str, Enum):
    VALID = "VALID"
    EXPIRED = "EXPIRED"


class CalloutStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    STANDBY = "STANDBY"
    DEPLOYED = "DEPLOYED"
    DEMOBILIZED = "DEMOBILIZED"
    DECLINED = "DECLINED"
    NO_RESPONSE = "NO_RESPONSE"


class ResourceStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class ResourceAssignmentStatus(str, Enum):
    RESERVED = "RESERVED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class ClueStatus(str, Enum):
    LOGGED = "LOGGED"
    ACTIONABLE = "ACTIONABLE"
    DISMISSED = "DISMISSED"
    RESOLVED = "RESOLVED"


class ReimbursementClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAID = "PAID"


class AfterActionReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


# --- Entity TypedDicts (common_fields: true -> id, created_at, updated_at, version) ---

class Incident(TypedDict):
    id: str
    name: str
    incident_type: str
    ics_incident_number: str
    operational_period_hours: int
    status: str
    active_task_count: int
    total_logged_hours: float
    total_mileage_miles: int
    total_approved_reimbursement_cents: int
    created_at: str
    updated_at: str
    version: int


class Task(TypedDict):
    id: str
    incident_id: str
    task_number: str
    task_type: str
    priority: str
    segment_area_sqkm: float
    planned_searcher_hours: float
    required_cert_types: List[str]
    max_responders: int
    planned_start: str
    planned_end: str
    status: str
    estimated_coverage_pct: float
    actual_coverage_pct: float
    created_at: str
    updated_at: str
    version: int


class Team(TypedDict):
    id: str
    name: str
    team_type: str
    base_location: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    team_id: str
    full_name: str
    email: str
    member_role: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict):
    id: str
    member_id: str
    cert_type: str
    issued_date: str
    expires_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Callout(TypedDict):
    id: str
    task_id: str
    member_id: str
    status: str
    requested_at: str
    deployed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Resource(TypedDict):
    id: str
    name: str
    resource_type: str
    handler_member_id: Optional[str]
    status: str
    out_of_service: bool
    active_assignment_count: int
    created_at: str
    updated_at: str
    version: int


class ResourceAssignment(TypedDict):
    id: str
    resource_id: str
    task_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Clue(TypedDict):
    id: str
    incident_id: str
    task_id: Optional[str]
    clue_number: str
    clue_priority: str
    description: str
    found_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ReimbursementClaim(TypedDict):
    id: str
    member_id: str
    incident_id: str
    declared_mileage_miles: int
    meal_count: int
    lodging_nights: int
    status: str
    estimated_amount_cents: int
    final_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class AfterActionReport(TypedDict):
    id: str
    incident_id: str
    summary: str
    lessons_learned: str
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only entity (common_fields: false -> only id + created_at) ---

class GroundTrack(TypedDict):
    id: str
    task_id: str
    member_id: str
    recorded_at: str
    distance_km: float
    duration_min: int
    coverage_area_sqkm: float
    created_at: str
