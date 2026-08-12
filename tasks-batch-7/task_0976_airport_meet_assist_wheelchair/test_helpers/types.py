"""Domain types: entity TypedDicts, status enums, role enum.

Derived from PRD §3 entity descriptions. TrackingEvent is append-only
(common_fields=false) and therefore carries only id + created_at; every
other entity carries id + created_at + updated_at + version.
"""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Enums (PRD §2.5, §3.1, §3.2, §3.4, §3.6, §3.8, §3.9)
# ---------------------------------------------------------------------------

class AirportPosture(str, Enum):
    NORMAL = "NORMAL"
    DEGRADED = "DEGRADED"
    LOCKDOWN = "LOCKDOWN"


class TerminalStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class SegmentDirection(str, Enum):
    ARRIVAL = "ARRIVAL"
    DEPARTURE = "DEPARTURE"


class SegmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LANDED = "LANDED"
    DEPARTED = "DEPARTED"
    CANCELLED = "CANCELLED"


class MobilityCode(str, Enum):
    WCHR = "WCHR"
    WCHS = "WCHS"
    WCHC = "WCHC"


class PassengerClass(str, Enum):
    ADULT = "ADULT"
    SENIOR = "SENIOR"
    UMNR = "UMNR"


class AgentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    OFF_SHIFT = "OFF_SHIFT"


class ChairClass(str, Enum):
    MANUAL = "MANUAL"
    POWER = "POWER"
    BARIATRIC = "BARIATRIC"


class WheelchairStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    CHECKED_OUT = "CHECKED_OUT"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class BillTo(str, Enum):
    AIRLINE = "AIRLINE"
    PRIVATE = "PRIVATE"


class ServiceTier(str, Enum):
    STANDARD = "STANDARD"
    PRIORITY = "PRIORITY"
    CONCIERGE = "CONCIERGE"


class RequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ASSIGNED = "ASSIGNED"
    IN_SERVICE = "IN_SERVICE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    WRITTEN_OFF = "WRITTEN_OFF"


class LegKind(str, Enum):
    MEET_ARRIVAL = "MEET_ARRIVAL"
    DEPARTURE_ESCORT = "DEPARTURE_ESCORT"
    CONNECTION_TRANSFER = "CONNECTION_TRANSFER"


class ServiceLegStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    AT_PICKUP = "AT_PICKUP"
    IN_TRANSIT = "IN_TRANSIT"
    AT_GATE = "AT_GATE"
    HANDED_OFF = "HANDED_OFF"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class AssignmentStatus(str, Enum):
    DISPATCHED = "DISPATCHED"
    AT_PICKUP = "AT_PICKUP"
    IN_TRANSIT = "IN_TRANSIT"
    AT_GATE = "AT_GATE"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class IncidentKind(str, Enum):
    FALL = "FALL"
    MISSED_CONNECTION = "MISSED_CONNECTION"
    MEDICAL = "MEDICAL"
    PROPERTY_DAMAGE = "PROPERTY_DAMAGE"
    SECURITY = "SECURITY"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    ACKED = "ACKED"
    RESOLVED = "RESOLVED"


class InvoiceKind(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    ADJUSTMENT = "ADJUSTMENT"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    WRITTEN_OFF = "WRITTEN_OFF"
    VOID = "VOID"


class TrackingEventKind(str, Enum):
    LOCATION_PING = "LOCATION_PING"
    PICKUP_CONFIRM = "PICKUP_CONFIRM"
    GATE_ARRIVAL = "GATE_ARRIVAL"
    HANDOFF_START = "HANDOFF_START"
    HANDOFF_COMPLETE = "HANDOFF_COMPLETE"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    REQUESTER = "Requester"
    DISPATCHER = "Dispatcher"
    AGENT = "Agent"
    CONFIRMER = "Confirmer"
    OPS_MANAGER = "OpsManager"
    BILLING_CLERK = "BillingClerk"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class Airport(TypedDict, total=False):
    id: str
    iata_code: str
    tz_offset_minutes: int
    meet_buffer_minutes: int
    posture: str
    ops_epoch: int
    created_at: str
    updated_at: str
    version: int


class Terminal(TypedDict, total=False):
    id: str
    airport_id: str
    code: str
    requires_secure_escort: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class FlightSegment(TypedDict, total=False):
    id: str
    airport_id: str
    flight_no: str
    direction: str
    terminal_id: str
    scheduled_utc: str
    actual_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Passenger(TypedDict, total=False):
    id: str
    full_name: str
    dob: str
    mobility_code: str
    passenger_class: str
    airline_pnr: Optional[str]
    private_card_token: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Agent(TypedDict, total=False):
    id: str
    airport_id: str
    display_name: str
    tsa_cleared_until: str
    ummr_certified: bool
    senior_trained: bool
    wc_certified: bool
    shift_start_utc: str
    shift_end_utc: str
    status: str
    active_assignment_count: int
    cumulative_delay_minutes: int
    created_at: str
    updated_at: str
    version: int


class WheelchairAsset(TypedDict, total=False):
    id: str
    airport_id: str
    asset_tag: str
    chair_class: str
    is_wchc_rated: bool
    status: str
    last_maintenance_utc: Optional[str]
    usage_count: int
    created_at: str
    updated_at: str
    version: int


class AssistRequest(TypedDict, total=False):
    id: str
    passenger_id: str
    bill_to: str
    service_tier: str
    request_status: str
    billing_status: str
    provisional_charge_cents: Optional[int]
    final_charge_cents: Optional[int]
    companion_count: int
    umnr_handoff_required: bool
    sofia_signoff_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceLeg(TypedDict, total=False):
    id: str
    assist_request_id: str
    segment_id: str
    leg_kind: str
    onward_leg_id: Optional[str]
    pickup_zone: str
    status: str
    scheduled_pickup_utc: str
    actual_pickup_utc: Optional[str]
    completed_utc: Optional[str]
    requires_wheelchair: bool
    requires_tsa_escort: bool
    requires_ummr_agent: bool
    requires_senior_agent: bool
    requires_wchc_chair: bool
    provisional_leg_cents: Optional[int]
    final_leg_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict, total=False):
    id: str
    assist_request_id: str
    service_leg_id: str
    agent_id: str
    wheelchair_asset_id: Optional[str]
    status: str
    assigned_by_user_id: str
    completed_by_user_id: Optional[str]
    umnr_second_signoff_user_id: Optional[str]
    scheduled_completion_utc: str
    tracking_token: str
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict, total=False):
    id: str
    assist_request_id: str
    assignment_id: str
    kind: str
    severity: str
    description: str
    status: str
    opened_at_utc: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    assist_request_id: str
    invoice_kind: str
    amount_cents: int
    status: str
    bill_to: str
    supersedes_invoice_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# TrackingEvent is append-only (common_fields=false). It carries id and
# created_at only — both updated_at and version are absent.
class TrackingEvent(TypedDict, total=False):
    id: str
    assignment_id: str
    event_kind: str
    lat: Optional[float]
    lon: Optional[float]
    occurred_at_utc: str
    created_at: str
