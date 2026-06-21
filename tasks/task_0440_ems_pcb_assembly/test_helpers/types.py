"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this PRD carry the common fields id, created_at, updated_at, and
version (PRD §2.4), so every TypedDict below includes them.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Roles (PRD §2.1) ---

class UserRole(str, Enum):
    PROCESS_ENGINEER = "ProcessEngineer"
    PRODUCTION_PLANNER = "ProductionPlanner"
    QUALITY_ENGINEER = "QualityEngineer"


# --- Status enums (PRD §3) ---

class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AvlEntryStatus(str, Enum):
    APPROVED = "APPROVED"
    REVOKED = "REVOKED"


class InventoryLotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    QUARANTINED = "QUARANTINED"
    DEPLETED = "DEPLETED"


class BomStatus(str, Enum):
    DRAFT = "DRAFT"
    RELEASED = "RELEASED"
    OBSOLETE = "OBSOLETE"


class WorkOrderStatus(str, Enum):
    PLANNED = "PLANNED"
    KITTED = "KITTED"
    SETUP = "SETUP"
    RUNNING = "RUNNING"
    AT_TEST = "AT_TEST"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class KitRequirementStatus(str, Enum):
    PENDING = "PENDING"
    RESERVED = "RESERVED"
    SHORT = "SHORT"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class LineProgramStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"


class UnitQualityStatus(str, Enum):
    BUILT = "BUILT"
    PASS = "PASS"
    FAIL = "FAIL"
    REWORKED = "REWORKED"


class UnitDisposition(str, Enum):
    IN_PROCESS = "IN_PROCESS"
    SHIPPED = "SHIPPED"
    SCRAPPED = "SCRAPPED"
    RETURNED = "RETURNED"


class ReworkOrderStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    ABANDONED = "ABANDONED"


class EcoStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    IMPLEMENTED = "IMPLEMENTED"


class RmaStatus(str, Enum):
    RECEIVED = "RECEIVED"
    TRIAGED = "TRIAGED"
    REPAIRED = "REPAIRED"
    SCRAPPED = "SCRAPPED"
    CLOSED = "CLOSED"


class FailureClass(str, Enum):
    WORKMANSHIP = "WORKMANSHIP"
    COMPONENT = "COMPONENT"
    DESIGN = "DESIGN"
    NO_FAULT_FOUND = "NO_FAULT_FOUND"


class PackageType(str, Enum):
    P0402 = "0402"
    P0603 = "0603"
    P0805 = "0805"
    SOT23 = "SOT23"
    QFN = "QFN"
    BGA = "BGA"
    THT = "THT"


# --- Entity TypedDicts (all common_fields: true) ---

class Part(TypedDict):
    id: str
    internal_pn: str
    description: str
    package_type: str
    is_rohs_required: bool
    contains_conflict_minerals: bool
    standard_cost_cents: int
    total_on_hand_qty: int
    available_qty: int
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict):
    id: str
    name: str
    cage_code: str
    is_rohs_certified: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class AvlEntry(TypedDict):
    id: str
    part_id: str
    vendor_id: str
    vendor_pn: str
    approval_rank: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict):
    id: str
    part_id: str
    avl_entry_id: str
    lot_code: str
    received_qty: int
    remaining_qty: int
    unit_cost_cents: int
    is_rohs_compliant: bool
    has_cmrt: bool
    received_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Bom(TypedDict):
    id: str
    product_code: str
    revision: str
    supersedes_bom_id: Optional[str]
    status: str
    line_count: int
    created_at: str
    updated_at: str
    version: int


class BomLine(TypedDict):
    id: str
    bom_id: str
    part_id: str
    ref_designators: List[str]
    qty_per_assembly: int
    is_dnp: bool
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    bom_id: str
    planned_qty: int
    line_program_id: Optional[str]
    status: str
    kit_shortage_count: int
    built_qty: int
    passed_qty: int
    first_pass_yield_pct: float
    material_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class KitRequirement(TypedDict):
    id: str
    work_order_id: str
    part_id: str
    required_qty: int
    reserved_qty: int
    consumed_qty: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LineProgram(TypedDict):
    id: str
    bom_id: str
    line_code: str
    feeder_slot_count: int
    program_checksum: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict):
    id: str
    work_order_id: str
    serial_number: str
    quality_status: str
    disposition: str
    defect_code: Optional[str]
    rework_count: int
    created_at: str
    updated_at: str
    version: int


class ReworkOrder(TypedDict):
    id: str
    unit_id: str
    eco_id: Optional[str]
    defect_code: str
    added_material_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Eco(TypedDict):
    id: str
    title: str
    bom_id: str
    change_summary: str
    authored_by_user_id: str
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Rma(TypedDict):
    id: str
    unit_id: str
    reported_defect_code: str
    failure_class: Optional[str]
    status: str
    warranty_credit_cents: int
    created_at: str
    updated_at: str
    version: int
