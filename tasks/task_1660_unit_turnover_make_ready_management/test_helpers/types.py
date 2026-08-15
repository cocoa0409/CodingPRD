"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    REGIONAL_MANAGER = "RegionalManager"
    PROPERTY_MANAGER = "PropertyManager"
    TURN_COORDINATOR = "TurnCoordinator"
    VENDOR = "Vendor"
    INSPECTOR = "Inspector"
    PLATFORM_ADMIN = "PlatformAdmin"


class UnitStatus(str, Enum):
    OCCUPIED = "OCCUPIED"
    NOTICE = "NOTICE"
    IN_TURN = "IN_TURN"
    READY = "READY"


class TurnStatus(str, Enum):
    OPEN = "OPEN"
    SCOPED = "SCOPED"
    IN_PROGRESS = "IN_PROGRESS"
    REWORK = "REWORK"
    READY = "READY"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ScopeCategory(str, Enum):
    REPAIR = "REPAIR"
    PAINT = "PAINT"
    CARPET = "CARPET"
    CLEAN = "CLEAN"
    APPLIANCE = "APPLIANCE"
    FIXTURE = "FIXTURE"
    OTHER = "OTHER"


class ScopeItemStatus(str, Enum):
    PLANNED = "PLANNED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    VOIDED = "VOIDED"
    REJECTED = "REJECTED"


class Classification(str, Enum):
    EXPENSE = "EXPENSE"
    CAPITAL = "CAPITAL"


class ApprovalTier(str, Enum):
    NONE = "NONE"
    PM = "PM"
    RM = "RM"


class VendorTrade(str, Enum):
    REPAIR = "REPAIR"
    PAINT = "PAINT"
    CARPET = "CARPET"
    CLEAN = "CLEAN"


class AssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACCEPTED = "ACCEPTED"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class DecisionType(str, Enum):
    REPAIR = "REPAIR"
    REPLACE = "REPLACE"


class ReplacementPolicy(str, Enum):
    PERCENT_OF_REPLACE = "PERCENT_OF_REPLACE"
    COST_PER_YEAR = "COST_PER_YEAR"


class CommitmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    AT_RISK = "AT_RISK"
    FULFILLED = "FULFILLED"
    BREACHED = "BREACHED"
    CANCELLED = "CANCELLED"


# --- Entities carrying the full system-managed field set (PRD §2.4) ---


class Property(TypedDict, total=False):
    id: str
    name: str
    days_to_ready_target: int
    pm_threshold_bp: int
    rm_threshold_bp: int
    capital_threshold_cents: int
    replacement_policy: str
    benchmark_turn_count: int
    avg_booked_expense_cents: int
    avg_days_to_ready: int
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict, total=False):
    id: str
    property_id: str
    unit_number: str
    square_feet: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Turn(TypedDict, total=False):
    id: str
    unit_id: str
    notice_date: str
    move_out_date: str
    status: str
    started_on: Optional[str]
    target_ready_date: Optional[str]
    actual_ready_date: Optional[str]
    projected_ready_date: Optional[str]
    approved_budget_cents: int
    estimated_cost_cents: int
    expense_actual_cents: int
    capital_actual_cents: int
    total_actual_cents: int
    booked_expense_cents: int
    created_at: str
    updated_at: str
    version: int


class ScopeItem(TypedDict, total=False):
    id: str
    turn_id: str
    category: str
    description: str
    estimated_cost_cents: int
    actual_cost_cents: Optional[int]
    classification: str
    sequence_rank: int
    approval_tier: str
    status: str
    rework_of_item_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict, total=False):
    id: str
    name: str
    trade: str
    open_assignment_count: int
    created_at: str
    updated_at: str
    version: int


class VendorAssignment(TypedDict, total=False):
    id: str
    scope_item_id: str
    vendor_id: str
    start_date: str
    end_date: str
    status: str
    actual_cost_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class LeaseCommitment(TypedDict, total=False):
    id: str
    unit_id: str
    applicant_name: str
    committed_delivery_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Immutable one-time-event records (PRD §2.4): id + created_at only ---


class Inspection(TypedDict, total=False):
    id: str
    turn_id: str
    result: str
    failed_scope_item_ids: Optional[List[str]]
    notes: Optional[str]
    created_at: str


class ReplacementDecision(TypedDict, total=False):
    id: str
    turn_id: str
    scope_item_id: str
    repair_estimate_cents: int
    replace_estimate_cents: int
    repair_life_years: int
    remaining_life_years: int
    decision: str
    policy_applied: str
    resulting_classification: str
    created_at: str
