"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---- Role enum ----
class UserRole(str, Enum):
    EXCAVATOR = "Excavator"
    FACILITY_OWNER = "FacilityOwner"
    LOCATE_TECH = "LocateTech"
    CALL_CENTER = "CallCenter"
    ADMIN = "Admin"


# ---- Status enums ----
class ExcavatorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class MemberUtilityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class FacilityType(str, Enum):
    GAS = "GAS"
    ELECTRIC = "ELECTRIC"
    WATER = "WATER"
    SEWER = "SEWER"
    TELECOM = "TELECOM"
    OIL = "OIL"


class LocateTechStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OFF_DUTY = "OFF_DUTY"


class TicketType(str, Enum):
    NORMAL = "NORMAL"
    EMERGENCY = "EMERGENCY"


class ResponsePosture(str, Enum):
    INTAKE = "INTAKE"
    AWAITING_RESPONSES = "AWAITING_RESPONSES"
    ALL_CLEAR = "ALL_CLEAR"
    CONFLICT = "CONFLICT"
    SLA_BREACHED = "SLA_BREACHED"


class TicketStatus(str, Enum):
    INTAKE = "INTAKE"
    SUBMITTED = "SUBMITTED"
    RESPONSES_COMPLETE = "RESPONSES_COMPLETE"
    MARKED = "MARKED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class NotificationStatus(str, Enum):
    PENDING = "PENDING"
    CLEAR = "CLEAR"
    CONFLICT = "CONFLICT"
    MARKED_BY_OWNER = "MARKED_BY_OWNER"


class PositiveResponseOutcome(str, Enum):
    CLEAR = "CLEAR"
    CONFLICT = "CONFLICT"
    MARKED_BY_OWNER = "MARKED_BY_OWNER"


class AssignmentStatus(str, Enum):
    DISPATCHED = "DISPATCHED"
    EN_ROUTE = "EN_ROUTE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    BREACHED = "BREACHED"


class MarkOutStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class MeetRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"


class DamageReportStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    SETTLED = "SETTLED"
    DISPUTED = "DISPUTED"


# ---- Entity TypedDicts ----
# All these entities carry the common mutable fields (id/created_at/updated_at/version)
# except PositiveResponse, which is append-only (id + created_at only).

class Polygon(TypedDict):
    min_x: int
    min_y: int
    max_x: int
    max_y: int


class Excavator(TypedDict):
    id: str
    company_name: str
    contact_email: str
    state_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MemberUtility(TypedDict):
    id: str
    name: str
    facility_type: str
    service_polygon: Polygon
    emergency_contact_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LocateTech(TypedDict):
    id: str
    full_name: str
    member_utility_id: str
    certified_facility_types: List[str]
    active_assignment_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LocateTicket(TypedDict):
    id: str
    excavator_id: str
    ticket_type: str
    dig_polygon: Polygon
    work_description: str
    is_white_lined: bool
    sla_due_at: Optional[str]
    dig_window_opens_at: Optional[str]
    dig_window_expires_at: Optional[str]
    notified_member_count: int
    open_response_count: int
    response_posture: str
    markout_completed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class UtilityNotification(TypedDict):
    id: str
    ticket_id: str
    member_utility_id: str
    response_status: str
    due_at: Optional[str]
    is_high_priority: bool
    created_at: str
    updated_at: str
    version: int


# Append-only, immutable record — carries ONLY id + created_at (no updated_at/version).
class PositiveResponse(TypedDict):
    id: str
    notification_id: str
    outcome: str
    comment: Optional[str]
    responded_at: str
    was_late: bool
    created_at: str


class LocateAssignment(TypedDict):
    id: str
    ticket_id: str
    notification_id: str
    locate_tech_id: str
    dispatched_at: Optional[str]
    sla_deadline_at: Optional[str]
    completed_at: Optional[str]
    sla_breached: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class MarkOut(TypedDict):
    id: str
    assignment_id: str
    ticket_id: str
    marks_count: int
    is_refresh: bool
    supersedes_markout_id: Optional[str]
    valid_until: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MeetRequest(TypedDict):
    id: str
    ticket_id: str
    member_utility_id: str
    proposed_start_min: int
    proposed_end_min: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DamageReport(TypedDict):
    id: str
    ticket_id: str
    member_utility_id: str
    markout_id: Optional[str]
    repair_cost_cents: int
    dug_within_marks: bool
    excavator_liability_cents: Optional[int]
    member_liability_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
