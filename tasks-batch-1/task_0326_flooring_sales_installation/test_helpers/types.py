"""Domain types: entity TypedDicts, status enums, role enum for the Flooring API."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ─────────────────────────────────────────────────────────

class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class JobStatus(str, Enum):
    DRAFT = "DRAFT"
    MEASURED = "MEASURED"
    RE_MEASURE = "RE_MEASURE"
    ESTIMATED = "ESTIMATED"
    ACCEPTED = "ACCEPTED"
    IN_INSTALL = "IN_INSTALL"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EstimateStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    ACCEPTED = "ACCEPTED"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class EstimateVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    MEASURED = "MEASURED"


class MaterialOrderStatus(str, Enum):
    ORDERED = "ORDERED"
    BACKORDERED = "BACKORDERED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class InstallCrewStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    INACTIVE = "INACTIVE"


class InstallSlotStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"
    DONE = "DONE"


class WarrantyClaimStatus(str, Enum):
    FILED = "FILED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ProductCategory(str, Enum):
    HARDWOOD = "HARDWOOD"
    LVP = "LVP"
    TILE = "TILE"
    CARPET = "CARPET"


class UserRole(str, Enum):
    ADMIN = "Admin"
    SALES_REP = "SalesRep"
    ESTIMATOR = "Estimator"
    SCHEDULER = "Scheduler"
    CUSTOMER = "Customer"


# ─── Entity TypedDicts ────────────────────────────────────────────────────
# Entities with the uniform system-managed field set carry id, created_at,
# updated_at, and version. Customer and SalesRep are registration records that
# carry ONLY id and created_at (no updated_at, no version).

class Product(TypedDict):
    id: str
    sku: str
    name: str
    category: str
    material_cost_per_sqft_cents: int
    labor_rate_per_sqft_cents: int
    requires_underlayment: bool
    underlayment_cost_per_sqft_cents: int
    lead_time_days: int
    warranty_years: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Job(TypedDict):
    id: str
    customer_id: str
    sales_rep_id: str
    product_id: str
    declared_sqft: float
    measured_sqft: Optional[float]
    tear_out_sqft: Optional[float]
    room_count: Optional[int]
    waste_factor_pct: Optional[float]
    status: str
    warranty_risk_score: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Estimate(TypedDict):
    id: str
    job_id: str
    variant: str
    billable_sqft: float
    material_cost_cents: int
    underlayment_cost_cents: int
    labor_cost_cents: int
    total_cents: int
    status: str
    valid_until: str
    expected_job_version: int
    created_at: str
    updated_at: str
    version: int


class MaterialOrder(TypedDict):
    id: str
    job_id: str
    product_id: str
    order_sqft: float
    lead_time_days: int
    expected_ready_date: str
    status: str
    backorder_count: int
    created_at: str
    updated_at: str
    version: int


class InstallCrew(TypedDict):
    id: str
    name: str
    skill_categories: List[str]
    daily_sqft_capacity: int
    buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InstallSlot(TypedDict):
    id: str
    job_id: str
    crew_id: str
    start_at: str
    end_at: str
    scheduled_sqft: float
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    job_id: str
    filed_at: str
    defect_description: str
    status: str
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — registration records, only id + created_at.
class Customer(TypedDict):
    id: str
    full_name: str
    address: str
    email: str
    created_at: str


class SalesRep(TypedDict):
    id: str
    name: str
    created_at: str
