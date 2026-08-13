"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PROGRAM_MANAGER = "ProgramManager"
    DESIGNER = "Designer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PRODUCTION_PLANNER = "ProductionPlanner"
    WAREHOUSE_OPERATOR = "WarehouseOperator"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    FIELD_SERVICE_MANAGER = "FieldServiceManager"


class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    DESIGN = "DESIGN"
    PRODUCTION = "PRODUCTION"
    FULFILLMENT = "FULFILLMENT"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class RuleDimension(str, Enum):
    MAX_WIDTH_IN = "MAX_WIDTH_IN"
    MAX_HEIGHT_IN = "MAX_HEIGHT_IN"
    MAX_DEPTH_IN = "MAX_DEPTH_IN"
    ALLOWED_MATERIAL = "ALLOWED_MATERIAL"
    MAX_WEIGHT_LB = "MAX_WEIGHT_LB"


class DesignStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    COMPLIANCE_REVIEW = "COMPLIANCE_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    LOCKED = "LOCKED"


class ComplianceResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ProductionRunStatus(str, Enum):
    PLANNED = "PLANNED"
    AUTHORIZED = "AUTHORIZED"
    PRODUCED = "PRODUCED"
    CANCELLED = "CANCELLED"


class KitStatus(str, Enum):
    PENDING = "PENDING"
    KITTED = "KITTED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    DAMAGED = "DAMAGED"


class ShipmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    APPOINTMENT_SET = "APPOINTMENT_SET"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


class DamageClaimStatus(str, Enum):
    REPORTED = "REPORTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FULFILLED = "FULFILLED"


class FieldServiceRequestStatus(str, Enum):
    OPEN = "OPEN"
    DISPATCHED = "DISPATCHED"
    RESOLVED = "RESOLVED"


class IssueType(str, Enum):
    ASSEMBLY_HELP = "ASSEMBLY_HELP"
    MISSING_PARTS = "MISSING_PARTS"
    INSTRUCTION_CLARIFICATION = "INSTRUCTION_CLARIFICATION"


class Client(TypedDict, total=False):
    id: str
    name: str
    contact_email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RetailerProgram(TypedDict, total=False):
    id: str
    client_id: str
    retailer_name: str
    program_name: str
    store_count: int
    program_revenue_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceRule(TypedDict, total=False):
    id: str
    program_id: str
    dimension: str
    limit_value: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class DisplayDesign(TypedDict, total=False):
    id: str
    program_id: str
    design_code: str
    width_in: float
    height_in: float
    depth_in: float
    weight_lb: float
    material: str
    revision_number: int
    compliance_result: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionRun(TypedDict, total=False):
    id: str
    program_id: str
    design_id: str
    overage_pct: float
    production_quantity: int
    unit_cost_cents: int
    total_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Store(TypedDict, total=False):
    id: str
    program_id: str
    store_number: str
    address: str
    created_at: str
    updated_at: str
    version: int


class Kit(TypedDict, total=False):
    id: str
    production_run_id: str
    store_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    kit_id: str
    ship_window_start: str
    ship_window_end: str
    appointment_at: Optional[str]
    shipped_at: Optional[str]
    delivered_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DamageClaim(TypedDict, total=False):
    id: str
    kit_id: str
    reported_by: str
    replacement_quantity: int
    replacement_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FieldServiceRequest(TypedDict, total=False):
    id: str
    store_id: str
    program_id: str
    issue_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ProgramRecap is minted once at program close and immutable thereafter:
# it carries only id + created_at as system fields — no updated_at, no version
# (PRD §2.4, §3.7).
class ProgramRecap(TypedDict, total=False):
    id: str
    program_id: str
    total_produced: int
    total_delivered: int
    total_damaged: int
    total_cost_cents: int
    roi_pct_provisional: float
    roi_pct_final: float
    generated_at: str
    created_at: str
