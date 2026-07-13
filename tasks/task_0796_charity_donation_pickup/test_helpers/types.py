"""Domain types: entity TypedDicts, status enums, and the role enum.

Derived from the Charity Donation-Pickup PRD. Every entity in this system
carries the full audit set (id, created_at, updated_at, version).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status / enum values ─────────────────────────────────────────────

class CharityPartnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class VehicleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class RouteStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class DonorStatus(str, Enum):
    ACTIVE = "ACTIVE"


class RecurringPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class PickupRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class RouteStopStatus(str, Enum):
    RESERVED = "RESERVED"
    SERVICED = "SERVICED"
    CANCELLED = "CANCELLED"


class DonationReceiptStatus(str, Enum):
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class HaulInvoiceStatus(str, Enum):
    INVOICED = "INVOICED"
    PAID = "PAID"


class Disposition(str, Enum):
    DONATION = "DONATION"
    HAUL = "HAUL"


class PickupMode(str, Enum):
    ATTENDED = "ATTENDED"
    UNATTENDED = "UNATTENDED"


class ItemCategory(str, Enum):
    FURNITURE = "FURNITURE"
    CLOTHING = "CLOTHING"
    ELECTRONICS = "ELECTRONICS"
    APPLIANCE = "APPLIANCE"
    HOUSEHOLD = "HOUSEHOLD"


class ItemCondition(str, Enum):
    NEW = "NEW"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"


class DiversionStream(str, Enum):
    RECYCLE = "RECYCLE"
    REUSE = "REUSE"
    LANDFILL = "LANDFILL"


class Frequency(str, Enum):
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"
    MONTHLY = "MONTHLY"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    DONOR = "Donor"
    DISPATCHER = "Dispatcher"
    DRIVER = "Driver"
    PARTNER_ADMIN = "PartnerAdmin"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Entity TypedDicts (all carry the full audit set) ─────────────────

class CharityPartner(TypedDict):
    id: str
    name: str
    region_code: str
    tax_id: str
    accepted_categories: List[str]
    status: str
    ytd_donation_value_cents: int
    diverted_weight_lbs: int
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    label: str
    capacity_cf: int
    home_depot_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict):
    id: str
    vehicle_id: str
    partner_id: str
    service_date: str
    window_start: str
    window_end: str
    status: str
    reserved_volume_cf: int
    total_stop_count: int
    serviced_stop_count: int
    created_at: str
    updated_at: str
    version: int


class Donor(TypedDict):
    id: str
    email: str
    full_name: str
    address: str
    region_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RecurringPlan(TypedDict):
    id: str
    donor_id: str
    partner_id: str
    pickup_mode: str
    address: str
    default_disposition: str
    frequency: str
    next_pickup_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PickupRequest(TypedDict):
    id: str
    donor_id: str
    partner_id: str
    recurring_plan_id: Optional[str]
    pickup_mode: str
    disposition: str
    address: str
    porch_photo_url: Optional[str]
    safety_attestation: bool
    declared_volume_cf: int
    measured_volume_cf: Optional[int]
    is_free_donation: bool
    estimated_haul_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DonationItem(TypedDict):
    id: str
    request_id: str
    category: str
    volume_cf: int
    weight_lbs: int
    declared_value_cents: int
    declared_condition: str
    appraised_value_cents: Optional[int]
    appraised_condition: Optional[str]
    stream: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict):
    id: str
    route_id: str
    request_id: str
    sequence: int
    slot_start: str
    slot_end: str
    reserved_volume_cf: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DonationReceipt(TypedDict):
    id: str
    request_id: str
    partner_id: str
    receipt_number: str
    provisional_value_cents: int
    final_value_cents: int
    issued_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class HaulInvoice(TypedDict):
    id: str
    request_id: str
    estimate_cents: int
    final_cents: int
    diversion_credit_cents: int
    amount_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
