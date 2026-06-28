"""Domain types: entity TypedDicts, status enums, role enum for the Mobile Phlebotomy API."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Roles (PRD §2.1) ---
class UserRole(str, Enum):
    ORDERING_PROVIDER = "OrderingProvider"
    DISPATCHER = "Dispatcher"
    PHLEBOTOMIST = "Phlebotomist"
    LAB_OPS = "LabOps"
    BILLING_AGENT = "BillingAgent"


# --- Status enums ---
class TestPanelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class LabPartnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PhlebotomistStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    SUSPENDED = "SUSPENDED"


class RouteDayStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class LabOrderStatus(str, Enum):
    ORDERED = "ORDERED"
    SCHEDULED = "SCHEDULED"
    DRAW_COMPLETED = "DRAW_COMPLETED"
    REDRAW_REQUIRED = "REDRAW_REQUIRED"
    RESULTED = "RESULTED"
    CANCELLED = "CANCELLED"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    ARRIVED = "ARRIVED"
    DRAW_COMPLETED = "DRAW_COMPLETED"
    CANCELLED = "CANCELLED"


class DrawKitStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    CONSUMED = "CONSUMED"


class SpecimenStatus(str, Enum):
    COLLECTED = "COLLECTED"
    MANIFESTED = "MANIFESTED"
    ACCESSIONED = "ACCESSIONED"
    QNS_REJECTED = "QNS_REJECTED"


class CustodyEventType(str, Enum):
    COLLECTED = "COLLECTED"
    MANIFESTED = "MANIFESTED"
    ACCESSIONED = "ACCESSIONED"
    REJECTED_QNS = "REJECTED_QNS"


class CourierManifestStatus(str, Enum):
    BUILDING = "BUILDING"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"


class LabResultStatus(str, Enum):
    PENDING_RELEASE = "PENDING_RELEASE"
    RELEASED = "RELEASED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    VOID = "VOID"


class BillingMode(str, Enum):
    INSURANCE = "INSURANCE"
    SELF_PAY = "SELF_PAY"


class OrderPriority(str, Enum):
    ROUTINE = "ROUTINE"
    STAT = "STAT"


# --- Entity TypedDicts ---
# Mutable entities carry id + created_at + updated_at + version.

class TestPanel(TypedDict):
    id: str
    panel_code: str
    name: str
    required_tube_count: int
    base_lab_fee_cents: int
    fasting_required: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class LabPartner(TypedDict):
    id: str
    name: str
    courier_sla_hours: int
    accepted_panel_codes: List[str]
    stat_surcharge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Phlebotomist(TypedDict):
    id: str
    full_name: str
    territory_code: str
    certification_active: bool
    redraw_strike_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RouteDay(TypedDict):
    id: str
    phlebotomist_id: str
    territory_code: str
    service_date: str
    shift_start_utc: str
    shift_end_utc: str
    stop_capacity: int
    booked_stop_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LabOrder(TypedDict):
    id: str
    ordering_provider_id: str
    patient_full_name: str
    patient_territory_code: str
    panel_code: str
    lab_partner_id: str
    priority: str
    billing_mode: str
    insurance_member_id: Optional[str]
    appointment_id: Optional[str]
    specimens_required_count: int
    specimens_accessioned_count: int
    redraw_count: int
    total_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    lab_order_id: str
    route_day_id: str
    phlebotomist_id: str
    window_start_utc: str
    window_end_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DrawKit(TypedDict):
    id: str
    appointment_id: str
    kit_lot_number: str
    tube_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Specimen(TypedDict):
    id: str
    lab_order_id: str
    appointment_id: str
    tube_label: str
    collected_at_utc: str
    courier_manifest_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only, immutable audit record (PRD §2.4 / §3.7): id + created_at ONLY.
class ChainOfCustodyEvent(TypedDict):
    id: str
    specimen_id: str
    prior_event_id: Optional[str]
    event_type: str
    actor_role: str
    actor_user_id: str
    sequence_index: int
    created_at: str


class CourierManifest(TypedDict):
    id: str
    lab_partner_id: str
    territory_code: str
    picked_up_at_utc: Optional[str]
    accession_due_utc: Optional[str]
    specimen_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LabResult(TypedDict):
    id: str
    lab_order_id: str
    lab_partner_id: str
    result_value: str
    released_to_provider: bool
    released_to_portal: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    lab_order_id: str
    billing_mode: str
    lab_fee_cents: int
    convenience_fee_cents: int
    redraw_waiver_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
