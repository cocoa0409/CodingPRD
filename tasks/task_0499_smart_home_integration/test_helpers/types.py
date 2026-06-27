"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Status enums ---

class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    PROVISIONING = "PROVISIONING"
    SCHEDULED = "SCHEDULED"
    INSTALLING = "INSTALLING"
    COMMISSIONED = "COMMISSIONED"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class ProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class DeviceStatus(str, Enum):
    REGISTERED = "REGISTERED"
    PROVISIONED = "PROVISIONED"
    ONLINE = "ONLINE"
    FAULTED = "FAULTED"
    RETIRED = "RETIRED"


class SceneStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    DEPLOYED = "DEPLOYED"
    ARCHIVED = "ARCHIVED"


class VisitStatus(str, Enum):
    PLANNED = "PLANNED"
    CONFIRMED = "CONFIRMED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class VisitAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class ContractStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class FirmwareUpdateStatus(str, Enum):
    STAGED = "STAGED"
    APPLIED = "APPLIED"
    ROLLED_BACK = "ROLLED_BACK"
    FAILED = "FAILED"


class RmaTicketStatus(str, Enum):
    OPENED = "OPENED"
    AUTHORIZED = "AUTHORIZED"
    SHIPPED = "SHIPPED"
    CLOSED = "CLOSED"
    DENIED = "DENIED"


class ChangeOrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


# --- Domain value enums ---

class BillingTier(str, Enum):
    RESIDENTIAL = "RESIDENTIAL"
    COMMERCIAL = "COMMERCIAL"


class RegionCode(str, Enum):
    NORTH = "NORTH"
    SOUTH = "SOUTH"
    EAST = "EAST"
    WEST = "WEST"


class DeviceCategory(str, Enum):
    CONTROLLER = "CONTROLLER"
    AUDIO = "AUDIO"
    VIDEO = "VIDEO"
    NETWORK = "NETWORK"
    LIGHTING = "LIGHTING"
    ACCESSORY = "ACCESSORY"


class CertLevel(str, Enum):
    APPRENTICE = "APPRENTICE"
    JOURNEYMAN = "JOURNEYMAN"
    MASTER = "MASTER"


class VisitKind(str, Enum):
    INSTALL = "INSTALL"
    COMMISSION = "COMMISSION"
    SERVICE = "SERVICE"


class ContractPlan(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    PREMIER = "PREMIER"


class FaultCode(str, Enum):
    HARDWARE = "HARDWARE"
    FIRMWARE = "FIRMWARE"
    NETWORK = "NETWORK"
    POWER = "POWER"


class Resolution(str, Enum):
    RETURN_REPAIR = "RETURN_REPAIR"
    ADVANCE_REPLACE = "ADVANCE_REPLACE"


# --- Role enum ---

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SYSTEMS_DESIGNER = "SystemsDesigner"
    PROJECT_MANAGER = "ProjectManager"
    LOW_VOLTAGE_TECH = "LowVoltageTech"
    SUPPORT_ENGINEER = "SupportEngineer"
    CLIENT = "Client"


# --- Entity TypedDicts (all entities carry common_fields: true) ---

class Client(TypedDict):
    id: str
    full_name: str
    email: str
    billing_tier: str
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict):
    id: str
    client_id: str
    site_address: str
    region_code: str
    status: str
    accepted_proposal_id: Optional[str]
    provisioned_device_count: int
    open_change_order_count: int
    contract_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Proposal(TypedDict):
    id: str
    project_id: str
    revision: int
    status: str
    labor_hours_estimate: float
    equipment_subtotal_cents: int
    labor_cost_cents: int
    discount_cents: int
    tax_cents: int
    grand_total_cents: int
    created_at: str
    updated_at: str
    version: int


class ProposalLineItem(TypedDict):
    id: str
    proposal_id: str
    sku: str
    category: str
    qty: int
    unit_price_cents: int
    removed: bool
    created_at: str
    updated_at: str
    version: int


class Rack(TypedDict):
    id: str
    project_id: str
    rack_units_total: int
    rack_units_used: int
    subnet_cidr: str
    ip_pool_size: int
    created_at: str
    updated_at: str
    version: int


class Device(TypedDict):
    id: str
    rack_id: str
    sku: str
    category: str
    rack_units: int
    mgmt_ip: Optional[str]
    firmware_version: Optional[str]
    status: str
    is_controller: bool
    created_at: str
    updated_at: str
    version: int


class SceneProgram(TypedDict):
    id: str
    project_id: str
    name: str
    device_ids: List[str]
    status: str
    action_count: int
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict):
    id: str
    project_id: str
    region_code: str
    window_start: str
    window_end: str
    visit_kind: str
    status: str
    crew_size_required: int
    assigned_crew_count: int
    created_at: str
    updated_at: str
    version: int


class CrewMember(TypedDict):
    id: str
    full_name: str
    region_code: str
    cert_level: str
    daily_visit_cap: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class VisitAssignment(TypedDict):
    id: str
    visit_id: str
    crew_member_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    project_id: str
    plan: str
    prepaid_hours: float
    hourly_rate_cents: int
    consumed_hours: float
    status: str
    balance_cents: int
    created_at: str
    updated_at: str
    version: int


class FirmwareUpdate(TypedDict):
    id: str
    device_id: str
    target_version: str
    status: str
    prior_version: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RmaTicket(TypedDict):
    id: str
    device_id: str
    contract_id: str
    fault_code: str
    resolution: str
    status: str
    replacement_device_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict):
    id: str
    project_id: str
    description: str
    delta_cents: int
    added_labor_hours: float
    status: str
    applied_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
