"""Domain types: entity TypedDicts, status enums, role enum.

Every persisted resource carries the common quartet id/created_at/updated_at/version
(PRD §2.4), so all TypedDicts below list all four.
"""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PUBLIC_WORKS_ADMIN = "PublicWorksAdmin"
    ROUTE_DISPATCHER = "RouteDispatcher"
    SIGNAGE_INSPECTOR = "SignageInspector"
    ENFORCEMENT_OFFICER = "EnforcementOfficer"
    RESIDENT = "Resident"


class RouteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class SignStatus(str, Enum):
    UNPOSTED = "UNPOSTED"
    POSTED = "POSTED"
    VERIFIED = "VERIFIED"


class EquipmentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    IN_SERVICE = "IN_SERVICE"


class ShiftStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED = "CLOSED"


class SweepEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SWEPT = "SWEPT"
    MISSED = "MISSED"
    SUSPENDED = "SUSPENDED"
    VOIDED = "VOIDED"


class SuspensionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


class CitationStatus(str, Enum):
    ISSUED = "ISSUED"
    CONTESTED = "CONTESTED"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"
    PAID = "PAID"


class ComplaintStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"
    REJECTED = "REJECTED"


class Route(TypedDict):
    id: str
    name: str
    zone_code: str
    sweep_weekday: str
    sweep_ordinal: Optional[int]
    status: str
    completed_block_count: int
    created_at: str
    updated_at: str
    version: int


class Block(TypedDict):
    id: str
    route_id: str
    block_label: str
    side: str
    restriction_start_local: str
    restriction_end_local: str
    linear_feet: int
    enforcement_enabled: bool
    sign_status: str
    sign_posted_at: Optional[str]
    sign_expires_at: Optional[str]
    sign_enforceable: bool
    pending_citation_cents: int
    created_at: str
    updated_at: str
    version: int


class Equipment(TypedDict):
    id: str
    unit_number: str
    type: str
    hopper_capacity_lbs: int
    odometer_miles: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Shift(TypedDict):
    id: str
    equipment_id: str
    operator_name: str
    shift_date: str
    start_utc: str
    end_utc: str
    status: str
    total_debris_lbs: int
    gross_tonnage: float
    net_tonnage: float
    created_at: str
    updated_at: str
    version: int


class SweepEvent(TypedDict):
    id: str
    block_id: str
    shift_id: Optional[str]
    original_event_id: Optional[str]
    scheduled_date: str
    window_start_utc: str
    window_end_utc: str
    status: str
    debris_lbs: Optional[int]
    completed_at: Optional[str]
    is_makeup: bool
    notified_resident_count: int
    created_at: str
    updated_at: str
    version: int


class Suspension(TypedDict):
    id: str
    reason: str
    scope: str
    route_id: Optional[str]
    start_date: str
    end_date: str
    status: str
    suspended_event_count: int
    created_at: str
    updated_at: str
    version: int


class Citation(TypedDict):
    id: str
    block_id: str
    sweep_event_id: Optional[str]
    plate: str
    scanned_at_utc: str
    issued_at: str
    status: str
    amount_due_cents: int
    paid_amount_cents: Optional[int]
    issuing_officer_id: str
    adjudicator_id: Optional[str]
    prior_upheld_count: int
    days_late: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Resident(TypedDict):
    id: str
    email: str
    full_name: str
    home_block_id: str
    notify_opt_in: bool
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    resident_id: str
    block_id: str
    category: str
    linked_sweep_event_id: Optional[str]
    status: str
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int
