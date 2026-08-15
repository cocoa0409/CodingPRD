"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    FLEET_MANAGER = "FleetManager"
    SALES_REP = "SalesRep"
    RENTAL_COORDINATOR = "RentalCoordinator"
    SERVICE_DISPATCHER = "ServiceDispatcher"
    TECHNICIAN = "Technician"
    TRAINING_REGISTRAR = "TrainingRegistrar"
    LEASE_MANAGER = "LeaseManager"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"


class PowerType(str, Enum):
    BATTERY = "BATTERY"
    LP = "LP"


class FuelProgram(str, Enum):
    BATTERY = "BATTERY"
    LP = "LP"


class UnitDisposition(str, Enum):
    NEW_SALE = "NEW_SALE"
    RENTAL_FLEET = "RENTAL_FLEET"
    USED_SALE = "USED_SALE"


class AvailabilityStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_RENT = "ON_RENT"
    IN_SHOP = "IN_SHOP"
    IN_RECON = "IN_RECON"
    LISTED = "LISTED"
    SOLD = "SOLD"
    ON_LEASE = "ON_LEASE"


class MaintenancePosture(str, Enum):
    PM_OK = "PM_OK"
    PM_DUE = "PM_DUE"


class QuoteKind(str, Enum):
    NEW_CONFIG = "NEW_CONFIG"
    USED_UNIT_SALE = "USED_UNIT_SALE"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    EXPIRED = "EXPIRED"


class RentalStatus(str, Enum):
    RESERVED = "RESERVED"
    ON_RENT = "ON_RENT"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class RateTier(str, Enum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"


class FuelEventType(str, Enum):
    CHARGE = "CHARGE"
    SWAP = "SWAP"
    LP_REFILL = "LP_REFILL"


class CallType(str, Enum):
    BREAKDOWN = "BREAKDOWN"
    PM = "PM"


class CallPriority(str, Enum):
    EMERGENCY = "EMERGENCY"
    STANDARD = "STANDARD"


class ServiceCallStatus(str, Enum):
    OPEN = "OPEN"
    DISPATCHED = "DISPATCHED"
    CLOSED = "CLOSED"


class TechnicianStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CertClass(str, Enum):
    SIT_DOWN = "SIT_DOWN"
    STAND_UP = "STAND_UP"
    ORDER_PICKER = "ORDER_PICKER"


class CertificationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class LeaseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETURNED = "RETURNED"
    SETTLED = "SETTLED"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class InspectionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"


class ReconStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class QcResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


# ---------------------------------------------------------------------------
# Entities — top-level resources carry id + created_at + updated_at + version
# (PRD §2.4); child sub-resources carry only id + created_at.
# ---------------------------------------------------------------------------

class Customer(TypedDict, total=False):
    id: str
    name: str
    credit_limit_cents: int
    discount_pct: float
    outstanding_balance_cents: int
    credit_holds_cents: int
    available_credit_cents: int
    account_status: str
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict, total=False):
    id: str
    serial_number: str
    model: str
    power_type: str
    fuel_program: str
    disposition: str
    daily_rate_cents: int
    weekly_rate_cents: int
    monthly_rate_cents: int
    pm_interval_hours: int
    hour_meter: float
    last_pm_hours: float
    next_pm_due_hours: float
    maintenance_posture: str
    availability_status: str
    resale_price_cents: Optional[int]
    utilization_pct_90d: float
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict, total=False):
    id: str
    customer_id: str
    kind: str
    unit_id: Optional[str]
    valid_until: str
    status: str
    submitted_at: Optional[str]
    revision_count: int
    subtotal_cents: int
    discount_cents: int
    tax_cents: int
    total_cents: int
    created_at: str
    updated_at: str
    version: int


class QuoteLine(TypedDict, total=False):
    # child sub-resource: id + created_at only (no updated_at / version)
    id: str
    quote_id: str
    description: str
    qty: int
    unit_price_cents: int
    extended_cents: int
    created_at: str


class RentalContract(TypedDict, total=False):
    id: str
    unit_id: str
    customer_id: str
    start_date: str
    end_date: str
    scheduled_days: int
    rate_tier: str
    provisional_estimate_cents: int
    final_charge_cents: Optional[int]
    checkout_hours: Optional[float]
    return_hours: Optional[float]
    actual_return_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MeterReading(TypedDict, total=False):
    # child sub-resource: id + created_at only
    id: str
    unit_id: str
    reading_hours: float
    note: Optional[str]
    created_at: str


class FuelEvent(TypedDict, total=False):
    # child sub-resource: id + created_at only
    id: str
    unit_id: str
    event_type: str
    kwh: float
    cylinders: int
    cost_cents: int
    created_at: str


class PartQty(TypedDict):
    part_number: str
    qty: int


class ServiceCall(TypedDict, total=False):
    id: str
    unit_id: str
    customer_id: str
    call_type: str
    priority: str
    operator_id: Optional[str]
    technician_id: Optional[str]
    required_parts: List[PartQty]
    used_parts: Optional[List[PartQty]]
    scheduled_start: Optional[str]
    scheduled_end: Optional[str]
    auto_created: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict, total=False):
    id: str
    full_name: str
    home_branch: str
    van_stock: List[PartQty]
    status: str
    created_at: str
    updated_at: str
    version: int


class Operator(TypedDict, total=False):
    id: str
    customer_id: str
    full_name: str
    badge_number: str
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict, total=False):
    id: str
    operator_id: str
    cert_class: str
    issued_at: str
    expires_at: str
    renewed_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LeaseContract(TypedDict, total=False):
    id: str
    unit_id: str
    customer_id: str
    start_date: str
    end_date: str
    allowed_hours: int
    excess_hour_rate_cents: int
    residual_value_cents: int
    return_date: Optional[str]
    settlement_total_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class LeaseInspection(TypedDict, total=False):
    # child sub-resource: id + created_at only
    id: str
    lease_id: str
    condition_grade: str
    hours_at_return: float
    appraised_value_cents: int
    wear_charge_cents: int
    status: str
    created_at: str


class ReconditioningOrder(TypedDict, total=False):
    id: str
    unit_id: str
    notes: Optional[str]
    qc_fail_count: int
    listing_price_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
