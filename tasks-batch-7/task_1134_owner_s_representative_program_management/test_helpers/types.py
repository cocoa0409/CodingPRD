"""Domain types: entity TypedDicts, status enums, role enum.

Per PRD §2.4 every resource carries id/created_at/updated_at/version EXCEPT
LessonEntry, which is append-only and carries only id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Any


# ---------- Role enum (PRD §2.1) ----------
class UserRole(str, Enum):
    OWNER_REP_PM = "OwnerRepPM"
    OWNER_REP_EXECUTIVE = "OwnerRepExecutive"
    OWNER = "Owner"


# ---------- Status enums (PRD §3) ----------
class ProgramStatus(str, Enum):
    CHARTERING = "CHARTERING"
    ACTIVE = "ACTIVE"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class CharterStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    RETURNED = "RETURNED"
    SUPERSEDED = "SUPERSEDED"


class BaselineStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    RETURNED = "RETURNED"
    SUPERSEDED = "SUPERSEDED"


class ContractStatus(str, Enum):
    SOLICITED = "SOLICITED"
    UNDER_NEGOTIATION = "UNDER_NEGOTIATION"
    COUNTERED = "COUNTERED"
    EXECUTED = "EXECUTED"
    COMPLETED = "COMPLETED"


class ChangeOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    RECOMMEND_APPROVAL = "RECOMMEND_APPROVAL"
    RECOMMEND_REJECTION = "RECOMMEND_REJECTION"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOID = "VOID"


class RiskEntryStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    ASSESSED = "ASSESSED"
    MITIGATING = "MITIGATING"
    MONITORING = "MONITORING"
    ESCALATED = "ESCALATED"
    REALIZED = "REALIZED"
    CLOSED = "CLOSED"


class ContingencyDrawdownStatus(str, Enum):
    RESERVED = "RESERVED"
    COMMITTED = "COMMITTED"
    DRAWN = "DRAWN"
    RELEASED = "RELEASED"


class DrawdownSource(str, Enum):
    MANUAL_RESERVE = "MANUAL_RESERVE"
    RISK_REALIZATION = "RISK_REALIZATION"
    CHANGE_ORDER = "CHANGE_ORDER"


class OwnerReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"


class EngagementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    CANCELLED = "CANCELLED"


class OccupancyPlanStatus(str, Enum):
    PLANNING = "PLANNING"
    COORDINATING = "COORDINATING"
    READY = "READY"
    EXECUTING = "EXECUTING"
    COMPLETE = "COMPLETE"


class MoveInWaveStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class CloseoutItemStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"


class ContingencyPosture(str, Enum):
    NORMAL = "NORMAL"
    WATCH = "WATCH"
    CRITICAL = "CRITICAL"


class ContractType(str, Enum):
    CONSULTANT = "CONSULTANT"
    CONTRACTOR = "CONTRACTOR"


class RiskCategory(str, Enum):
    SCHEDULE = "SCHEDULE"
    COST = "COST"
    SCOPE = "SCOPE"
    STAKEHOLDER = "STAKEHOLDER"
    SITE = "SITE"


class GroupType(str, Enum):
    USER_GROUP = "USER_GROUP"
    AUTHORITIES = "AUTHORITIES"
    COMMUNITY = "COMMUNITY"
    OPERATIONS = "OPERATIONS"


class DockResource(str, Enum):
    DOCK_A = "DOCK_A"
    DOCK_B = "DOCK_B"
    DOCK_C = "DOCK_C"


class CloseoutItemType(str, Enum):
    PUNCH_LIST = "PUNCH_LIST"
    WARRANTY = "WARRANTY"
    AS_BUILT = "AS_BUILT"
    FINAL_ACCOUNT = "FINAL_ACCOUNT"
    TRAINING = "TRAINING"


class LessonCategory(str, Enum):
    SCHEDULE = "SCHEDULE"
    COST = "COST"
    SCOPE = "SCOPE"
    STAKEHOLDER = "STAKEHOLDER"
    SITE = "SITE"
    PROCUREMENT = "PROCUREMENT"


# ---------- Entity TypedDicts ----------
# common_fields: true entities — id + created_at + updated_at + version

class Program(TypedDict, total=False):
    id: str
    program_name: str
    owner_organization: str
    status: str
    current_budget_cents: Optional[int]
    contingency_total_cents: int
    contingency_reserved_cents: int
    contingency_committed_cents: int
    contingency_drawn_cents: int
    contingency_available_cents: int
    contingency_posture: str
    approved_charter_id: Optional[str]
    approved_baseline_id: Optional[str]
    baseline_version_no: Optional[int]
    target_finish_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Charter(TypedDict, total=False):
    id: str
    program_id: str
    version_no: int
    objectives: str
    scope_statement: str
    status: str
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    return_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BaselineLine(TypedDict):
    cost_code: str
    amount_cents: int


class Baseline(TypedDict, total=False):
    id: str
    program_id: str
    version_no: int
    total_budget_cents: int
    contingency_total_cents: int
    target_finish_date: str
    lines: List[BaselineLine]
    status: str
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    return_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict, total=False):
    id: str
    program_id: str
    vendor_name: str
    contract_type: str
    solicitation_estimate_cents: int
    status: str
    negotiator_user_id: Optional[str]
    negotiation_rounds: int
    latest_counter_amount_cents: Optional[int]
    awarded_amount_cents: Optional[int]
    current_commitment_cents: Optional[int]
    executed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AllocatedLine(TypedDict):
    cost_code: str
    allocated_cents: int


class ChangeOrder(TypedDict, total=False):
    id: str
    program_id: str
    contract_id: str
    supersedes_id: Optional[str]
    superseded_by_id: Optional[str]
    title: str
    reason: str
    amount_cents: int
    allocated_lines: List[AllocatedLine]
    status: str
    recommended_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    linked_drawdown_id: Optional[str]
    revision_note: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RiskEntry(TypedDict, total=False):
    id: str
    program_id: str
    title: str
    category: str
    probability_pct: int
    impact_cents: int
    exposure_cents: int
    status: str
    mitigation_plan: Optional[str]
    realized_loss_cents: Optional[int]
    linked_drawdown_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ContingencyDrawdown(TypedDict, total=False):
    id: str
    program_id: str
    risk_entry_id: Optional[str]
    change_order_id: Optional[str]
    source: str
    purpose: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OwnerReport(TypedDict, total=False):
    id: str
    program_id: str
    period: str
    status: str
    eac_commitment_based_cents: int
    eac_trend_based_cents: int
    budget_variance_commitment_cents: int
    budget_variance_trend_cents: int
    contingency_posture_snapshot: str
    baseline_version_no_snapshot: Optional[int]
    submitted_by_user_id: Optional[str]
    accepted_by_user_id: Optional[str]
    return_note: Optional[str]
    accepted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StakeholderGroup(TypedDict, total=False):
    id: str
    program_id: str
    group_name: str
    group_type: str
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class EngagementItem(TypedDict, total=False):
    id: str
    program_id: str
    stakeholder_group_id: str
    title: str
    scheduled_start: str
    scheduled_end: str
    duration_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OccupancyPlan(TypedDict, total=False):
    id: str
    program_id: str
    plan_name: str
    target_move_month: str
    status: str
    readiness_unweighted_pct: float
    readiness_weighted_pct: float
    created_at: str
    updated_at: str
    version: int


class MoveInWave(TypedDict, total=False):
    id: str
    program_id: str
    occupancy_plan_id: str
    stakeholder_group_id: str
    wave_name: str
    dock_resource: str
    move_start: str
    move_end: str
    criticality_weight: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CloseoutItem(TypedDict, total=False):
    id: str
    program_id: str
    item_type: str
    title: str
    status: str
    submitted_by_user_id: Optional[str]
    verified_by_user_id: Optional[str]
    rejection_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only LessonEntry: id + created_at ONLY (PRD §2.4)
class LessonEntry(TypedDict, total=False):
    id: str
    program_id: str
    category: str
    lesson_text: str
    recommendation: str
    created_at: str
