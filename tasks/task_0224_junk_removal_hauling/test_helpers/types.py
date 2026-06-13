"""Domain types: entity TypedDicts, status enums, role enum (Junk Removal & Hauling)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ─────────────────────────────────────

class PricingPolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CrewStatus(str, Enum):
    ON_DUTY = "ON_DUTY"
    OFF_DUTY = "OFF_DUTY"


class TruckStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class HaulJobStatus(str, Enum):
    DRAFT = "DRAFT"
    ESTIMATED = "ESTIMATED"
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    ON_SITE = "ON_SITE"
    LOADED = "LOADED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class JobItemCategory(str, Enum):
    STANDARD = "STANDARD"
    MATTRESS = "MATTRESS"
    APPLIANCE = "APPLIANCE"
    FREON_APPLIANCE = "FREON_APPLIANCE"


class ServiceType(str, Enum):
    SAME_DAY = "SAME_DAY"
    SCHEDULED = "SCHEDULED"


class PhotoEstimateStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


class DispatchStatus(str, Enum):
    RESERVED = "RESERVED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    VOIDED = "VOIDED"


class DiversionDestination(str, Enum):
    DONATION = "DONATION"
    RECYCLING = "RECYCLING"


class DumpFeeBasis(str, Enum):
    WEIGHT_BASED = "WEIGHT_BASED"
    VOLUME_BASED = "VOLUME_BASED"


class InvoiceKind(str, Enum):
    SERVICE = "SERVICE"
    CANCELLATION = "CANCELLATION"


class InvoiceBillingStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    SETTLED = "SETTLED"


class InvoiceDisputeStatus(str, Enum):
    NONE = "NONE"
    DISPUTED = "DISPUTED"
    RESOLVED = "RESOLVED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CUSTOMER = "Customer"
    DISPATCHER = "Dispatcher"
    CREW_LEAD = "CrewLead"
    BILLING = "Billing"


# ─── Entity TypedDicts ────────────────────────────────
# Entities below carry the standard system-managed fields
# (id, created_at, updated_at, version) per PRD §2.4.

class PricingPolicy(TypedDict):
    id: str
    name: str
    full_truck_cents: int
    tier_breaks: list
    min_billable_fraction: float
    fraction_step: float
    mattress_surcharge_cents: int
    appliance_surcharge_cents: int
    freon_surcharge_cents: int
    dump_fee_per_ton_cents: int
    full_truck_dump_cents: int
    recycle_fee_per_ton_cents: int
    diversion_credit_per_ton_cents: int
    same_day_surcharge_pct: float
    tax_pct: float
    cancel_pct_scheduled: float
    cancel_pct_dispatched: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    credit_limit_cents: int
    outstanding_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict):
    id: str
    name: str
    shift_start_utc: str
    shift_end_utc: str
    buffer_minutes: int
    hazmat_certified: bool
    reserved_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Truck(TypedDict):
    id: str
    name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class HaulJob(TypedDict):
    id: str
    customer_id: str
    pricing_policy_id: str
    service_type: str
    address: str
    estimated_truck_fraction: Optional[float]
    measured_truck_fraction: Optional[float]
    estimated_total_cents: Optional[int]
    final_total_cents: Optional[int]
    cancellation_fee_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class JobItem(TypedDict):
    id: str
    haul_job_id: str
    category: str
    quantity: int
    description: str
    created_at: str
    updated_at: str
    version: int


class PhotoEstimate(TypedDict):
    id: str
    haul_job_id: str
    photo_url: str
    raw_fraction: float
    declared_items: list
    accepted: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispatch(TypedDict):
    id: str
    haul_job_id: str
    crew_id: str
    truck_id: str
    window_start_utc: str
    window_end_utc: str
    window_minutes: int
    dispatch_status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    haul_job_id: str
    customer_id: str
    total_cents: int
    kind: str
    billing_status: str
    dispute_status: str
    created_at: str
    updated_at: str
    version: int


# Append-only line items (PRD §2.4): only id + created_at — no updated_at, no version.

class DiversionRecord(TypedDict):
    id: str
    haul_job_id: str
    destination: str
    tons: float
    created_at: str


class DumpTicket(TypedDict):
    id: str
    haul_job_id: str
    landfill_tons: float
    landfill_fraction: float
    fee_basis: str
    dump_fee_cents: Optional[int]
    created_at: str
