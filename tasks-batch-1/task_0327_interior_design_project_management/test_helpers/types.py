"""Domain types: entity TypedDicts, status enums, role enum (Interior Design PM API)."""
from enum import Enum
from typing import TypedDict, List, Optional


# ─── Role enum ────────────────────────────────────────────
class UserRole(str, Enum):
    STUDIO_ADMIN = "StudioAdmin"
    DESIGNER = "Designer"
    PROCUREMENT_COORDINATOR = "ProcurementCoordinator"
    CLIENT = "Client"


# ─── Status enums ─────────────────────────────────────────
class ProjectStatus(str, Enum):
    BRIEFING = "BRIEFING"
    IN_DESIGN = "IN_DESIGN"
    PROCUREMENT = "PROCUREMENT"
    INSTALLATION = "INSTALLATION"
    CLOSED = "CLOSED"
    ON_HOLD = "ON_HOLD"


class ProjectPosture(str, Enum):
    OPEN = "OPEN"
    BUDGET_REVIEW = "BUDGET_REVIEW"
    FROZEN = "FROZEN"


class BudgetStatus(str, Enum):
    GREEN = "GREEN"
    AMBER = "AMBER"
    RED = "RED"


class FeeModel(str, Enum):
    FLAT = "FLAT"
    HOURLY = "HOURLY"
    MARKUP = "MARKUP"


class RoomStatus(str, Enum):
    SCOPING = "SCOPING"
    MOODBOARD_READY = "MOODBOARD_READY"
    APPROVED = "APPROVED"
    REWORK = "REWORK"


class MoodBoardStatus(str, Enum):
    DRAFT = "DRAFT"
    PRESENTED = "PRESENTED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


class FFECategory(str, Enum):
    FURNITURE = "FURNITURE"
    LIGHTING = "LIGHTING"
    TEXTILE = "TEXTILE"
    DECOR = "DECOR"
    FIXTURE = "FIXTURE"


class SelectionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    SPECIFIED = "SPECIFIED"
    ORDERED = "ORDERED"
    WITHDRAWN = "WITHDRAWN"


class VendorTrade(str, Enum):
    SUPPLIER = "SUPPLIER"
    UPHOLSTERY = "UPHOLSTERY"
    MILLWORK = "MILLWORK"
    ELECTRICAL = "ELECTRICAL"
    GENERAL = "GENERAL"


class VendorStanding(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    ORDERED = "ORDERED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    RETURNED = "RETURNED"


class RevisionTargetKind(str, Enum):
    ROOM = "ROOM"
    SELECTION = "SELECTION"


class RevisionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class PunchSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    BLOCKING = "BLOCKING"


class PunchStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    WAIVED = "WAIVED"


class TimeEntryStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# ─── Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ───
class Project(TypedDict):
    id: str
    client_name: str
    client_user_id: str
    brief_summary: str
    budget_cents: int
    fee_model: str
    flat_fee_cents: int
    hourly_rate_cents: int
    markup_pct: float
    status: str
    posture: str
    committed_cents: int
    design_fee_cents: int
    budget_remaining_cents: int
    budget_status: str
    client_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    display_name: str
    email: str
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict):
    id: str
    project_id: str
    name: str
    scope_note: str
    room_budget_cents: int
    status: str
    approved_moodboard_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MoodBoard(TypedDict):
    id: str
    room_id: str
    title: str
    palette: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FFEItem(TypedDict):
    id: str
    sku: str
    name: str
    category: str
    list_unit_cost_cents: int
    lead_time_days: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class DesignSelection(TypedDict):
    id: str
    project_id: str
    room_id: str
    ffe_item_id: str
    quantity: int
    unit_cost_cents: int
    trade_discount_pct: float
    spec_note: str
    status: str
    line_net_cents: int
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict):
    id: str
    name: str
    trade: str
    standing: str
    lead_time_buffer_days: int
    created_at: str
    updated_at: str
    version: int


class ProcurementOrder(TypedDict):
    id: str
    project_id: str
    vendor_id: str
    window_start: str
    window_end: str
    status: str
    order_subtotal_cents: int
    amount_paid_cents: int
    balance_due_cents: int
    expected_delivery_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only join row: ONLY id + created_at
class OrderLine(TypedDict):
    id: str
    order_id: str
    selection_id: str
    line_net_cents_snapshot: int
    created_at: str


class RevisionRequest(TypedDict):
    id: str
    project_id: str
    target_kind: str
    target_id: str
    note: str
    round_no: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PunchListItem(TypedDict):
    id: str
    order_id: str
    description: str
    severity: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TimeEntry(TypedDict):
    id: str
    project_id: str
    designer_user_id: str
    minutes: int
    billable: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentReceipt(TypedDict):
    id: str
    project_id: str
    amount_cents: int
    received_at: str
    memo: str
    created_at: str
    updated_at: str
    version: int
