"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PORT_AUTHORITY_ADMIN = "PortAuthorityAdmin"
    HARBORMASTER = "Harbormaster"
    TERMINAL_OPERATOR = "TerminalOperator"
    VESSEL_AGENT = "VesselAgent"
    CUSTOMS_OFFICER = "CustomsOfficer"
    BILLING_CLERK = "BillingClerk"


class TerminalPosture(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    CONSTRAINED = "CONSTRAINED"
    EMERGENCY = "EMERGENCY"


class BerthStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class PortCallStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DELAYED = "DELAYED"
    ARRIVED = "ARRIVED"
    TURNAROUND = "TURNAROUND"
    DEPARTED = "DEPARTED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class BerthAssignmentStatus(str, Enum):
    TENTATIVE = "TENTATIVE"
    CONFIRMED = "CONFIRMED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class ManifestDirection(str, Enum):
    EMBARK = "EMBARK"
    DEBARK = "DEBARK"


class CabinClass(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    CREW = "CREW"


class ManifestEntryStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    SCREENED = "SCREENED"
    EMBARKED = "EMBARKED"
    NO_SHOW = "NO_SHOW"
    ABOARD = "ABOARD"
    DISEMBARKED = "DISEMBARKED"
    HELD = "HELD"
    CLEARED = "CLEARED"
    CARRIED_AWAY = "CARRIED_AWAY"
    CANCELLED = "CANCELLED"


class BaggageItemStatus(str, Enum):
    CHECKED = "CHECKED"
    STAGED = "STAGED"
    LOADED = "LOADED"
    DELIVERED = "DELIVERED"
    MISTAGGED = "MISTAGGED"
    RECOVERED = "RECOVERED"
    OFFLOADED = "OFFLOADED"
    CANCELLED = "CANCELLED"


class ScreeningLaneStatus(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"


class CustomsCaseStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    HELD = "HELD"
    CLEARED = "CLEARED"


class ServiceOrderKind(str, Enum):
    PROVISIONING = "PROVISIONING"
    WASTE_OFFLOAD = "WASTE_OFFLOAD"


class ServiceOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InvoiceKind(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class VehicleClass(str, Enum):
    TAXI = "TAXI"
    SHUTTLE = "SHUTTLE"
    PRIVATE = "PRIVATE"


class TransportSlotStatus(str, Enum):
    QUEUED = "QUEUED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    EXPIRED = "EXPIRED"


class AdvisorySeverity(str, Enum):
    WATCH = "WATCH"
    WARNING = "WARNING"
    EMERGENCY = "EMERGENCY"


class WeatherAdvisoryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class Terminal(TypedDict, total=False):
    id: str
    name: str
    max_apron_slots: int
    taxi_dispatch_capacity_per_window: int
    occupied_berth_count: int
    active_berth_count: int
    free_berth_count: int
    posture: str
    ops_run_index: int
    created_at: str
    updated_at: str
    version: int


class Berth(TypedDict, total=False):
    id: str
    terminal_id: str
    berth_code: str
    length_ft: int
    max_draft_ft: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Vessel(TypedDict, total=False):
    id: str
    terminal_id: str
    name: str
    loa_ft: int
    draft_ft: float
    pax_capacity: int
    crew_count: int
    created_at: str
    updated_at: str
    version: int


class PortCall(TypedDict, total=False):
    id: str
    terminal_id: str
    vessel_id: str
    voyage_ref: str
    scheduled_eta: str
    scheduled_etd: str
    booked_embark_pax: int
    booked_debark_pax: int
    revised_eta: Optional[str]
    revised_etd: Optional[str]
    delay_reason: Optional[str]
    actual_eta: Optional[str]
    actual_etd: Optional[str]
    status: str
    passengers_aboard: int
    bags_aboard: int
    created_at: str
    updated_at: str
    version: int


class BerthAssignment(TypedDict, total=False):
    id: str
    port_call_id: str
    berth_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ManifestEntry(TypedDict, total=False):
    id: str
    port_call_id: str
    passenger_ref: str
    direction: str
    cabin_class: str
    status: str
    is_taxable: bool
    created_at: str
    updated_at: str
    version: int


class BaggageItem(TypedDict, total=False):
    id: str
    manifest_entry_id: str
    port_call_id: str
    tag_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ScreeningLane(TypedDict, total=False):
    id: str
    terminal_id: str
    lane_code: str
    officers_assigned: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomsCase(TypedDict, total=False):
    id: str
    port_call_id: str
    status: str
    hold_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceOrder(TypedDict, total=False):
    id: str
    port_call_id: str
    kind: str
    units: int
    window_start: str
    window_end: str
    requested_by_user_id: str
    approved_by_user_id: Optional[str]
    surcharge_applied: bool
    actual_units: Optional[int]
    reject_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    port_call_id: str
    kind: str
    status: str
    dockage_fee_cents: int
    head_tax_cents: int
    service_fee_cents: int
    adjustments_total_cents: int
    gross_cents: int
    total_cents: int
    payment_cents: Optional[int]
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransportSlot(TypedDict, total=False):
    id: str
    terminal_id: str
    port_call_id: str
    vehicle_class: str
    party_size: int
    queue_seq: int
    requeue_count: int
    dispatch_window_start: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WeatherAdvisory(TypedDict, total=False):
    id: str
    terminal_id: str
    severity: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int
