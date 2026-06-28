"""Domain types: entity TypedDicts, status enums, role enum.

All terminology mirrors the Boat Dry-Stack Marina PRD. Every persisted resource
carries id/created_at/updated_at/version (common resource properties, PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    DOCK_MASTER = "DockMaster"
    BOAT_OWNER = "BoatOwner"
    BILLING_CLERK = "BillingClerk"


# --------------------------------------------------------------------------- #
# Status enums
# --------------------------------------------------------------------------- #
class ForkliftStatus(str, Enum):
    AVAILABLE = "AVAILABLE"


class RackStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"


class VesselLocationStatus(str, Enum):
    OFF_SITE = "OFF_SITE"
    RACKED = "RACKED"
    IN_WATER = "IN_WATER"


class VesselBillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    ACTIVE_STORAGE = "ACTIVE_STORAGE"
    WINTER_HOLD = "WINTER_HOLD"
    DELINQUENT = "DELINQUENT"
    CLOSED = "CLOSED"


class InsurancePolicyStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class StorageAgreementStatus(str, Enum):
    PENDING_COI = "PENDING_COI"
    ACTIVE = "ACTIVE"
    WINTERIZED = "WINTERIZED"
    TERMINATED = "TERMINATED"


class WaitlistEntryStatus(str, Enum):
    WAITING = "WAITING"
    OFFERED = "OFFERED"
    PLACED = "PLACED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class LaunchRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    SPLASHED = "SPLASHED"
    RACKED = "RACKED"
    CANCELLED = "CANCELLED"


class ForkliftSlotStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"


class ServiceOrderStatus(str, Enum):
    ORDERED = "ORDERED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class ServiceKind(str, Enum):
    FUEL = "FUEL"
    VALET_SPLASH = "VALET_SPLASH"
    WINTERIZATION = "WINTERIZATION"
    HAUL_OUT = "HAUL_OUT"


class SizeClass(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class StorageInvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class InvoiceSourceKind(str, Enum):
    STORAGE_AGREEMENT = "STORAGE_AGREEMENT"
    LAUNCH_REQUEST = "LAUNCH_REQUEST"
    SERVICE_ORDER = "SERVICE_ORDER"


class InvoiceVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


# --------------------------------------------------------------------------- #
# Entity TypedDicts (all common_fields: true -> id/created_at/updated_at/version)
# --------------------------------------------------------------------------- #
class Marina(TypedDict):
    id: str
    name: str
    timezone: str
    forklift_service_minutes: int
    forklift_buffer_minutes: int
    total_rack_count: int
    created_at: str
    updated_at: str
    version: int


class Forklift(TypedDict):
    id: str
    marina_id: str
    label: str
    max_lift_weight_lbs: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Rack(TypedDict):
    id: str
    marina_id: str
    bay_label: str
    size_class: str
    max_loa_ft: float
    max_beam_ft: float
    max_weight_lbs: int
    status: str
    current_agreement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Vessel(TypedDict):
    id: str
    marina_id: str
    owner_id: str
    name: str
    loa_ft: float
    beam_ft: float
    dry_weight_lbs: int
    location_status: str
    billing_status: str
    active_policy_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BoatOwnerAccount(TypedDict):
    id: str
    marina_id: str
    full_name: str
    email: str
    account_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict):
    id: str
    vessel_id: str
    carrier_name: str
    liability_limit_cents: int
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class StorageAgreement(TypedDict):
    id: str
    vessel_id: str
    rack_id: str
    tier_size_class: Optional[str]
    monthly_base_cents: int
    oversize_surcharge_applied: bool
    activated_at: Optional[str]
    terminated_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict):
    id: str
    vessel_id: str
    requested_size_class: str
    deposit_paid: bool
    joined_at: str
    priority_score: int
    status: str
    offered_rack_id: Optional[str]
    offer_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LaunchRequest(TypedDict):
    id: str
    vessel_id: str
    forklift_slot_id: Optional[str]
    requested_window_start: str
    with_valet_splash: bool
    launch_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ForkliftSlot(TypedDict):
    id: str
    forklift_id: str
    launch_request_id: Optional[str]
    window_start: str
    window_end: str
    busy_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceOrder(TypedDict):
    id: str
    vessel_id: str
    service_kind: str
    fuel_gallons: float
    fuel_price_cents_per_gal: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StorageInvoice(TypedDict):
    id: str
    owner_id: str
    source_kind: str
    source_id: str
    variant: str
    period_start: Optional[str]
    period_end: Optional[str]
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
