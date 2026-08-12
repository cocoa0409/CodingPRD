"""Domain types: entity TypedDicts, status enums, role enum (PRD sections 2-4)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ------------------------------------------------------------------ enums
class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CatalogCategory(str, Enum):
    CRIB = "CRIB"
    STROLLER = "STROLLER"
    CARSEAT = "CARSEAT"


class CatalogItemStatus(str, Enum):
    LISTED = "LISTED"
    DELISTED = "DELISTED"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class UnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    RENTED_OUT = "RENTED_OUT"
    AWAITING_CLEANING = "AWAITING_CLEANING"
    IN_CLEANING = "IN_CLEANING"
    QUARANTINED = "QUARANTINED"
    RETIRED = "RETIRED"


class PartnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PricingModel(str, Enum):
    PER_DAY = "PER_DAY"
    PERCENT_OF_RENTAL = "PERCENT_OF_RENTAL"


class Severity(str, Enum):
    COSMETIC = "COSMETIC"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    TOTAL_LOSS = "TOTAL_LOSS"


class ReservationStatus(str, Enum):
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    DEPOSIT_PENDING = "DEPOSIT_PENDING"
    DEPOSIT_HELD = "DEPOSIT_HELD"
    SETTLED_PAID = "SETTLED_PAID"
    REFUNDED = "REFUNDED"


class LineStatus(str, Enum):
    PENDING = "PENDING"
    ALLOCATED = "ALLOCATED"
    OUT = "OUT"
    RETURNED = "RETURNED"
    PENDING_REALLOCATION = "PENDING_REALLOCATION"
    CANCELLED = "CANCELLED"


class RouteStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"


class StopType(str, Enum):
    DELIVERY_SETUP = "DELIVERY_SETUP"
    PICKUP = "PICKUP"


class StopStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ExtensionStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SUPERSEDED = "SUPERSEDED"


class ClaimStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    DISPUTED = "DISPUTED"
    CAPTURED = "CAPTURED"


class RecallSeverity(str, Enum):
    ADVISORY = "ADVISORY"
    MANDATORY = "MANDATORY"


class RecallStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class TicketType(str, Enum):
    STANDARD = "STANDARD"
    DEEP = "DEEP"
    RECALL_DECONTAMINATION = "RECALL_DECONTAMINATION"


class TicketStatus(str, Enum):
    OPEN = "OPEN"
    PASSED = "PASSED"
    FAILED = "FAILED"


class TxnType(str, Enum):
    HOLD = "HOLD"
    CAPTURE = "CAPTURE"
    RELEASE = "RELEASE"


class TxnReason(str, Enum):
    HOLD_AT_CONFIRM = "HOLD_AT_CONFIRM"
    DAMAGE_CLAIM = "DAMAGE_CLAIM"
    LATE_FEE = "LATE_FEE"
    CANCELLATION_FEE = "CANCELLATION_FEE"
    RELEASE_REMAINDER = "RELEASE_REMAINDER"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CUSTOMER = "Customer"
    HOTEL_PARTNER = "HotelPartner"
    INSPECTOR = "Inspector"
    OPERATIONS_ADMIN = "OperationsAdmin"


# ---------------------------------------------------------------- entities
class Customer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    phone: str
    status: str
    risk_score: int
    late_return_count: int
    captured_damage_count: int
    created_at: str
    updated_at: str
    version: int


class CatalogItem(TypedDict, total=False):
    id: str
    name: str
    category: str
    daily_rate_cents: int
    deposit_amount_cents: int
    weight_kg: float
    cleaning_turnaround_hours: int
    deep_clean_every_cycles: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryUnit(TypedDict, total=False):
    id: str
    catalog_item_id: str
    serial_number: str
    condition_grade: str
    status: str
    cleans_since_deep: int
    blocked_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HotelPartner(TypedDict, total=False):
    id: str
    name: str
    zone_code: str
    commission_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class InsurancePlan(TypedDict, total=False):
    id: str
    code: str
    pricing_model: str
    rate_value: float
    deductible_cents: int
    coverage_cap_cents: int
    covered_severities: List[str]
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict, total=False):
    id: str
    customer_id: str
    hotel_partner_id: Optional[str]
    delivery_address: str
    zone_code: str
    start_date: str
    end_date: str
    insurance_plan_id: Optional[str]
    status: str
    payment_status: str
    quoted_total_cents: int
    gear_subtotal_cents: int
    final_total_cents: Optional[int]
    deposit_hold_cents: int
    deposit_captured_cents: int
    deposit_released_cents: int
    late_fee_cents: int
    extension_charge_cents: int
    extension_days: int
    commission_cents: int
    returned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReservationLine(TypedDict, total=False):
    id: str
    reservation_id: str
    catalog_item_id: str
    assigned_unit_id: Optional[str]
    status: str
    unit_rate_cents: int
    line_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class DeliveryRoute(TypedDict, total=False):
    id: str
    route_date: str
    zone_code: str
    vehicle_capacity_kg: float
    status: str
    planned_weight_kg: float
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict, total=False):
    id: str
    route_id: str
    reservation_id: str
    stop_type: str
    address: str
    time_window_start: str
    time_window_end: str
    status: str
    sequence: int
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExtensionRequest(TypedDict, total=False):
    id: str
    reservation_id: str
    requested_end_date: str
    status: str
    extension_charge_cents: int
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DamageClaim(TypedDict, total=False):
    id: str
    reservation_line_id: str
    severity: str
    repair_cost_cents: int
    description: str
    filed_by_user_id: str
    reviewed_by_user_id: Optional[str]
    status: str
    capture_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class RecallNotice(TypedDict, total=False):
    id: str
    catalog_item_id: str
    recall_code: str
    severity: str
    description: str
    status: str
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CleaningTicket(TypedDict, total=False):
    id: str
    unit_id: str
    ticket_type: str
    status: str
    inspector_user_id: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only ledger entry: carries ONLY id + created_at (no updated_at, no version)
class DepositTransaction(TypedDict, total=False):
    id: str
    reservation_id: str
    txn_type: str
    amount_cents: int
    reason: str
    balance_after_cents: int
    created_at: str
