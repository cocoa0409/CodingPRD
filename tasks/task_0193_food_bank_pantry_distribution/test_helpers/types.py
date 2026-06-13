"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resource model in the Food Bank Pantry Distribution PRD (§2.4, §3).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum (PRD §2.1) ---
class UserRole(str, Enum):
    FOOD_BANK_OPERATOR = "FoodBankOperator"
    ALLOCATION_MANAGER = "AllocationManager"
    AGENCY_COORDINATOR = "AgencyCoordinator"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"


# --- Status / domain enums ---
class TempZone(str, Enum):
    DRY = "DRY"
    REFRIGERATED = "REFRIGERATED"
    FROZEN = "FROZEN"


class ColdStorageStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    FULL = "FULL"


class FoodCategory(str, Enum):
    PRODUCE = "PRODUCE"
    DAIRY = "DAIRY"
    FROZEN_MEAT = "FROZEN_MEAT"
    DRY_GOODS = "DRY_GOODS"
    BAKERY = "BAKERY"


class SourceType(str, Enum):
    DONATION = "DONATION"
    RESCUE = "RESCUE"
    TEFAP = "TEFAP"
    PURCHASED = "PURCHASED"


class LotDisposition(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    DEPLETED = "DEPLETED"
    EXPIRED = "EXPIRED"
    DISPOSED = "DISPOSED"


class AgencyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CycleStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class OrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class LineStatus(str, Enum):
    PENDING = "PENDING"
    RESERVED = "RESERVED"
    SHORT = "SHORT"
    PACKED = "PACKED"


class CertificationStatus(str, Enum):
    PENDING = "PENDING"
    CERTIFIED = "CERTIFIED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class EventStatus(str, Enum):
    PLANNED = "PLANNED"
    PACKED = "PACKED"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


# --- Entity TypedDicts ---
# All entities below carry full common fields (id, created_at, updated_at, version)
# except PoundageReport (read-time snapshot: id + created_at only). (PRD §2.4)

class ColdStorageUnit(TypedDict):
    id: str
    name: str
    temp_zone: str
    capacity_lbs: float
    stored_lbs: float
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict):
    id: str
    cold_storage_unit_id: str
    food_category: str
    required_temp_zone: str
    source_type: str
    intake_lbs: float
    remaining_lbs: float
    expiration_date: str
    unit_cost_cents: int
    disposition: str
    created_at: str
    updated_at: str
    version: int


class Agency(TypedDict):
    id: str
    name: str
    service_area: str
    fair_share_weight: int
    status: str
    lifetime_distributed_lbs: float
    created_at: str
    updated_at: str
    version: int


class AllocationCycle(TypedDict):
    id: str
    label: str
    total_pool_lbs: float
    total_fair_share_weight: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AgencyOrder(TypedDict):
    id: str
    agency_id: str
    allocation_cycle_id: str
    requested_lbs: float
    approved_lbs: float
    status: str
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    agency_order_id: str
    food_category: str
    requested_lbs: float
    reserved_lbs: float
    reserved_lot_id: Optional[str]
    line_status: str
    created_at: str
    updated_at: str
    version: int


class ClientHousehold(TypedDict):
    id: str
    agency_id: str
    household_size: int
    monthly_income_cents: int
    tefap_eligible: bool
    certification_status: str
    created_at: str
    updated_at: str
    version: int


class DistributionEvent(TypedDict):
    id: str
    agency_order_id: str
    client_household_id: str
    planned_lbs: float
    actual_distributed_lbs: float
    tefap_lbs: float
    status: str
    created_at: str
    updated_at: str
    version: int


# PoundageReport is a read-time snapshot: only id + created_at (PRD §2.4).
class PoundageReport(TypedDict):
    id: str
    allocation_cycle_id: str
    total_planned_lbs: float
    total_distributed_lbs: float
    total_tefap_lbs: float
    shrinkage_lbs: float
    created_at: str
