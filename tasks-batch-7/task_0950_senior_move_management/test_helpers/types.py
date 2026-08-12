"""Domain types for the Senior Move Management API: status enums and entity shapes."""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PLATFORM_ADMIN"
    MOVE_MANAGER = "MOVE_MANAGER"
    BILLING_ADMIN = "BILLING_ADMIN"
    CREW_LEAD = "CREW_LEAD"
    VENDOR = "VENDOR"
    CLIENT = "CLIENT"
    FAMILY_MEMBER = "FAMILY_MEMBER"
    POWER_OF_ATTORNEY = "POWER_OF_ATTORNEY"


class EngagementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class EngagementPhase(str, Enum):
    ASSESSMENT = "ASSESSMENT"
    SORT_PLAN = "SORT_PLAN"
    PACK = "PACK"
    MOVE_DAY = "MOVE_DAY"
    SETTLE_IN = "SETTLE_IN"
    CLOSE_OUT = "CLOSE_OUT"
    DONE = "DONE"


class BillingMode(str, Enum):
    HOURLY = "HOURLY"
    PACKAGE = "PACKAGE"


class HomeTier(str, Enum):
    STUDIO = "STUDIO"
    ONE_BED = "ONE_BED"
    TWO_BED = "TWO_BED"
    HOUSE = "HOUSE"


class PartyType(str, Enum):
    CLIENT = "CLIENT"
    FAMILY_MEMBER = "FAMILY_MEMBER"
    POA = "POA"
    MOVE_MANAGER_STAFF = "MOVE_MANAGER_STAFF"


class AuthorityScope(str, Enum):
    FULL = "FULL"
    DISPOSITION_ONLY = "DISPOSITION_ONLY"
    BILLING_ONLY = "BILLING_ONLY"


class AuthorityStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class UnitType(str, Enum):
    APARTMENT = "APARTMENT"
    COTTAGE = "COTTAGE"
    ASSISTED_LIVING_SUITE = "ASSISTED_LIVING_SUITE"
    MEMORY_CARE_ROOM = "MEMORY_CARE_ROOM"


class PlacementStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"


class RoomType(str, Enum):
    LIVING = "LIVING"
    BEDROOM = "BEDROOM"
    KITCHEN = "KITCHEN"
    DINING = "DINING"
    STORAGE = "STORAGE"
    BATH = "BATH"


class ItemCategory(str, Enum):
    FURNITURE = "FURNITURE"
    ARTWORK = "ARTWORK"
    JEWELRY = "JEWELRY"
    APPLIANCE = "APPLIANCE"
    LINENS = "LINENS"
    DOCUMENTS = "DOCUMENTS"
    MISC = "MISC"


class AppraisalSource(str, Enum):
    NONE = "NONE"
    SELF_REPORTED = "SELF_REPORTED"
    APPRAISED = "APPRAISED"


class Disposition(str, Enum):
    UNDECIDED = "UNDECIDED"
    KEEP = "KEEP"
    DONATE = "DONATE"
    SELL = "SELL"
    HAUL_AWAY = "HAUL_AWAY"


class HandlingState(str, Enum):
    AT_ORIGIN = "AT_ORIGIN"
    PACKED = "PACKED"
    LOADED = "LOADED"
    DELIVERED = "DELIVERED"
    UNPACKED = "UNPACKED"
    STAGED_FOR_PICKUP = "STAGED_FOR_PICKUP"
    REMOVED = "REMOVED"


class HoldState(str, Enum):
    NONE = "NONE"
    HELD = "HELD"


class FamilyHoldStatus(str, Enum):
    OPEN = "OPEN"
    ESCALATED = "ESCALATED"
    RESOLVED_KEEP = "RESOLVED_KEEP"
    RESOLVED_RELEASE = "RESOLVED_RELEASE"
    WITHDRAWN = "WITHDRAWN"


class HoldResolution(str, Enum):
    KEEP = "KEEP"
    RELEASE = "RELEASE"


class SortPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FROZEN = "FROZEN"


class MoveDayPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    CREWED = "CREWED"
    CONFIRMED = "CONFIRMED"
    FROZEN = "FROZEN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    RESCHEDULED = "RESCHEDULED"


class CrewRole(str, Enum):
    LEAD = "LEAD"
    ORGANIZER = "ORGANIZER"
    PACKER = "PACKER"
    DRIVER = "DRIVER"


class CrewAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    REPLACED = "REPLACED"


class EntryKind(str, Enum):
    LABOR = "LABOR"
    TRAVEL = "TRAVEL"
    BREAK = "BREAK"


class VendorType(str, Enum):
    JUNK_HAUL = "JUNK_HAUL"
    CONSIGNMENT = "CONSIGNMENT"
    APPRAISAL = "APPRAISAL"
    CLEANING = "CLEANING"
    SHREDDING = "SHREDDING"


class ServiceKind(str, Enum):
    HAUL_AWAY = "HAUL_AWAY"
    CONSIGNMENT_PICKUP = "CONSIGNMENT_PICKUP"
    APPRAISAL = "APPRAISAL"
    CLEANING = "CLEANING"
    SHREDDING = "SHREDDING"


class VendorAssignmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACCEPTED = "ACCEPTED"
    SCHEDULED = "SCHEDULED"
    COI_BLOCKED = "COI_BLOCKED"
    PERFORMED = "PERFORMED"
    SIGNED_OFF = "SIGNED_OFF"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class ConsignmentLotStatus(str, Enum):
    LISTED = "LISTED"
    MARKED_DOWN = "MARKED_DOWN"
    SOLD = "SOLD"
    SETTLED = "SETTLED"
    UNSOLD = "UNSOLD"
    RETURNED = "RETURNED"
    HAULED = "HAULED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    FINALIZED = "FINALIZED"


class LineType(str, Enum):
    PACKAGE_BASE = "PACKAGE_BASE"
    HOURLY_LABOR = "HOURLY_LABOR"
    OVERAGE_LABOR = "OVERAGE_LABOR"
    TRAVEL_SURCHARGE = "TRAVEL_SURCHARGE"
    STAIRS_SURCHARGE = "STAIRS_SURCHARGE"
    LONG_CARRY_SURCHARGE = "LONG_CARRY_SURCHARGE"
    VENDOR_PASSTHROUGH = "VENDOR_PASSTHROUGH"
    DISPOSAL_FEE = "DISPOSAL_FEE"
    CONSIGNMENT_CREDIT = "CONSIGNMENT_CREDIT"
    CONSIGNMENT_REVERSAL = "CONSIGNMENT_REVERSAL"
    COORDINATION_FEE = "COORDINATION_FEE"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT"


class MilestoneKey(str, Enum):
    ASSESSMENT = "ASSESSMENT"
    SORT_PLAN = "SORT_PLAN"
    PACK = "PACK"
    MOVE_DAY = "MOVE_DAY"
    SETTLE_IN = "SETTLE_IN"
    CLOSE_OUT = "CLOSE_OUT"


class MilestoneStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    REOPENED = "REOPENED"


class OverdueStatus(str, Enum):
    ON_TIME = "ON_TIME"
    OVERDUE = "OVERDUE"
    RECOVERED = "RECOVERED"


class UnpackPriority(str, Enum):
    ESSENTIALS = "ESSENTIALS"
    STANDARD = "STANDARD"


class UnpackSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    REOPENED = "REOPENED"


class PunchSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class PunchStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"


# ---------------------------------------------------------------------------
# Entity shapes.  Every resource carries id + created_at; almost every one also
# carries updated_at and version.  InvoiceLine is the single exception: a ledger
# line is immutable once written and carries only id and created_at.
# ---------------------------------------------------------------------------


class Client(TypedDict):
    id: str
    full_name: str
    phone: str
    email: Optional[str]
    engagement_count: int
    created_at: str
    updated_at: str
    version: int


