"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    OFFICE_ADMIN = "OfficeAdmin"
    ESTIMATOR = "Estimator"
    DISPATCHER = "Dispatcher"
    CREW_LEAD = "CrewLead"
    CUSTOMER = "Customer"


# ---------------------------------------------------------------------------
# Enumerations (PRD §3)
# ---------------------------------------------------------------------------
class CustomerType(str, Enum):
    RESIDENTIAL = "RESIDENTIAL"
    COMMERCIAL = "COMMERCIAL"


class LotKind(str, Enum):
    RESIDENTIAL_DRIVEWAY = "RESIDENTIAL_DRIVEWAY"
    COMMERCIAL_LOT = "COMMERCIAL_LOT"


class SlopeSeverity(str, Enum):
    NONE = "NONE"
    MODERATE = "MODERATE"
    STEEP = "STEEP"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class MaterialGrade(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    ECO = "ECO"


class MaterialLotStatus(str, Enum):
    RECEIVED = "RECEIVED"
    IN_USE = "IN_USE"
    DEPLETED = "DEPLETED"
    QUARANTINED = "QUARANTINED"


class RouteSheetStatus(str, Enum):
    OPEN = "OPEN"
    PUBLISHED = "PUBLISHED"
    WEATHER_HOLD = "WEATHER_HOLD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class ExecutionStatus(str, Enum):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    WEATHER_HOLD = "WEATHER_HOLD"
    IN_PROGRESS = "IN_PROGRESS"
    CURING = "CURING"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNINVOICED = "UNINVOICED"
    INVOICED = "INVOICED"
    PAID = "PAID"


class StripingStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PLANNING = "PLANNING"
    PLANNED = "PLANNED"
    APPROVED = "APPROVED"
    APPLIED = "APPLIED"
    VERIFIED = "VERIFIED"


class DisplacementPlanStatus(str, Enum):
    NOTICE_PENDING = "NOTICE_PENDING"
    NOTICE_SENT = "NOTICE_SENT"
    STALE = "STALE"
    CLEARED = "CLEARED"
    CANCELLED = "CANCELLED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"


class WarrantyRecordStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLAIM_OPEN = "CLAIM_OPEN"
    EXPIRED = "EXPIRED"
    EXHAUSTED = "EXHAUSTED"


class ClaimType(str, Enum):
    CRACK_RECURRENCE = "CRACK_RECURRENCE"
    PEELING = "PEELING"
    FADE = "FADE"


class WarrantyClaimStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REPAIR_SCHEDULED = "REPAIR_SCHEDULED"
    RESOLVED = "RESOLVED"


class WeatherSource(str, Enum):
    FORECAST = "FORECAST"
    OBSERVED = "OBSERVED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — every primary resource carries id, created_at,
# updated_at, version (PRD §2.4); the weather snapshot is the sole exception.
# ---------------------------------------------------------------------------
class Customer(TypedDict, total=False):
    id: str
    name: str
    customer_type: str
    email: str
    phone: str
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict, total=False):
    id: str
    customer_id: str
    address: str
    lot_kind: str
    current_area_sqft: Optional[float]
    open_quote_id: Optional[str]
    last_completed_seal_on: Optional[str]
    next_seal_eligible_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SiteAssessment(TypedDict, total=False):
    id: str
    property_id: str
    measured_area_sqft: float
    crack_linear_ft: float
    pothole_count: int
    pothole_area_sqft: float
    oil_spot_area_sqft: float
    slope_severity: str
    pavement_condition_index: int
    submitted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Material(TypedDict, total=False):
    id: str
    product_name: str
    grade: str
    coverage_sqft_per_gallon: float
    min_apply_temp_f: float
    max_precip_probability_pct: int
    cure_hours_vehicle: int
    reapplication_months: int
    warranty_months: int
    price_per_gallon_cents: int
    created_at: str
    updated_at: str
    version: int


class MaterialLot(TypedDict, total=False):
    id: str
    material_id: str
    delivered_gallons: float
    reserved_gallons: float
    consumed_gallons: float
    wasted_gallons: float
    on_hand_gallons: float
    unit_cost_cents: int
    received_on: str
    reorder_threshold_gallons: float
    reorder_flag: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict, total=False):
    id: str
    crew_name: str
    home_zone: str
    daily_capacity_sqft: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class RouteSheet(TypedDict, total=False):
    id: str
    crew_id: str
    service_date: str
    capacity_sqft: int
    booked_sqft: int
    total_drive_minutes: int
    open_capacity_sqft: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict, total=False):
    id: str
    property_id: str
    assessment_id: str
    material_id: str
    include_crack_fill: bool
    include_patch: bool
    include_seal: bool
    include_striping: bool
    coats: int
    stripe_linear_ft: Optional[float]
    discount_pct: float
    area_sqft_snapshot: float
    crack_ft_snapshot: float
    pothole_area_snapshot: float
    seal_line_cents: int
    crack_line_cents: int
    patch_line_cents: int
    striping_line_cents: int
    subtotal_cents: int
    discount_cents: int
    mobilization_fee_cents: int
    total_cents: int
    sent_at: Optional[str]
    expires_on: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    property_id: str
    quote_id: str
    warranty_claim_id: Optional[str]
    route_sheet_id: Optional[str]
    material_lot_id: Optional[str]
    include_crack_fill: bool
    include_patch: bool
    include_seal: bool
    include_striping: bool
    coats: int
    material_grade: str
    quoted_area_sqft: float
    quoted_total_cents: int
    scheduled_date: Optional[str]
    window_start_hour: Optional[int]
    window_end_hour: Optional[int]
    drive_minutes_est: Optional[int]
    vehicles_to_move: Optional[int]
    reserved_gallons: float
    execution_status: str
    billing_status: str
    striping_status: str
    stall_count: Optional[int]
    ada_stalls_required: Optional[int]
    stripe_linear_ft_computed: Optional[float]
    actual_area_sqft: Optional[float]
    actual_crack_ft: Optional[float]
    actual_pothole_area_sqft: Optional[float]
    actual_stripe_ft: Optional[float]
    gallons_used: Optional[float]
    started_at: Optional[str]
    finished_at: Optional[str]
    cure_until: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisplacementPlan(TypedDict, total=False):
    id: str
    work_order_id: str
    vehicles_to_move: int
    notice_sent_at: Optional[str]
    access_block_start: str
    access_block_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InvoiceLineItem(TypedDict, total=False):
    label: str
    amount_cents: int


class Invoice(TypedDict, total=False):
    id: str
    work_order_id: str
    line_items: list
    subtotal_cents: int
    fuel_surcharge_cents: int
    total_cents: int
    issued_at: Optional[str]
    paid_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyRecord(TypedDict, total=False):
    id: str
    work_order_id: str
    property_id: str
    warranty_months: int
    started_on: str
    expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    warranty_record_id: str
    claim_type: str
    description: str
    investigated_by: Optional[str]
    repair_work_order_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WeatherSnapshot(TypedDict, total=False):
    """Append-only weather event: carries ONLY id + created_at (PRD §2.4)."""

    id: str
    target_date: str
    min_temp_f: float
    max_temp_f: float
    precip_probability_pct: int
    precipitation_mm: float
    source: str
    created_at: str
