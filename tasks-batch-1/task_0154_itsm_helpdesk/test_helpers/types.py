"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resource model described in the PRD: tickets carry two independent
state axes (lifecycle and SLA), change requests fan out to a CAB, problems
graduate to known errors, and assets carry their own health lifecycle.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------- #
# Roles (PRD §2.1 — exactly five roles, spelled precisely)
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    REQUESTER = "Requester"
    AGENT = "Agent"
    CHANGE_MANAGER = "ChangeManager"
    CAB_MEMBER = "CabMember"
    PLATFORM_ADMIN = "PlatformAdmin"


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #
class Priority(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class TicketLifecycleState(str, Enum):
    NEW = "NEW"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    PENDING_CHANGE = "PENDING_CHANGE"
    ON_HOLD = "ON_HOLD"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class TicketSlaState(str, Enum):
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    RESPONSE_BREACHED = "RESPONSE_BREACHED"
    RESOLVE_BREACHED = "RESOLVE_BREACHED"
    MET = "MET"


class ProblemState(str, Enum):
    OPEN = "OPEN"
    ROOT_CAUSE_IDENTIFIED = "ROOT_CAUSE_IDENTIFIED"
    KNOWN_ERROR = "KNOWN_ERROR"
    RESOLVED = "RESOLVED"


class ChangeRequestState(str, Enum):
    DRAFT = "DRAFT"
    PENDING_CAB = "PENDING_CAB"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    IMPLEMENTED = "IMPLEMENTED"
    FAILED = "FAILED"


class ChangeRisk(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class VoteDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class AssetKind(str, Enum):
    SERVER = "SERVER"
    LAPTOP = "LAPTOP"
    NETWORK_DEVICE = "NETWORK_DEVICE"
    APPLICATION = "APPLICATION"


class AssetStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    DEGRADED = "DEGRADED"
    RETIRED = "RETIRED"


# --------------------------------------------------------------------------- #
# Entity TypedDicts
# Resources with the full id + created_at + updated_at + version triple.
# --------------------------------------------------------------------------- #
class Category(TypedDict, total=False):
    id: str
    name: str
    default_priority: str
    sla_policy_id: str
    default_assignment_group_id: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class SlaPolicy(TypedDict, total=False):
    id: str
    name: str
    response_target_minutes: int
    resolve_target_minutes: int
    ola_target_minutes: int
    priority_multipliers: dict
    created_at: str
    updated_at: str
    version: int


class AssignmentGroup(TypedDict, total=False):
    id: str
    name: str
    is_fulfilment_group: bool
    queue_depth: int
    created_at: str
    updated_at: str
    version: int


class Ticket(TypedDict, total=False):
    id: str
    short_description: str
    requester_id: str
    category_id: str
    priority: str
    assignment_group_id: str
    assignee_user_id: Optional[str]
    lifecycle_state: str
    sla_state: str
    problem_id: Optional[str]
    deflected: bool
    reopen_count: int
    opened_at: str
    response_due_at: Optional[str]
    resolve_due_at: Optional[str]
    paused_total_minutes: int
    change_request_id: Optional[str]
    asset_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Problem(TypedDict, total=False):
    id: str
    title: str
    owner_user_id: str
    state: str
    linked_ticket_count: int
    asset_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class KnownError(TypedDict, total=False):
    id: str
    problem_id: str
    symptom: str
    workaround: str
    published: bool
    created_at: str
    updated_at: str
    version: int


class KbArticle(TypedDict, total=False):
    id: str
    title: str
    category_id: str
    body: str
    view_count: int
    deflection_count: int
    created_at: str
    updated_at: str
    version: int


class ChangeRequest(TypedDict, total=False):
    id: str
    title: str
    ticket_id: str
    raised_by_user_id: str
    risk: str
    state: str
    required_approvals: int
    approve_count: int
    reject_count: int
    created_at: str
    updated_at: str
    version: int


class CsatSurvey(TypedDict, total=False):
    id: str
    ticket_id: str
    score: int
    comment: Optional[str]
    counts_toward_index: bool
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict, total=False):
    id: str
    asset_tag: str
    kind: str
    status: str
    open_incident_count: int
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# Append-only event record (PRD §2.4): a CabVote carries ONLY id + created_at;
# it has no updated_at and no version because a cast vote is immutable.
# --------------------------------------------------------------------------- #
class CabVote(TypedDict, total=False):
    id: str
    change_request_id: str
    voter_user_id: str
    decision: str
    created_at: str
