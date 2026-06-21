"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Moving & Relocation Booking PRD. Money is integer cents
throughout. SurveyItem and ClaimItem are append-only line items carrying only
id and created_at (no updated_at, no version).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum (PRD §2.1: exactly five roles) ─────────────────────────────────
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    ESTIMATOR = "Estimator"
    DISPATCHER = "Dispatcher"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Status enums ─────────────────────────────────────────────────────────────
class MoveJobStatus(str, Enum):
    QUOTING = "QUOTING"
    BOOKED = "BOOKED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    PAID_IN_FULL = "PAID_IN_FULL"
    REFUNDED = "REFUNDED"


class ServiceType(str, Enum):
    LOCAL = "LOCAL"
    LONG_HAUL = "LONG_HAUL"


class SurveyMethod(str, Enum):
    IN_HOME = "IN_HOME"
    VIRTUAL = "VIRTUAL"
    SELF_REPORTED = "SELF_REPORTED"


class BindingType(str, Enum):
    BINDING = "BINDING"
    NON_BINDING = "NON_BINDING"


class ValuationCoverage(str, Enum):
    RELEASED = "RELEASED"
    FULL_VALUE = "FULL_VALUE"


class EstimateStatus(str, Enum):
    DRAFT = "DRAFT"
    REVISED = "REVISED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class DispatchStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EN_ROUTE = "EN_ROUTE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class StorageLotStatus(str, Enum):
    IN_STORAGE = "IN_STORAGE"
    RELEASED = "RELEASED"
    WAIVED = "WAIVED"


class DamageClaimStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class PaymentKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    BALANCE = "BALANCE"


# ─── Entity TypedDicts (common_fields: true → id+created_at+updated_at+version) ─
class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    origin_state_code: str
    phone: str
    created_at: str
    updated_at: str
    version: int


class MoveJob(TypedDict):
    id: str
    customer_id: str
    service_type: str
    origin_zip: str
    destination_zip: str
    distance_miles: int
    requested_move_date: str
    stair_flights: int
    long_carry_units: int
    job_status: str
    payment_status: str
    accepted_estimate_id: Optional[str]
    final_charge_cents: int
    gross_charges_cents: int
    balance_due_cents: int
    paid_cents: int
    waived_cents: int
    refunded_cents: int
    created_at: str
    updated_at: str
    version: int


class InventorySurvey(TypedDict):
    id: str
    move_job_id: str
    survey_method: str
    total_cubic_feet: float
    estimated_weight_lbs: int
    locked: bool
    created_at: str
    updated_at: str
    version: int


class Estimate(TypedDict):
    id: str
    move_job_id: str
    survey_id: str
    estimator_user_id: str
    binding_type: str
    valuation_coverage: str
    declared_value_cents: int
    deductible_cents: int
    linehaul_cents: int
    labor_cents: int
    fuel_surcharge_cents: int
    packing_cents: int
    valuation_premium_cents: int
    accessorial_cents: int
    estimate_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PackingOrder(TypedDict):
    id: str
    move_job_id: str
    crate_count: int
    packing_lines: List[dict]
    packing_total_cents: int
    created_at: str
    updated_at: str
    version: int


class Truck(TypedDict):
    id: str
    plate: str
    capacity_cubic_feet: int
    home_state_code: str
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict):
    id: str
    name: str
    head_count: int
    home_state_code: str
    created_at: str
    updated_at: str
    version: int


class Dispatch(TypedDict):
    id: str
    move_job_id: str
    truck_id: str
    crew_id: str
    window_start: str
    window_end: str
    required_crew_size: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StorageLot(TypedDict):
    id: str
    move_job_id: str
    intake_date: str
    release_date: Optional[str]
    billable_days: int
    sit_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DamageClaim(TypedDict):
    id: str
    move_job_id: str
    filed_by_user_id: str
    adjudicated_by_user_id: Optional[str]
    coverage_snapshot: str
    deductible_cents: int
    settlement_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Append-only line items (common_fields: false → only id + created_at) ──────
class SurveyItem(TypedDict):
    id: str
    survey_id: str
    label: str
    quantity: int
    cubic_feet_each: float
    created_at: str


class ClaimItem(TypedDict):
    id: str
    claim_id: str
    label: str
    item_weight_lbs: int
    repair_cost_cents: int
    replacement_value_cents: int
    created_at: str
