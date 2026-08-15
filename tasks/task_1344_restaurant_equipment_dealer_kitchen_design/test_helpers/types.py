"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this PRD carry the common fields (id, created_at, updated_at,
version) — the PRD states that no entity is exempt from updated_at or version.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Status enums (one per stateful entity)
# ---------------------------------------------------------------------------

class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ProjectStatus(str, Enum):
    DESIGN = "DESIGN"
    QUOTED = "QUOTED"
    CONTRACTED = "CONTRACTED"
    FABRICATION = "FABRICATION"
    DELIVERED = "DELIVERED"
    COMMISSIONED = "COMMISSIONED"
    PUNCH_CLOSED = "PUNCH_CLOSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class LayoutStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class EquipmentItemStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ORDERED = "ORDERED"
    RECEIVED = "RECEIVED"
    INSTALLED = "INSTALLED"
    STARTED = "STARTED"
    CANCELLED = "CANCELLED"


class WarrantyStatus(str, Enum):
    UNREGISTERED = "UNREGISTERED"
    REGISTERED = "REGISTERED"


class ItemKind(str, Enum):
    STOCK = "STOCK"
    CUSTOM_FABRICATION = "CUSTOM_FABRICATION"


class FabricationOrderStatus(str, Enum):
    PENDING_SHOP_DRAWING = "PENDING_SHOP_DRAWING"
    SHOP_DRAWING_APPROVED = "SHOP_DRAWING_APPROVED"
    IN_PRODUCTION = "IN_PRODUCTION"
    FAB_COMPLETE = "FAB_COMPLETE"
    CANCELLED = "CANCELLED"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    PRESENTED = "PRESENTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class QuoteVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class FilingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class FilingAuthority(str, Enum):
    HEALTH_DEPT = "HEALTH_DEPT"
    BUILDING_DEPT = "BUILDING_DEPT"
    FIRE_MARSHAL = "FIRE_MARSHAL"


class DeliveryJobStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    SITE_COMPLETE = "SITE_COMPLETE"
    CANCELLED = "CANCELLED"


class StartupSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETE = "COMPLETE"
    VOID = "VOID"


class ServiceAgencyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ServiceAssignmentStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    TRANSFERRED = "TRANSFERRED"


class PunchSeverity(str, Enum):
    COSMETIC = "COSMETIC"
    FUNCTIONAL = "FUNCTIONAL"
    LIFE_SAFETY = "LIFE_SAFETY"


class PunchListItemStatus(str, Enum):
    OPEN = "OPEN"
    VERIFIED = "VERIFIED"
    VOID = "VOID"


class HealthJurisdiction(str, Enum):
    CITY_HEALTH = "CITY_HEALTH"
    COUNTY_HEALTH = "COUNTY_HEALTH"
    STATE_HEALTH = "STATE_HEALTH"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PROJECT_MANAGER = "ProjectManager"
    KITCHEN_DESIGNER = "KitchenDesigner"
    SALES_REP = "SalesRep"
    CUSTOMER = "Customer"
    PERMIT_COORDINATOR = "PermitCoordinator"
    FABRICATION_LEAD = "FabricationLead"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    STARTUP_TECHNICIAN = "StartupTechnician"
    SERVICE_MANAGER = "ServiceManager"


# ---------------------------------------------------------------------------
# Entity TypedDicts — every entity carries id/created_at/updated_at/version
# ---------------------------------------------------------------------------

class Customer(TypedDict, total=False):
    id: str
    legal_name: str
    contact_email: str
    credit_limit_cents: int
    outstanding_exposure_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict, total=False):
    id: str
    customer_id: str
    project_name: str
    site_address: str
    health_jurisdiction: str
    quote_baseline_cents: int
    retainage_pct: float
    retainage_held_cents: int
    warranty_registered_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class KitchenLayout(TypedDict, total=False):
    id: str
    project_id: str
    layout_label: str
    drawing_ref: str
    hood_required: bool
    revision_no: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EquipmentItem(TypedDict, total=False):
    id: str
    layout_id: str
    project_id: str
    model_no: str
    item_kind: str
    quantity: int
    unit_price_cents: int
    lead_time_days: int
    requires_hood: bool
    warranty_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FabricationOrder(TypedDict, total=False):
    id: str
    project_id: str
    equipment_item_id: str
    shop_drawing_ref: str
    quoted_fab_cost_cents: int
    final_fab_cost_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict, total=False):
    id: str
    project_id: str
    layout_id: str
    equipment_subtotal_cents: int
    freight_cents: int
    installation_cents: int
    startup_cents: int
    grand_total_cents: int
    variant: str
    revision_no: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PermitFiling(TypedDict, total=False):
    id: str
    project_id: str
    layout_id: str
    authority: str
    submitted_at: Optional[str]
    review_cycle_no: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryJob(TypedDict, total=False):
    id: str
    project_id: str
    scheduled_start: str
    scheduled_end: str
    rigging_required: bool
    rigging_crew_size: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StartupSession(TypedDict, total=False):
    id: str
    project_id: str
    equipment_item_id: str
    technician_name: str
    demo_minutes: int
    warranty_registered: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceAgency(TypedDict, total=False):
    id: str
    agency_name: str
    covered_jurisdictions: List[str]
    capacity: int
    open_assignment_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceAssignment(TypedDict, total=False):
    id: str
    project_id: str
    agency_id: str
    opened_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PunchListItem(TypedDict, total=False):
    id: str
    project_id: str
    description: str
    severity: str
    status: str
    created_at: str
    updated_at: str
    version: int
