"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    MECHANIC = "Mechanic"
    DISPATCHER = "Dispatcher"
    FLEET_MANAGER = "FleetManager"
    PLATFORM_ADMIN = "PlatformAdmin"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class FleetAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class MechanicStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OFF_DUTY = "OFF_DUTY"


class MechanicSkillTier(str, Enum):
    TIER1 = "TIER1"
    TIER2 = "TIER2"
    TIER3 = "TIER3"


class Severity(str, Enum):
    ROUTINE = "ROUTINE"
    URGENT = "URGENT"
    EMERGENCY = "EMERGENCY"


class RoutingMode(str, Enum):
    ON_SITE = "ON_SITE"
    TOW_TO_SHOP = "TOW_TO_SHOP"


class ServiceRequestStatus(str, Enum):
    INTAKE = "INTAKE"
    QUOTED = "QUOTED"
    APPROVED = "APPROVED"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_ADDON_APPROVAL = "AWAITING_ADDON_APPROVAL"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class JobVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EN_ROUTE = "EN_ROUTE"
    ON_SITE_WORKING = "ON_SITE_WORKING"
    AT_SHOP = "AT_SHOP"
    FINISHED = "FINISHED"
    ABORTED = "ABORTED"


class PartLineStatus(str, Enum):
    SOURCED = "SOURCED"
    INSTALLED = "INSTALLED"
    VOIDED = "VOIDED"


class InspectionFindingStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    FLEET_CREDIT = "FLEET_CREDIT"


class PaymentStatus(str, Enum):
    INVOICED = "INVOICED"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"


class WarrantyClaimStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


# ---- Entity TypedDicts ----
# Entities with full common fields carry id + created_at + updated_at + version.

class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    home_zone_code: str
    fleet_account_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FleetAccount(TypedDict):
    id: str
    company_name: str
    credit_limit_cents: int
    labor_discount_pct: float
    outstanding_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Mechanic(TypedDict):
    id: str
    full_name: str
    zone_code: str
    skill_tier: str
    labor_rate_cents_per_hour: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceRequest(TypedDict):
    id: str
    customer_id: str
    vehicle_vin: str
    symptom_text: str
    zone_code: str
    severity: str
    fleet_account_id: Optional[str]
    routing_mode: Optional[str]
    estimate_total_cents: Optional[int]
    final_total_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    service_request_id: str
    diagnosis_text: str
    estimated_labor_hours: float
    estimated_parts_cents: int
    tow_fee_cents: int
    labor_rate_cents_per_hour: int
    quoted_total_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class JobVisit(TypedDict):
    id: str
    service_request_id: str
    mechanic_id: str
    scheduled_start_utc: str
    scheduled_end_utc: str
    routing_mode: str
    logged_labor_hours: Optional[float]
    visit_status: str
    created_at: str
    updated_at: str
    version: int


class PartLine(TypedDict):
    id: str
    service_request_id: str
    catalog_part_id: str
    quantity: int
    unit_cost_cents: int
    unit_price_cents: Optional[int]
    line_total_cents: Optional[int]
    is_addon: bool
    status: str
    created_at: str
    updated_at: str
    version: int


# CatalogPart has common_fields: false — only id + created_at (no updated_at, no version).
class CatalogPart(TypedDict):
    id: str
    sku: str
    name: str
    wholesale_cost_cents: int
    created_at: str


class InspectionFinding(TypedDict):
    id: str
    service_request_id: str
    job_visit_id: str
    description: str
    recommended_part_id: Optional[str]
    recommended_quantity: int
    add_on_labor_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    service_request_id: str
    fleet_account_id: Optional[str]
    total_due_cents: int
    method: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    service_request_id: str
    reason_text: str
    filed_at_utc: str
    callback_visit_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
