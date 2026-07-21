"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    STORE_MANAGER = "StoreManager"
    VET_TECH = "VetTech"
    SALES_ASSOCIATE = "SalesAssociate"
    CUSTOMER = "Customer"


class PermitClass(str, Enum):
    NONE = "NONE"
    CLASS_I = "CLASS_I"
    CLASS_II = "CLASS_II"
    CLASS_III = "CLASS_III"


class FeederType(str, Enum):
    CRICKET = "CRICKET"
    DUBIA = "DUBIA"
    MOUSE_PINKY = "MOUSE_PINKY"
    MOUSE_ADULT = "MOUSE_ADULT"
    RAT = "RAT"


class FeederSize(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class LoyaltyTier(str, Enum):
    STANDARD = "STANDARD"
    SILVER = "SILVER"
    GOLD = "GOLD"


class AnimalStatus(str, Enum):
    INTAKE = "INTAKE"
    QUARANTINE = "QUARANTINE"
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    SOLD = "SOLD"
    DECEASED = "DECEASED"


class HealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DECEASED = "DECEASED"


class QuarantineStatus(str, Enum):
    OPEN = "OPEN"
    CLEARED = "CLEARED"
    FAILED = "FAILED"


class PermitStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    REVOKED = "REVOKED"


class SaleStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    FULFILLED = "FULFILLED"
    REFUNDED = "REFUNDED"
    VOIDED = "VOIDED"
    CLOSED = "CLOSED"


class WarrantyClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    RESOLVED = "RESOLVED"


class ClaimType(str, Enum):
    DOA = "DOA"
    EARLY_DEATH = "EARLY_DEATH"


class Resolution(str, Enum):
    REFUND = "REFUND"
    REPLACEMENT = "REPLACEMENT"
    CREDIT = "CREDIT"


class FeederBatchStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEPLETED = "DEPLETED"
    RECALLED = "RECALLED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    HELD = "HELD"
    CANCELLED = "CANCELLED"


class ShipmentStatus(str, Enum):
    SHIPPED = "SHIPPED"
    REVERSED = "REVERSED"


class ReversedReason(str, Enum):
    RECALL = "RECALL"
    MANUAL = "MANUAL"


class HabitatBuildStatus(str, Enum):
    QUOTED = "QUOTED"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    IN_PROGRESS = "IN_PROGRESS"
    CHANGE_REQUESTED = "CHANGE_REQUESTED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class ExpoStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ExpoAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"


class RecallStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


# All entities in this domain carry the common system fields:
# id, created_at, updated_at, version.


class Species(TypedDict):
    id: str
    common_name: str
    scientific_name: str
    is_regulated: bool
    permit_class: str
    min_quarantine_days: int
    warranty_days: int
    care_temp_low_c: float
    care_temp_high_c: float
    care_humidity_low_pct: int
    care_humidity_high_pct: int
    feed_interval_days: int
    care_feeder_type: str
    created_at: str
    updated_at: str
    version: int


class Animal(TypedDict):
    id: str
    species_id: str
    morph: str
    sex: str
    acquisition_cost_cents: int
    list_price_cents: int
    acquired_by_user_id: str
    hatch_date: Optional[str]
    health_status: str
    status: str
    quarantine_record_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QuarantineRecord(TypedDict):
    id: str
    animal_id: str
    start_at: str
    required_until: str
    status: str
    health_checks: List[dict]
    passed_checks_count: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    loyalty_tier: str
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    customer_id: str
    permit_number: str
    permit_class: str
    issued_date: str
    expiry_date: str
    status: str
    verified_at: Optional[str]
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Sale(TypedDict):
    id: str
    animal_id: str
    customer_id: str
    permit_id: Optional[str]
    sold_at_expo: bool
    status: str
    provisional_price_cents: int
    sale_price_cents: Optional[int]
    confirmed_at: Optional[str]
    warranty_expires_at: Optional[str]
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    sale_id: str
    claim_type: str
    reason: str
    status: str
    resolution: Optional[str]
    refund_cents: Optional[int]
    replacement_animal_id: Optional[str]
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeederBatch(TypedDict):
    id: str
    feeder_type: str
    size: str
    quantity_on_hand: int
    unit_price_cents: int
    received_date: str
    expiry_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FeederSubscription(TypedDict):
    id: str
    customer_id: str
    feeder_type: str
    size: str
    quantity_per_shipment: int
    cadence_days: int
    next_ship_date: str
    status: str
    price_last_shipment_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    subscription_id: str
    feeder_type: str
    size: str
    quantity: int
    allocations: List[dict]
    shipment_cost_cents: int
    status: str
    reversed_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HabitatBuild(TypedDict):
    id: str
    customer_id: str
    spec_summary: str
    quote_cents: int
    deposit_cents: Optional[int]
    change_orders_total_cents: int
    deposit_paid: bool
    status: str
    installer_id: Optional[str]
    install_start_at: Optional[str]
    install_end_at: Optional[str]
    final_invoice_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Expo(TypedDict):
    id: str
    name: str
    venue: str
    start_at: str
    end_at: str
    venue_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExpoAssignment(TypedDict):
    id: str
    expo_id: str
    animal_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Recall(TypedDict):
    id: str
    reason: str
    target_feeder_type: str
    affected_batch_ids: List[str]
    opened_by_user_id: str
    closed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
