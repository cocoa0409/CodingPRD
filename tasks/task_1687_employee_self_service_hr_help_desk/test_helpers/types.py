"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    EMPLOYEE = "Employee"
    HELP_DESK_AGENT = "HelpDeskAgent"
    SPECIALIST_AGENT = "SpecialistAgent"
    SENSITIVE_CASE_MANAGER = "SensitiveCaseManager"
    KNOWLEDGE_MANAGER = "KnowledgeManager"
    HR_DATA_STEWARD = "HRDataSteward"
    WORKFORCE_PLANNER = "WorkforcePlanner"
    HR_SERVICES_ADMIN = "HRServicesAdmin"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------

class EmployeeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    TERMINATED = "TERMINATED"


class AgentTier(str, Enum):
    T1 = "T1"
    T2 = "T2"


class AgentClearance(str, Enum):
    STANDARD = "STANDARD"
    SENSITIVE = "SENSITIVE"


class TicketPriority(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class ClockMode(str, Enum):
    WALL_CLOCK = "WALL_CLOCK"
    BUSINESS_HOURS = "BUSINESS_HOURS"


class TicketWorkflowStatus(str, Enum):
    NEW = "NEW"
    TRIAGED = "TRIAGED"
    IN_PROGRESS = "IN_PROGRESS"
    PENDING_EMPLOYEE = "PENDING_EMPLOYEE"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class TicketSlaStatus(str, Enum):
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    BREACHED_RESPONSE = "BREACHED_RESPONSE"
    BREACHED_RESOLUTION = "BREACHED_RESOLUTION"
    MET = "MET"


class KbArticleStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"


class DeflectionOutcome(str, Enum):
    NONE = "NONE"
    TICKET_CREATED = "TICKET_CREATED"


class TicketEventType(str, Enum):
    CREATED = "CREATED"
    TRIAGED = "TRIAGED"
    ASSIGNED = "ASSIGNED"
    UNASSIGNED = "UNASSIGNED"
    RESPONDED = "RESPONDED"
    INFO_REQUESTED = "INFO_REQUESTED"
    INFO_PROVIDED = "INFO_PROVIDED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    AUTO_CLOSED = "AUTO_CLOSED"
    SLA_BREACH = "SLA_BREACH"
    COACHING_RELEASE = "COACHING_RELEASE"


class ChangeType(str, Enum):
    ADDRESS = "ADDRESS"
    DIRECT_DEPOSIT = "DIRECT_DEPOSIT"


class DcrApprovalStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class DcrFraudStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    LOCKED = "LOCKED"


class FraudMethod(str, Enum):
    SECURITY_CODE = "SECURITY_CODE"
    MANAGER_CONFIRMATION = "MANAGER_CONFIRMATION"


class FraudVerificationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    LOCKED = "LOCKED"


class SurveyStatus(str, Enum):
    ISSUED = "ISSUED"
    SUBMITTED = "SUBMITTED"
    EXPIRED = "EXPIRED"


class StaffingWindowStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AgentShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class CoveragePosture(str, Enum):
    UNDER_STAFFED = "UNDER_STAFFED"
    ADEQUATE = "ADEQUATE"
    SURPLUS = "SURPLUS"


class BankAccountType(str, Enum):
    CHECKING = "CHECKING"
    SAVINGS = "SAVINGS"


class ChangeSource(str, Enum):
    DCR_APPLIED = "DCR_APPLIED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# Primary resources carry id + created_at + updated_at + version (PRD §2.4).
# Append-only records (ArticleView, TicketEvent, AuditLogEntry) carry only
# id + created_at; both updated_at and version are absent for them.
# ---------------------------------------------------------------------------

class Employee(TypedDict, total=False):
    id: str
    employee_number: str
    full_name: str
    email: str
    status: str
    manager_id: Optional[str]
    address_line1: Optional[str]
    city: Optional[str]
    region: Optional[str]
    postal_code: Optional[str]
    bank_routing_number: Optional[str]
    bank_account_number: Optional[str]
    bank_account_type: Optional[str]
    has_pending_dcr: bool
    open_ticket_count: int
    created_at: str
    updated_at: str
    version: int


class Team(TypedDict, total=False):
    id: str
    name: str
    description: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Agent(TypedDict, total=False):
    id: str
    display_name: str
    email: str
    tier: str
    clearance: str
    team_id: str
    capacity_max: int
    active: bool
    assigned_open_count: int
    rolling_csat: Optional[float]
    coaching_hold: bool
    created_at: str
    updated_at: str
    version: int


class TicketCategory(TypedDict, total=False):
    id: str
    code: str
    name: str
    is_sensitive: bool
    specialist_team_id: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class SlaPolicy(TypedDict, total=False):
    id: str
    category_id: str
    priority: str
    first_response_minutes: int
    resolution_minutes: int
    clock_mode: str
    created_at: str
    updated_at: str
    version: int


class KbArticle(TypedDict, total=False):
    id: str
    title: str
    body: str
    keywords: List[str]
    category_id: str
    author_user_id: str
    status: str
    supersedes_article_id: Optional[str]
    published_at: Optional[str]
    published_by_user_id: Optional[str]
    view_count: int
    deflection_fail_count: int
    created_at: str
    updated_at: str
    version: int


class ArticleView(TypedDict, total=False):
    # Append-only record: id + created_at only (no updated_at, no version).
    id: str
    employee_id: str
    article_id: str
    viewed_at: str
    deflection_outcome: str
    created_at: str


class Ticket(TypedDict, total=False):
    id: str
    employee_id: str
    category_id: str
    subject: str
    description: str
    priority: str
    sensitive: bool
    tier: str
    workflow_status: str
    sla_status: str
    assigned_agent_id: Optional[str]
    source_article_id: Optional[str]
    resolution_article_id: Optional[str]
    resolution_summary: Optional[str]
    first_response_due_at: str
    resolution_due_at: str
    first_responded_at: Optional[str]
    resolved_at: Optional[str]
    closed_at: Optional[str]
    escalation_count: int
    reopen_count: int
    masked: bool
    created_at: str
    updated_at: str
    version: int


class TicketEvent(TypedDict, total=False):
    # Append-only record: id + created_at only (no updated_at, no version).
    id: str
    ticket_id: str
    actor_user_id: str
    event_type: str
    from_state: Optional[str]
    to_state: Optional[str]
    note: Optional[str]
    created_at: str


class DataChangeRequest(TypedDict, total=False):
    id: str
    employee_id: str
    change_type: str
    new_values: dict
    approval_status: str
    fraud_status: str
    submitted_at: str
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    applied_at: Optional[str]
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FraudVerification(TypedDict, total=False):
    id: str
    dcr_id: str
    method: str
    challenge_code: str
    attempts: int
    status: str
    verified_by_user_id: Optional[str]
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SurveyResponse(TypedDict, total=False):
    id: str
    ticket_id: str
    employee_id: str
    agent_id: Optional[str]
    status: str
    score: Optional[int]
    comment: Optional[str]
    issued_at: str
    expires_at: str
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StaffingWindow(TypedDict, total=False):
    id: str
    team_id: str
    name: str
    window_start: str
    window_end: str
    required_t1_hours: float
    required_t2_hours: float
    sla_multiplier: float
    status: str
    covered_t1_hours: float
    covered_t2_hours: float
    coverage_posture: str
    created_at: str
    updated_at: str
    version: int


class AgentShift(TypedDict, total=False):
    id: str
    agent_id: str
    staffing_window_id: str
    shift_start: str
    shift_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditLogEntry(TypedDict, total=False):
    # Append-only record: id + created_at only (no updated_at, no version).
    id: str
    employee_id: str
    dcr_id: str
    field_changed: str
    old_value: Optional[str]
    new_value: str
    changed_by_user_id: str
    change_source: str
    created_at: str
