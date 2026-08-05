"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this system are mutable and therefore carry the four common
properties id, created_at, updated_at, version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    MEMBER = "Member"
    VAULT_MANAGER = "VaultManager"
    CONCIERGE_TECH = "ConciergeTech"
    BILLING_ADMIN = "BillingAdmin"


class UnitClass(str, Enum):
    STANDARD = "STANDARD"
    CLIMATE = "CLIMATE"
    SHOWCASE = "SHOWCASE"


class UnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class MembershipTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class BillingStatus(str, Enum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"
    SUSPENDED = "SUSPENDED"


class FuelType(str, Enum):
    ICE = "ICE"
    HYBRID = "HYBRID"
    EV = "EV"


class ConditionStatus(str, Enum):
    INTAKE_PENDING = "INTAKE_PENDING"
    DOCUMENTED = "DOCUMENTED"
    DAMAGE_HOLD = "DAMAGE_HOLD"


class InsuranceStatus(str, Enum):
    NONE = "NONE"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"


class COIStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class AgreementStatus(str, Enum):
    PENDING = "PENDING"
    IN_STORAGE = "IN_STORAGE"
    CHECKED_OUT = "CHECKED_OUT"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class MonitorType(str, Enum):
    BATTERY_TENDER = "BATTERY_TENDER"
    CLIMATE = "CLIMATE"
    BOTH = "BOTH"


class MonitoringStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class ServiceType(str, Enum):
    DETAIL = "DETAIL"
    START_ENGINE = "START_ENGINE"
    CHECKOUT = "CHECKOUT"
    CHECKIN = "CHECKIN"
    FUEL = "FUEL"


class ServiceOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    IN_PROGRESS = "IN_PROGRESS"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TransporterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class DeliveryJobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OUT_FOR_EVENT = "OUT_FOR_EVENT"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class WaitlistStatus(str, Enum):
    WAITING = "WAITING"
    OFFERED = "OFFERED"
    CLAIMED = "CLAIMED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class InspectionType(str, Enum):
    INTAKE = "INTAKE"
    PERIODIC = "PERIODIC"
    CHECKOUT = "CHECKOUT"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class ProrationMode(str, Enum):
    FULL_MONTH = "FULL_MONTH"
    PRORATED = "PRORATED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class Facility(TypedDict):
    id: str
    name: str
    total_units: int
    units_available: int
    units_reserved: int
    units_occupied: int
    units_out_of_service: int
    created_at: str
    updated_at: str
    version: int


class StorageUnit(TypedDict):
    id: str
    facility_id: str
    unit_code: str
    unit_class: str
    climate_controlled: bool
    monthly_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    full_name: str
    email: str
    membership_tier: str
    tier_discount_pct: float
    billing_status: str
    charged_cents: int
    paid_cents: int
    held_cents: int
    account_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    member_id: str
    make: str
    model: str
    model_year: int
    vin: str
    fuel_type: str
    declared_value_cents: int
    condition_status: str
    insurance_status: str
    created_at: str
    updated_at: str
    version: int


class InsuranceCOI(TypedDict):
    id: str
    vehicle_id: str
    policy_number: str
    carrier: str
    coverage_amount_cents: int
    effective_at: str
    expiry_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class StorageAgreement(TypedDict):
    id: str
    member_id: str
    vehicle_id: str
    unit_id: str
    move_in_at: str
    planned_move_out_at: str
    actual_move_out_at: Optional[str]
    monthly_rate_cents: int
    days_stored: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class MonitoringSubscription(TypedDict):
    id: str
    agreement_id: str
    monitor_type: str
    monthly_fee_cents: int
    status: str
    last_battery_voltage: Optional[float]
    low_battery_alert: bool
    created_at: str
    updated_at: str
    version: int


class ServiceOrder(TypedDict):
    id: str
    agreement_id: str
    service_type: str
    estimated_labor_hours: float
    actual_labor_hours: Optional[float]
    parts_cents: int
    estimated_cost_cents: Optional[int]
    final_cost_cents: Optional[int]
    scheduled_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Transporter(TypedDict):
    id: str
    name: str
    buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryJob(TypedDict):
    id: str
    vehicle_id: str
    transporter_id: str
    event_name: str
    pickup_at: str
    dropoff_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict):
    id: str
    member_id: str
    desired_unit_class: str
    facility_id: str
    status: str
    offered_unit_id: Optional[str]
    offer_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    vehicle_id: str
    inspection_type: str
    status: str
    damage_noted: bool
    findings: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    member_id: str
    agreement_id: str
    period_start_at: str
    period_end_at: str
    proration_mode: str
    line_items: List[dict]
    subtotal_cents: int
    tax_cents: int
    total_cents: int
    due_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
