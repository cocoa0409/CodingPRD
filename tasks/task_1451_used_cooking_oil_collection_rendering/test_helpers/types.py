"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this domain carry the standard common fields
(id, created_at, updated_at, version) per PRD §2.5.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    FIELD_OPS_MANAGER = "FieldOpsManager"
    ROUTE_DISPATCHER = "RouteDispatcher"
    DRIVER = "Driver"
    BILLING_ANALYST = "BillingAnalyst"
    PLANT_OPERATOR = "PlantOperator"
    CUSTOMER_CONTACT = "CustomerContact"


class CustomerStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RENEWAL_OFFERED = "RENEWAL_OFFERED"
    AT_RISK = "AT_RISK"
    TERMINATED_VOLUNTARY = "TERMINATED_VOLUNTARY"
    TERMINATED_POACHED = "TERMINATED_POACHED"
    EXPIRED = "EXPIRED"


class PricingMode(str, Enum):
    REBATE = "REBATE"
    SERVICE_FEE = "SERVICE_FEE"


class ContainerStatus(str, Enum):
    PLACED = "PLACED"
    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"
    REMOVED = "REMOVED"


class TruckStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class RouteManifestStatus(str, Enum):
    DRAFT = "DRAFT"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    RECONCILED = "RECONCILED"


class PickupVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EN_ROUTE = "EN_ROUTE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    VOID = "VOID"


class QualitySampleStatus(str, Enum):
    COLLECTED = "COLLECTED"
    SUBMITTED = "SUBMITTED"
    GRADED = "GRADED"
    DISPUTED = "DISPUTED"


class SampleGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    REJECT = "REJECT"


class MarketIndexQuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class SettlementStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    PAID = "PAID"
    VOID = "VOID"


class SettlementLineVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class ComplaintStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"
    CLOSED = "CLOSED"


class ComplaintCategory(str, Enum):
    SPILL = "SPILL"
    ODOR = "ODOR"
    NUISANCE = "NUISANCE"
    THEFT_ATTEMPT = "THEFT_ATTEMPT"


class ComplaintSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class TheftIncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"
    RESOLVED = "RESOLVED"


class ProcessingBatchStatus(str, Enum):
    INTAKE = "INTAKE"
    PROCESSED = "PROCESSED"
    SOLD = "SOLD"


class Customer(TypedDict, total=False):
    id: str
    name: str
    site_address: str
    site_max_container_gal: int
    status: str
    missed_pickup_count: int
    rebate_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict, total=False):
    id: str
    customer_id: str
    pricing_mode: str
    index_code: str
    floor_cents_per_gal: float
    cap_cents_per_gal: float
    service_fee_cents: int
    overage_threshold_gal: float
    overage_rate_cents_per_gal: float
    term_start: str
    term_end: str
    status: str
    status_before_renewal: Optional[str]
    offered_term_start: Optional[str]
    offered_term_end: Optional[str]
    activated_at: Optional[str]
    competitor_name: Optional[str]
    poach_offer_cents_per_gal: Optional[float]
    termination_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Container(TypedDict, total=False):
    id: str
    customer_id: str
    capacity_gallons: float
    est_fill_rate_gal_per_week: float
    lock_code: str
    status: str
    last_completed_pickup_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Truck(TypedDict, total=False):
    id: str
    plate: str
    tank_capacity_gallons: float
    status: str
    created_at: str
    updated_at: str
    version: int


class RouteManifest(TypedDict, total=False):
    id: str
    truck_id: str
    driver_ref: str
    service_date: str
    status: str
    projected_fill_gallons: float
    start_level_gallons: float
    end_level_gallons: float
    spill_loss_gallons: float
    collected_gallons: float
    created_at: str
    updated_at: str
    version: int


class PickupVisit(TypedDict, total=False):
    id: str
    manifest_id: str
    container_id: str
    scheduled_date: str
    status: str
    pump_gallons: float
    field_moisture_pct: float
    net_gallons_provisional: float
    retry_count: int
    failure_reason: Optional[str]
    void_reason: Optional[str]
    skipped_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QualitySample(TypedDict, total=False):
    id: str
    pickup_visit_id: str
    status: str
    lab_moisture_pct: float
    lab_impurity_pct: float
    grade: Optional[str]
    dispute_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MarketIndexQuote(TypedDict, total=False):
    id: str
    index_code: str
    week_start: str
    price_cents_per_gal: float
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict, total=False):
    id: str
    customer_id: str
    period_start: str
    period_end: str
    status: str
    provisional_total_cents: int
    final_total_cents: int
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SettlementLine(TypedDict, total=False):
    id: str
    settlement_id: str
    pickup_visit_id: str
    variant: str
    pricing_mode: str
    gallons_billed: float
    rate_cents_per_gal: Optional[float]
    line_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict, total=False):
    id: str
    customer_id: str
    pickup_visit_id: Optional[str]
    category: str
    severity: str
    note: str
    status: str
    resolved_at: Optional[str]
    reopen_count: int
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TheftIncident(TypedDict, total=False):
    id: str
    container_id: str
    evidence_note: str
    status: str
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProcessingBatch(TypedDict, total=False):
    id: str
    manifest_id: str
    input_gallons: float
    weighted_moisture_pct: float
    est_yield_gallons: float
    actual_output_gallons: float
    yield_rate: float
    sale_price_cents_per_gal: float
    sale_revenue_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
