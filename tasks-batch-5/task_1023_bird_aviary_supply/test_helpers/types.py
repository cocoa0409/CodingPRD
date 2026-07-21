"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Bird & Aviary Supply PRD entity model and lifecycles.
Every persisted resource in this domain is mutable and therefore carries the
common audit set (id, created_at, updated_at, version) per PRD Section 2.4.
"""
from enum import Enum
from typing import TypedDict, List, Optional


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    AVIARY_STAFF = "AviaryStaff"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    STORE_MANAGER = "StoreManager"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ClubTier(str, Enum):
    NONE = "NONE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class SpeciesStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"


class CitesAppendix(str, Enum):
    I = "I"
    II = "II"
    III = "III"
    NONE = "NONE"


class CitesPermitStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class BirdStatus(str, Enum):
    INTAKE = "INTAKE"
    IN_QUARANTINE = "IN_QUARANTINE"
    CLEARED = "CLEARED"
    LISTED = "LISTED"
    SOLD = "SOLD"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class QuarantineRecordStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_TEST = "UNDER_TEST"
    CLEARED = "CLEARED"
    FAILED = "FAILED"


class CageClass(str, Enum):
    HOUSING = "HOUSING"
    BOARDING = "BOARDING"


class CageStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class BoardingReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    CANCELLED = "CANCELLED"


class GroomingStationStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ServiceType(str, Enum):
    WING_TRIM = "WING_TRIM"
    NAIL_TRIM = "NAIL_TRIM"


class GroomingAppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class FeedTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class FeedSubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class FeedKind(str, Enum):
    DRY = "DRY"
    FRESH = "FRESH"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class BuildStatus(str, Enum):
    QUEUED = "QUEUED"
    IN_BUILD = "IN_BUILD"
    BUILT = "BUILT"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


# ---- Entity TypedDicts (all entities are mutable -> full audit set) ----

class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    club_tier: str
    wallet_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Species(TypedDict):
    id: str
    common_name: str
    scientific_name: str
    cites_appendix: str
    permit_required: bool
    status: str
    listed_bird_count: int
    created_at: str
    updated_at: str
    version: int


class CitesPermit(TypedDict):
    id: str
    species_id: str
    permit_number: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Bird(TypedDict):
    id: str
    species_id: str
    housing_cage_id: Optional[str]
    band_code: str
    imported: bool
    list_price_cents: int
    provisional_risk_score: int
    final_risk_score: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class QuarantineRecord(TypedDict):
    id: str
    bird_id: str
    opened_at: str
    min_clear_at: str
    failed_test_count: int
    retest_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CageUnit(TypedDict):
    id: str
    label: str
    cage_class: str
    capacity: int
    nightly_rate_cents: int
    current_occupancy: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BoardingReservation(TypedDict):
    id: str
    customer_id: str
    cage_id: str
    planned_check_in: str
    planned_check_out: str
    actual_check_out: Optional[str]
    provisional_cost_cents: int
    final_cost_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class GroomingStation(TypedDict):
    id: str
    label: str
    service_types: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class GroomingAppointment(TypedDict):
    id: str
    customer_id: str
    grooming_station_id: str
    service_type: str
    slot_start: str
    slot_end: str
    fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FeedSubscription(TypedDict):
    id: str
    customer_id: str
    tier: str
    bird_count: int
    fresh_feed: bool
    fresh_item_id: Optional[str]
    monthly_charge_cents: int
    created_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryItem(TypedDict):
    id: str
    sku: str
    feed_kind: str
    quantity_on_hand: int
    quantity_allocated: int
    created_at: str
    updated_at: str
    version: int


class SpecialOrder(TypedDict):
    id: str
    customer_id: str
    cage_item_id: str
    build_qty: int
    line_items: list
    invoice_total_cents: int
    payment_status: str
    build_status: str
    created_at: str
    updated_at: str
    version: int