class Engagement(TypedDict):
    id: str
    client_id: str
    status: str
    phase: str
    billing_mode: str
    home_tier: str
    package_tier: Optional[str]
    scheduled_move_start_utc: str
    move_freeze_at_utc: str
    mileage_miles: float
    origin_stairs_flights: int
    origin_long_carry_feet: int
    accrued_labor_cents: int
    billing_hours_total: float
    inventory_item_count: int
    total_inventory_volume_cft: float
    keep_volume_cft: float
    haul_volume_cft: float
    consignment_credit_cents: int
    billing_hold: bool
    hold_reason: Optional[str]
    hold_count: int
    cancel_reason: Optional[str]
    closed_at_utc: Optional[str]
    ops_run_seq: int
    created_at: str
    updated_at: str
    version: int


class PortalParty(TypedDict):
    id: str
    engagement_id: str
    client_id: Optional[str]
    party_type: str
    display_name: str
    email: str
    can_approve_dispositions: bool
    active_authority_ceiling_cents: int
    created_at: str
    updated_at: str
    version: int


class AuthorityRecord(TypedDict):
    id: str
    engagement_id: str
    holder_party_id: str
    authority_scope: str
    approval_ceiling_cents: int
    status: str
    effective_from_utc: str
    effective_to_utc: str
    suspend_count: int
    revoked_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DestinationResidence(TypedDict):
    id: str
    engagement_id: str
    name: str
    unit_type: str
    address_line: str
    placement_status: str
    placement_revision: int
    approved_by_party_id: Optional[str]
    approved_at_utc: Optional[str]
    room_count: int
    total_effective_capacity_linear_inches: float
    created_at: str
    updated_at: str
    version: int


class DestinationRoom(TypedDict):
    id: str
    destination_residence_id: str
    room_type: str
    nominal_linear_inches: float
    nominal_volume_cft: float
    approved_addendum_linear_inches: float
    effective_capacity_linear_inches: float
    keep_load_linear_inches: float
    keep_load_volume_cft: float
    headroom_linear_inches: float
    assigned_item_count: int
    created_at: str
    updated_at: str
    version: int


class InventoryItem(TypedDict):
    id: str
    engagement_id: str
    assigned_room_id: Optional[str]
    consignment_lot_id: Optional[str]
    unpack_session_id: Optional[str]
    label: str
    category: str
    footprint_linear_inches: float
    volume_cft: float
    appraised_value_cents: int
    appraisal_source: str
    disposition: str
    disposition_locked: bool
    handling_state: str
    hold_state: str
    redesignation_count: int
    donation_receipt_cents: int
    created_at: str
    updated_at: str
    version: int


class FamilyHold(TypedDict):
    id: str
    inventory_item_id: str
    raised_by_party_id: str
    resolved_by_party_id: Optional[str]
    status: str
    reason: str
    resolution_note: Optional[str]
    escalation_count: int
    remand_count: int
    created_at: str
    updated_at: str
    version: int


class SortPlan(TypedDict):
    id: str
    engagement_id: str
    approved_by_party_id: Optional[str]
    status: str
    notes: Optional[str]
    rejected_reason: Optional[str]
    reopen_count: int
    undecided_count_at_submit: int
    locked_item_count: int
    frozen_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MoveDayPlan(TypedDict):
    id: str
    engagement_id: str
    status: str
    scheduled_start_utc: str
    freeze_at_utc: str
    truck_capacity_cft: float
    truck_count: int
    planned_trip_count: int
    actual_trip_count: Optional[int]
    actual_loaded_volume_cft: Optional[float]
    crew_confirmed_count: int
    crew_min_required: int
    reschedule_count: int
    started_at_utc: Optional[str]
    completed_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CrewMember(TypedDict):
    id: str
    full_name: str
    crew_role: str
    hourly_rate_cents: int
    assignment_count: int
    created_at: str
    updated_at: str
    version: int


class CrewAssignment(TypedDict):
    id: str
    move_day_plan_id: str
    crew_member_id: str
    replaces_assignment_id: Optional[str]
    status: str
    checked_in_at_utc: Optional[str]
    checked_out_at_utc: Optional[str]
    portal_hours: float
    billing_hours: float
    applied_hours: float
    overtime_hours: float
    labor_cents: int
    no_show_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TimeEntry(TypedDict):
    id: str
    crew_assignment_id: str
    entry_kind: str
    started_at_utc: str
    ended_at_utc: str
    raw_hours: float
    rounded_hours: float
    voided: bool
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict):
    id: str
    name: str
    vendor_type: str
    coi_expires_on: str
    daily_capacity: int
    holdback_pct: float
    coi_renewal_count: int
    blocked_assignment_count: int
    created_at: str
    updated_at: str
    version: int


