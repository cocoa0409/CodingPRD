"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this API carry the common resource properties (id, created_at,
updated_at, version) described in PRD section 2.5.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class OrgType(str, Enum):
    INTERNAL_DEPARTMENT = "INTERNAL_DEPARTMENT"
    STUDENT_GROUP = "STUDENT_GROUP"
    EXTERNAL = "EXTERNAL"


class OrgStanding(str, Enum):
    GOOD = "GOOD"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class RoomStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class RoomFeature(str, Enum):
    PROJECTOR = "PROJECTOR"
    VIDEO_CONF = "VIDEO_CONF"
    SOUND_SYSTEM = "SOUND_SYSTEM"
    STAGE = "STAGE"
    PIANO = "PIANO"
    LAB_BENCHES = "LAB_BENCHES"
    KITCHEN_ACCESS = "KITCHEN_ACCESS"
    ADA_LIFT = "ADA_LIFT"


class TermStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULING = "SCHEDULING"
    GENERAL = "GENERAL"
    CLOSED = "CLOSED"


class AcademicBlockStatus(str, Enum):
    UNPLACED = "UNPLACED"
    PLACED = "PLACED"


class SchedulingRunStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class EventStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    CONFIRMED = "CONFIRMED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    BUMPED = "BUMPED"


class CancelReason(str, Enum):
    CLIENT = "CLIENT"
    ADMIN = "ADMIN"
    BUMPED = "BUMPED"
    ORG_SUSPENDED = "ORG_SUSPENDED"


class ServiceCategory(str, Enum):
    AV = "AV"
    CATERING = "CATERING"
    CUSTODIAL = "CUSTODIAL"
    SECURITY = "SECURITY"


class ServiceOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    QUOTED = "QUOTED"
    NEEDS_REVISION = "NEEDS_REVISION"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    FULFILLED = "FULFILLED"
    INVOICED = "INVOICED"
    CANCELLED = "CANCELLED"


class InvoiceStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOIDED = "VOIDED"
    REFUNDED = "REFUNDED"


class GrantType(str, Enum):
    PHYSICAL_KEY = "PHYSICAL_KEY"
    CARD_ACCESS = "CARD_ACCESS"


class AccessGrantStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ISSUED = "ISSUED"
    OVERDUE = "OVERDUE"
    RETURNED = "RETURNED"
    LOST = "LOST"
    REVOKED = "REVOKED"


class UserRole(str, Enum):
    ORG_REQUESTER = "OrgRequester"
    SCHEDULER = "Scheduler"
    SERVICE_COORDINATOR = "ServiceCoordinator"
    FACILITIES_MANAGER = "FacilitiesManager"
    FINANCE_ADMIN = "FinanceAdmin"


class Organization(TypedDict, total=False):
    id: str
    name: str
    org_type: str
    contact_email: str
    insurance_certificate_expiry: Optional[str]
    insurance_coverage_cents: Optional[int]
    no_show_count: int
    standing: str
    deposit_held_cents: int
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict, total=False):
    id: str
    name: str
    building_code: str
    capacity: int
    features: List[str]
    turnaround_buffer_minutes: int
    internal_hourly_rate_cents: int
    student_hourly_rate_cents: int
    external_hourly_rate_cents: int
    peak_multiplier_bps: int
    status: str
    outage_start_at: Optional[str]
    outage_end_at: Optional[str]
    outage_windows: List[dict]
    key_count: int
    keys_issued: int
    keys_lost_total: int
    created_at: str
    updated_at: str
    version: int


class TermWindow(TypedDict, total=False):
    id: str
    name: str
    term_start_date: str
    term_end_date: str
    priority_open_at: str
    general_open_at: str
    status: str
    current_draft_run_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AcademicBlock(TypedDict, total=False):
    id: str
    term_id: str
    course_code: str
    instructor_name: str
    enrollment: int
    required_features: List[str]
    days_of_week: List[str]
    start_time: str
    end_time: str
    priority_score: int
    status: str
    assigned_room_id: Optional[str]
    scheduling_run_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SchedulingRun(TypedDict, total=False):
    id: str
    term_id: str
    status: str
    placed_count: int
    bumped_event_ids: List[str]
    unplaced_block_ids: List[str]
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EventReservation(TypedDict, total=False):
    id: str
    requester_org_id: str
    room_id: Optional[str]
    title: str
    expected_attendance: int
    required_features: List[str]
    start_at: str
    end_at: str
    setup_minutes: int
    teardown_minutes: int
    precedence_tier: int
    status: str
    decision_deadline: str
    confirm_deadline: Optional[str]
    checked_in_at: Optional[str]
    pinned_hourly_rate_cents: Optional[int]
    pinned_peak_multiplier_bps: Optional[int]
    cancellation_fee_cents: Optional[int]
    cancel_reason: Optional[str]
    approved_by_user_id: Optional[str]
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceOrder(TypedDict, total=False):
    id: str
    event_id: str
    category: str
    quantity: int
    unit_cost_cents: Optional[int]
    quoted_total_cents: Optional[int]
    service_start_at: str
    service_end_at: str
    crew_id: Optional[str]
    status: str
    fee_waived: bool
    revision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceCrew(TypedDict, total=False):
    id: str
    name: str
    category: str
    concurrent_capacity: int
    shift_start: str
    shift_end: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    event_id: str
    org_id: str
    status: str
    room_charge_cents: int
    service_charge_cents: int
    insurance_surcharge_cents: int
    cancellation_fee_cents: int
    no_show_fee_cents: int
    deposit_charge_cents: int
    total_cents: int
    paid_cents: int
    waived_cents: int
    refunded_cents: int
    created_at: str
    updated_at: str
    version: int


class AccessGrant(TypedDict, total=False):
    id: str
    event_id: str
    room_id: str
    grant_type: str
    status: str
    key_slot: Optional[int]
    deposit_cents: int
    deposit_forfeit_cents: int
    return_deadline: str
    returned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
