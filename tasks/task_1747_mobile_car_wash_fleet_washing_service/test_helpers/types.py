"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    DISPATCHER = "Dispatcher"
    CUSTOMER = "Customer"
    TECHNICIAN = "Technician"
    QUALITY_AUDITOR = "QualityAuditor"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CustomerType(str, Enum):
    RETAIL = "RETAIL"
    FLEET = "FLEET"


class SiteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SuspensionReason(str, Enum):
    MANUAL = "MANUAL"
    COMPLIANCE_INCIDENT = "COMPLIANCE_INCIDENT"


class ContainmentType(str, Enum):
    NONE = "NONE"
    BERMS = "BERMS"
    RECLAIM_MAT = "RECLAIM_MAT"
    VACUUM_RECOVERY = "VACUUM_RECOVERY"


class VehicleClass(str, Enum):
    SEDAN = "SEDAN"
    SUV_PICKUP = "SUV_PICKUP"
    VAN_BOXTRUCK = "VAN_BOXTRUCK"
    HEAVY_FLEET = "HEAVY_FLEET"


class VanStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"


class ReclaimSystem(str, Enum):
    NONE = "NONE"
    BASIC = "BASIC"
    ADVANCED = "ADVANCED"


class TechnicianStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class FleetContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class Cadence(str, Enum):
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"
    MONTHLY = "MONTHLY"


class WashOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    REWASH_PENDING = "REWASH_PENDING"
    CLOSED = "CLOSED"
    WEATHER_HELD = "WEATHER_HELD"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    WAIVED = "WAIVED"


class CancelReason(str, Enum):
    CUSTOMER_REQUEST = "CUSTOMER_REQUEST"
    DISPATCH = "DISPATCH"
    SITE_SUSPENDED = "SITE_SUSPENDED"
    NO_SHOW = "NO_SHOW"
    WEATHER_EXPIRED = "WEATHER_EXPIRED"


class HoldReason(str, Enum):
    WEATHER_FREEZE = "WEATHER_FREEZE"


class RouteStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    LOCKED = "LOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RouteCancelReason(str, Enum):
    DISPATCH = "DISPATCH"
    WEATHER_FREEZE = "WEATHER_FREEZE"


class RouteStopStatus(str, Enum):
    PLANNED = "PLANNED"
    ARRIVED = "ARRIVED"
    DONE = "DONE"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


class InspectionReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"


class AuditResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class DamageClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"


class DamageArea(str, Enum):
    EXTERIOR_BODY = "EXTERIOR_BODY"
    GLASS = "GLASS"
    WHEELS = "WHEELS"
    INTERIOR = "INTERIOR"
    TRIM = "TRIM"


class IncidentType(str, Enum):
    DISCHARGE_TO_STORM_DRAIN = "DISCHARGE_TO_STORM_DRAIN"
    CONTAINMENT_FAILURE = "CONTAINMENT_FAILURE"
    RECLAIM_EQUIPMENT_FAILURE = "RECLAIM_EQUIPMENT_FAILURE"
    SPILL = "SPILL"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"
    RESOLVED = "RESOLVED"


class InvoiceStatus(str, Enum):
    PREVIEW = "PREVIEW"
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    VOID = "VOID"


class InvoiceVariant(str, Enum):
    PROJECTION = "PROJECTION"
    FINAL = "FINAL"


class Customer(TypedDict, total=False):
    id: str
    name: str
    customer_type: str
    email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict, total=False):
    id: str
    customer_id: str
    name: str
    lot_size_sqft: int
    containment_type: str
    water_reclaim_required: bool
    max_discharge_gal: float
    status: str
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    customer_id: str
    site_id: str
    plate: str
    vehicle_class: str
    created_at: str
    updated_at: str
    version: int


class Van(TypedDict, total=False):
    id: str
    name: str
    tank_capacity_gal: float
    reclaim_system: str
    status: str
    water_loaded_gal: float
    water_reserved_gal: float
    water_used_gal: float
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict, total=False):
    id: str
    name: str
    water_reclaim_certified: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class FleetContract(TypedDict, total=False):
    id: str
    customer_id: str
    start_date: str
    end_date: str
    monthly_minimum_cents: int
    sedan_rate_cents: int
    suv_pickup_rate_cents: int
    van_boxtruck_rate_cents: int
    heavy_fleet_rate_cents: int
    loyalty_credit_pct: float
    status: str
    early_termination_fee_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PauseRecord(TypedDict, total=False):
    started_at: str
    ended_at: Optional[str]
    days: int


class Subscription(TypedDict, total=False):
    id: str
    customer_id: str
    vehicle_id: str
    cadence: str
    next_service_date: str
    status: str
    pauses: List[PauseRecord]
    pause_count_365d: int
    paused_days_365d: int
    created_at: str
    updated_at: str
    version: int


class WashOrder(TypedDict, total=False):
    id: str
    customer_id: str
    site_id: str
    subscription_id: Optional[str]
    vehicle_ids: List[str]
    scheduled_window_start: str
    scheduled_window_end: str
    requires_inspection: bool
    status: str
    billing_status: str
    vehicle_count: int
    quote_cents: int
    final_cents: Optional[int]
    vehicles_washed_ids: Optional[List[str]]
    rewash_of_id: Optional[str]
    is_rewash: bool
    hold_reason: Optional[str]
    held_at: Optional[str]
    cancel_reason: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict, total=False):
    id: str
    route_date: str
    shift_start_at: str
    van_id: str
    lead_technician_id: str
    status: str
    cancel_reason: Optional[str]
    assigned_vehicle_count: int
    reserved_water_gal: float
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict, total=False):
    id: str
    route_id: str
    wash_order_id: str
    sequence: int
    planned_start_at: str
    planned_end_at: str
    status: str
    reserved_water_gal: float
    created_at: str
    updated_at: str
    version: int


class InspectionArea(TypedDict, total=False):
    area: str
    pre_existing_damage: bool
    notes: str


class InspectionReport(TypedDict, total=False):
    id: str
    wash_order_id: str
    technician_id: str
    areas: List[InspectionArea]
    status: str
    created_at: str
    updated_at: str
    version: int


class QualityAudit(TypedDict, total=False):
    # common_fields: false — append-only record; carries ONLY id + created_at
    id: str
    created_at: str
    wash_order_id: str
    auditor_id: str
    exterior_score: int
    wheels_score: int
    glass_score: int
    trim_score: int
    water_spotting_score: int
    total_score: int
    result: str


class DamageClaim(TypedDict, total=False):
    id: str
    wash_order_id: str
    customer_id: str
    area: str
    claimed_amount_cents: int
    description: str
    status: str
    approved_amount_cents: Optional[int]
    filed_at: str
    reviewed_by: Optional[str]
    paid_by: Optional[str]
    deny_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceIncident(TypedDict, total=False):
    id: str
    site_id: str
    wash_order_id: Optional[str]
    incident_type: str
    notes: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    fleet_contract_id: str
    period_month: str
    variant: str
    status: str
    line_count: int
    charges_cents: int
    loyalty_credits_cents: int
    minimum_applied: bool
    billed_cents: int
    claim_credits_cents: int
    net_due_cents: int
    created_at: str
    updated_at: str
    version: int


JsonDict = Dict[str, Any]
