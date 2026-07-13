"""Domain types: entity TypedDicts, status enums, role enum.

All types are derived from the Car Shipping PRD. A LedgerEntry is an immutable
financial posting and carries only id + created_at (no updated_at, no version);
every other entity carries the full id / created_at / updated_at / version set.
"""
from enum import Enum
from typing import Optional, TypedDict


# ─── Enumerations ──────────────────────────────────────────────────────────

class UserRole(str, Enum):
    SHIPPER = "Shipper"
    BROKER = "Broker"
    CARRIER = "Carrier"
    ADMIN = "Admin"


class TransportType(str, Enum):
    OPEN = "OPEN"
    ENCLOSED = "ENCLOSED"


class DeliveryMode(str, Enum):
    DOOR_TO_DOOR = "DOOR_TO_DOOR"
    TERMINAL = "TERMINAL"


class ServiceLevel(str, Enum):
    STANDARD = "STANDARD"
    EXPEDITED = "EXPEDITED"


class EquipmentType(str, Enum):
    OPEN = "OPEN"
    ENCLOSED = "ENCLOSED"


class CarrierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ShipmentOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    LISTED = "LISTED"
    DISPATCHED = "DISPATCHED"
    PICKED_UP = "PICKED_UP"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class QuoteStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


class LoadListingStatus(str, Enum):
    OPEN = "OPEN"
    AWARDED = "AWARDED"
    WITHDRAWN = "WITHDRAWN"


class DispatchOfferStatus(str, Enum):
    PENDING = "PENDING"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class AssignmentStatus(str, Enum):
    DISPATCHED = "DISPATCHED"
    REVOKED = "REVOKED"
    COMPLETED = "COMPLETED"


class InspectionPhase(str, Enum):
    PICKUP = "PICKUP"
    DELIVERY = "DELIVERY"


class LedgerKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    COD_PAYMENT = "COD_PAYMENT"
    REFUND = "REFUND"
    CLAIM_PAYOUT = "CLAIM_PAYOUT"


class LedgerStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    RETURNED_FOR_INFO = "RETURNED_FOR_INFO"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"


# ─── Entity TypedDicts (common_fields: true) ───────────────────────────────

class Carrier(TypedDict, total=False):
    id: str
    legal_name: str
    mc_number: str
    cargo_insurance_limit_cents: int
    insurance_expiry_date: str
    equipment_type: str
    rating: float
    aggregate_exposure_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ShipmentOrder(TypedDict, total=False):
    id: str
    shipper_id: str
    origin_zip: str
    dest_zip: str
    route_miles: int
    transport_type: str
    delivery_mode: str
    service_level: str
    pickup_window_start: str
    pickup_window_end: str
    quoted_total_cents: Optional[int]
    settled_total_cents: Optional[int]
    deposit_cents: Optional[int]
    cod_balance_cents: Optional[int]
    terminal_id: Optional[str]
    terminal_slot_start: Optional[str]
    terminal_slot_end: Optional[str]
    amount_paid_cents: int
    outstanding_balance_cents: Optional[int]
    assigned_carrier_id: Optional[str]
    status: str
    has_open_claim: bool
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    order_id: str
    make: str
    model: str
    year: int
    is_inoperable: bool
    declared_value_cents: int
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict, total=False):
    id: str
    order_id: str
    base_cents: int
    transport_surcharge_cents: int
    inoperable_surcharge_cents: int
    multi_car_discount_cents: int
    total_cents: int
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LoadListing(TypedDict, total=False):
    id: str
    order_id: str
    offered_carrier_pay_cents: int
    expedited: bool
    best_offer_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DispatchOffer(TypedDict, total=False):
    id: str
    listing_id: str
    carrier_id: str
    ask_pay_cents: int
    pickup_eta: str
    round_no: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict, total=False):
    id: str
    order_id: str
    carrier_id: str
    offer_id: str
    carrier_pay_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    order_id: str
    phase: str
    damage_count: int
    observed_inoperable_count: int
    odometer: int
    signed_by_carrier_id: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    order_id: str
    carrier_id: str
    claimed_cents: int
    approved_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipper(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    created_at: str
    updated_at: str
    version: int


class Terminal(TypedDict, total=False):
    id: str
    name: str
    dock_zip: str
    dock_count: int
    buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


# ─── Append-only entity (common_fields: false) ─────────────────────────────
# A LedgerEntry is an immutable financial posting: only id + created_at.

class LedgerEntry(TypedDict, total=False):
    id: str
    order_id: str
    kind: str
    amount_cents: int
    status: str
    created_at: str
