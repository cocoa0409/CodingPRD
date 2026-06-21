"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the Laundry & Dry-Cleaning Delivery PRD resource model.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CUSTOMER = "Customer"
    DISPATCH_AGENT = "DispatchAgent"
    PLANT_OPERATOR = "PlantOperator"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class OrderStatus(str, Enum):
    CREATED = "CREATED"
    SCHEDULED = "SCHEDULED"
    PICKED_UP = "PICKED_UP"
    IN_PROCESSING = "IN_PROCESSING"
    QC_HOLD = "QC_HOLD"
    READY = "READY"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class GarmentStatus(str, Enum):
    INTAKE_PENDING = "INTAKE_PENDING"
    INTAKE_LOGGED = "INTAKE_LOGGED"
    CLEANING = "CLEANING"
    CLEANED = "CLEANED"
    PACKED = "PACKED"
    LOST = "LOST"


class ServiceType(str, Enum):
    WASH_FOLD = "WASH_FOLD"
    DRY_CLEAN = "DRY_CLEAN"
    ALTERATION = "ALTERATION"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    INVESTIGATING = "INVESTIGATING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SETTLED = "SETTLED"
    DENIED_FINAL = "DENIED_FINAL"


class ClaimSubjectKind(str, Enum):
    ORDER = "ORDER"
    GARMENT = "GARMENT"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"


class RouteWindowKind(str, Enum):
    PICKUP = "PICKUP"
    DELIVERY = "DELIVERY"


class RouteWindowStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"


class LockerStatus(str, Enum):
    OPEN = "OPEN"


class LockerAssignmentStatus(str, Enum):
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class HandoffMethod(str, Enum):
    DOORSTEP = "DOORSTEP"
    LOCKER = "LOCKER"


class PlanTier(str, Enum):
    LITE = "LITE"
    PLUS = "PLUS"
    PREMIUM = "PREMIUM"


class NoteKind(str, Enum):
    STAIN = "STAIN"
    DAMAGE = "DAMAGE"


# --------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true → id + created_at + updated_at + version)
# --------------------------------------------------------------------------
class SubscriptionPlan(TypedDict):
    id: str
    tier: str
    monthly_fee_cents: int
    included_wash_fold_grams: int
    overage_rate_cents_per_kg: int
    dryclean_discount_pct: float
    rush_waived: bool
    active: bool
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    default_address: str
    zone_code: str
    wallet_credit_cents: int
    risk_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    customer_id: str
    plan_id: str
    cycle_start_utc: str
    cycle_wash_fold_grams_used: int
    outstanding_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RouteWindow(TypedDict):
    id: str
    zone_code: str
    window_kind: str
    start_utc: str
    end_utc: str
    stop_capacity: int
    booked_stops: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Locker(TypedDict):
    id: str
    zone_code: str
    location_label: str
    compartment_count: int
    hold_buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    subscription_id: Optional[str]
    pickup_window_id: str
    delivery_window_id: str
    handoff_method: str
    rush: bool
    ready_by_utc: Optional[str]
    estimate_total_cents: int
    final_total_cents: int
    risk_flag: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Garment(TypedDict):
    id: str
    order_id: str
    service_type: str
    declared_weight_grams: int
    declared_piece_count: int
    actual_weight_grams: int
    actual_piece_count: int
    alteration_fee_cents: int
    estimate_line_cents: int
    final_line_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LockerAssignment(TypedDict):
    id: str
    order_id: str
    locker_id: str
    compartment_index: int
    hold_start_utc: str
    hold_end_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    order_id: str
    subject_kind: str
    garment_id: Optional[str]
    declared_value_cents: int
    settlement_cents: int
    appeal_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    order_id: str
    gross_cents: int
    subscription_credit_cents: int
    wallet_applied_cents: int
    amount_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Append-only entity (common_fields: false → id + created_at only)
# --------------------------------------------------------------------------
class GarmentNote(TypedDict):
    id: str
    garment_id: str
    note_kind: str
    severity: int
    description: str
    logged_by_role: str
    created_at: str
