"""Domain types: entity TypedDicts, status enums, role enum (PRD sections 2.1, 2.5, 3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    SITE_SUPERVISOR = "SiteSupervisor"
    HAULER_PARTNER = "HaulerPartner"
    RESIDENT = "Resident"
    VOLUNTEER = "Volunteer"
    ANONYMOUS = "Anonymous"


class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class ProgramPosture(str, Enum):
    NORMAL = "NORMAL"
    RESTRICTED = "RESTRICTED"


class SiteStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class ZoneStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BookingStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    SERVICED = "SERVICED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"
    REJECTED_CONTAMINATED = "REJECTED_CONTAMINATED"


class IntakeStatus(str, Enum):
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class TicketStatus(str, Enum):
    OPEN = "OPEN"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"
    APPEALED = "APPEALED"
    UPHELD_FINAL = "UPHELD_FINAL"
    OVERTURNED = "OVERTURNED"


class RunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ClaimStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class VolunteerStatus(str, Enum):
    APPLIED = "APPLIED"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"


class ShiftStatus(str, Enum):
    SIGNED_UP = "SIGNED_UP"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class SizeClass(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"
    MIXED = "MIXED"


class SourceType(str, Enum):
    RESIDENT_SELF_HAUL = "RESIDENT_SELF_HAUL"
    COMMERCIAL_LANDSCAPER = "COMMERCIAL_LANDSCAPER"
    CITY_CREW = "CITY_CREW"


class MaterialClass(str, Enum):
    MIXED_CONIFER = "MIXED_CONIFER"
    HARDWOOD = "HARDWOOD"
    MIXED_LOAD = "MIXED_LOAD"


class ShiftRole(str, Enum):
    GREETER = "GREETER"
    TRAFFIC_CONTROL = "TRAFFIC_CONTROL"
    LOADER = "LOADER"


class TicketCategory(str, Enum):
    DECORATIONS = "DECORATIONS"
    STAND_ATTACHED = "STAND_ATTACHED"
    FLOCKED_TREE = "FLOCKED_TREE"
    WREATH_WITH_WIRE = "WREATH_WITH_WIRE"
    OTHER = "OTHER"


class ClaimTier(str, Enum):
    PARTICIPANT = "PARTICIPANT"
    GENERAL = "GENERAL"


class NotificationKind(str, Enum):
    PROGRAM_PUBLISHED = "PROGRAM_PUBLISHED"
    ZONE_RESCHEDULED = "ZONE_RESCHEDULED"
    BOOKING_AUTO_CANCELLED = "BOOKING_AUTO_CANCELLED"
    CLAIM_PROMOTED = "CLAIM_PROMOTED"
    SITE_CLOSING = "SITE_CLOSING"
    MULCH_EVENT_OPENED = "MULCH_EVENT_OPENED"


class ReportGrade(str, Enum):
    NO_DATA = "NO_DATA"
    A = "A"
    B = "B"
    C = "C"


class Program(TypedDict, total=False):
    id: str
    name: str
    season_label: str
    window_start: str
    window_end: str
    target_diversion_rate: float
    status: str
    posture: str
    open_ticket_count: int
    mulch_produced_cy: float
    mulch_allocated_participant_cy: float
    mulch_allocated_general_cy: float
    participant_remaining_cy: float
    general_remaining_cy: float
    created_at: str
    updated_at: str
    version: int


class DropOffSite(TypedDict, total=False):
    id: str
    program_id: str
    name: str
    address: str
    capacity_cy: float
    open_date: str
    close_date: str
    volunteer_slots_per_role: int
    status: str
    stockpile_cy: float
    created_at: str
    updated_at: str
    version: int


class ServiceZone(TypedDict, total=False):
    id: str
    program_id: str
    zone_code: str
    collection_date: str
    daily_tree_capacity: int
    status: str
    reserved_trees: int
    remaining_capacity: int
    projected_tons_provisional: float
    collected_tons_actual: float
    created_at: str
    updated_at: str
    version: int


class Household(TypedDict, total=False):
    id: str
    program_id: str
    zone_id: str
    address: str
    contact_email: str
    strike_count: int
    curbside_eligible: bool
    created_at: str
    updated_at: str
    version: int


class CurbsideBooking(TypedDict, total=False):
    id: str
    household_id: str
    zone_id: str
    tree_count: int
    size_class: str
    prep_attestation: bool
    status: str
    service_date: str
    actual_tons: Optional[float]
    estimated_tons: float
    created_at: str
    updated_at: str
    version: int


class IntakeEvent(TypedDict, total=False):
    # Append-only record: carries only id + created_at (no updated_at/version).
    id: str
    site_id: str
    source_type: str
    tree_count: int
    size_class: str
    contaminated_cy: float
    gross_volume_cy: float
    net_volume_cy: float
    weighed_tons: Optional[float]
    estimated_tons: float
    report_tons: float
    recorded_at: str
    status: str
    void_reason: Optional[str]
    created_at: str


class ContaminationTicket(TypedDict, total=False):
    id: str
    program_id: str
    booking_id: Optional[str]
    site_id: Optional[str]
    category: str
    notes: Optional[str]
    reporter_user_id: str
    reporter_role: str
    status: str
    adjudicated_by: Optional[str]
    adjudicated_at: Optional[str]
    appeal_deadline: Optional[str]
    resolved_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChippingRun(TypedDict, total=False):
    id: str
    program_id: str
    site_id: str
    scheduled_start: str
    scheduled_end: str
    material_class: str
    status: str
    input_cy: Optional[float]
    measured_input_tons: Optional[float]
    contaminated_input_tons: Optional[float]
    theoretical_output_cy: Optional[float]
    measured_output_cy: Optional[float]
    variance_pct: Optional[float]
    yield_review_confirmed: bool
    created_at: str
    updated_at: str
    version: int


class MulchEvent(TypedDict, total=False):
    id: str
    program_id: str
    name: str
    claim_open_at: str
    claim_close_at: str
    pickup_start: str
    pickup_end: str
    per_household_cap_cy: float
    status: str
    created_at: str
    updated_at: str
    version: int


class MulchClaim(TypedDict, total=False):
    id: str
    event_id: str
    household_id: str
    requested_cy: float
    tier: str
    allocated_cy: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Volunteer(TypedDict, total=False):
    id: str
    program_id: str
    full_name: str
    email: str
    status: str
    no_show_count: int
    created_at: str
    updated_at: str
    version: int


class VolunteerShift(TypedDict, total=False):
    id: str
    volunteer_id: str
    site_id: str
    start_at: str
    end_at: str
    shift_role: str
    status: str
    created_at: str
    updated_at: str
    version: int


class NotificationLog(TypedDict, total=False):
    # Append-only record: carries only id + created_at (no updated_at/version).
    id: str
    program_id: str
    kind: str
    household_id: Optional[str]
    zone_id: Optional[str]
    message: str
    created_at: str


class DiversionReport(TypedDict, total=False):
    id: str
    program_id: str
    period_start: str
    period_end: str
    status: str
    collected_tons: float
    diverted_tons: float
    disposed_tons: float
    diversion_rate: float
    grade: str
    below_target: bool
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