class VendorAssignment(TypedDict):
    id: str
    engagement_id: str
    vendor_id: str
    signed_off_by_party_id: Optional[str]
    service_kind: str
    service_date: str
    status: str
    quoted_cents: int
    holdback_cents: int
    paid_cents: int
    holdback_released: bool
    performed_at_utc: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConsignmentLot(TypedDict):
    id: str
    engagement_id: str
    vendor_id: str
    status: str
    list_price_cents: int
    current_price_cents: int
    markdown_round: int
    listed_on: str
    sold_on: Optional[str]
    gross_sale_price_cents: Optional[int]
    commission_cents: int
    fees_cents: int
    net_proceeds_cents: int
    item_count: int
    credited: bool
    reversed: bool
    disposal_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    engagement_id: str
    status: str
    subtotal_cents: int
    credits_cents: int
    coordination_fee_cents: int
    total_cents: int
    payments_cents: int
    balance_due_cents: int
    recall_count: int
    dispute_count: int
    dispute_reason: Optional[str]
    issued_at_utc: Optional[str]
    finalized_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InvoiceLine(TypedDict):
    """A posted ledger line is immutable: id and created_at only."""

    id: str
    invoice_id: str
    source_consignment_lot_id: Optional[str]
    line_type: str
    amount_cents: int
    memo: str
    created_by_role: str
    created_at: str


class Milestone(TypedDict):
    id: str
    engagement_id: str
    completed_by_party_id: Optional[str]
    milestone_key: str
    sequence_index: int
    status: str
    overdue_status: str
    due_on: str
    completed_at_utc: Optional[str]
    reopen_count: int
    created_at: str
    updated_at: str
    version: int


class UnpackSession(TypedDict):
    id: str
    engagement_id: str
    priority: str
    status: str
    scheduled_start_utc: str
    items_unpacked_count: int
    reopen_count: int
    started_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PunchListItem(TypedDict):
    id: str
    engagement_id: str
    unpack_session_id: Optional[str]
    severity: str
    status: str
    description: str
    resolution_note: Optional[str]
    due_at_utc: str
    breached_sla: bool
    reopen_count: int
    created_at: str
    updated_at: str
    version: int


__all__ = [
    "UserRole",
    "EngagementStatus",
    "EngagementPhase",
    "BillingMode",
    "HomeTier",
    "PartyType",
    "AuthorityScope",
    "AuthorityStatus",
    "UnitType",
    "PlacementStatus",
    "RoomType",
    "ItemCategory",
    "AppraisalSource",
    "Disposition",
    "HandlingState",
    "HoldState",
    "FamilyHoldStatus",
    "HoldResolution",
    "SortPlanStatus",
    "MoveDayPlanStatus",
    "CrewRole",
    "CrewAssignmentStatus",
    "EntryKind",
    "VendorType",
    "ServiceKind",
    "VendorAssignmentStatus",
    "ConsignmentLotStatus",
    "InvoiceStatus",
    "LineType",
    "MilestoneKey",
    "MilestoneStatus",
    "OverdueStatus",
    "UnpackPriority",
    "UnpackSessionStatus",
    "PunchSeverity",
    "PunchStatus",
    "Client",
    "Engagement",
    "PortalParty",
    "AuthorityRecord",
    "DestinationResidence",
    "DestinationRoom",
    "InventoryItem",
    "FamilyHold",
    "SortPlan",
    "MoveDayPlan",
    "CrewMember",
    "CrewAssignment",
    "TimeEntry",
    "Vendor",
    "VendorAssignment",
    "ConsignmentLot",
    "Invoice",
    "InvoiceLine",
    "Milestone",
    "UnpackSession",
    "PunchListItem",
]
