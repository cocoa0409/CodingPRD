"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Food Safety & Traceability PRD. The AllergenProfile is the
single immutable entity (no updated_at, no version); every other entity carries
the full common-field set.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Status enums --------------------------------------------------------

class CoaStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class LotStatus(str, Enum):
    RECEIVED = "RECEIVED"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"
    DESTROYED = "DESTROYED"


class LotHoldStatus(str, Enum):
    FREE = "FREE"
    HELD = "HELD"


class LotCoaStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class LotKind(str, Enum):
    RAW_MATERIAL = "RAW_MATERIAL"
    FINISHED = "FINISHED"


class ProductionRunStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    ABORTED = "ABORTED"


class HoldOrderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    DISPOSED = "DISPOSED"


class HoldDisposition(str, Enum):
    RELEASED = "RELEASED"
    DISPOSED = "DISPOSED"


class HoldReason(str, Enum):
    ALLERGEN = "ALLERGEN"
    PATHOGEN = "PATHOGEN"
    TEMPERATURE_EXCURSION = "TEMPERATURE_EXCURSION"
    RECALL = "RECALL"
    OTHER = "OTHER"


class SupplierApprovalStatus(str, Enum):
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"


class CcpClassification(str, Enum):
    IN_SPEC = "IN_SPEC"
    DEVIATION = "DEVIATION"


class UserRole(str, Enum):
    QUALITY_MANAGER = "QualityManager"
    RECEIVING_CLERK = "ReceivingClerk"
    PRODUCTION_OPERATOR = "ProductionOperator"
    SAFETY_AUDITOR = "SafetyAuditor"


# --- Entity TypedDicts ---------------------------------------------------

# common_fields: true
class Facility(TypedDict):
    id: str
    name: str
    gln: str
    current_utc: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Supplier(TypedDict):
    id: str
    facility_id: str
    name: str
    approval_status: str
    coa_required: bool
    failed_coa_streak: int
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Ingredient(TypedDict):
    id: str
    facility_id: str
    name: str
    storage_target_c: float
    storage_tolerance_c: float
    shelf_life_days: int
    declared_allergen_codes: List[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable, only id + created_at
class AllergenProfile(TypedDict):
    id: str
    facility_id: str
    code: str
    name: str
    severity_rank: int
    created_at: str


# common_fields: true
class Lot(TypedDict):
    id: str
    facility_id: str
    supplier_id: Optional[str]
    ingredient_id: str
    lot_code: str
    lot_kind: str
    received_qty: float
    available_qty: float
    production_date: str
    expiration_date: Optional[str]
    effective_expiration_date: str
    cumulative_excursion_minutes: int
    effective_allergen_codes: List[str]
    controlling_allergen_code: Optional[str]
    status: str
    hold_status: str
    coa_status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class CertificateOfAnalysis(TypedDict):
    id: str
    lot_id: str
    supplier_id: str
    measured_allergen_codes: List[str]
    pathogen_pass: bool
    declared_shelf_life_days: int
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class ProductionRun(TypedDict):
    id: str
    facility_id: str
    ingredient_id: str
    planned_output_qty: float
    output_lot_id: Optional[str]
    started_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class ConsumedLot(TypedDict):
    id: str
    production_run_id: str
    source_lot_id: str
    quantity: float
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class CCPReading(TypedDict):
    id: str
    lot_id: str
    ccp_type: str
    measured_value_c: float
    measured_at: str
    classification: str
    excursion_minutes: int
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class HoldOrder(TypedDict):
    id: str
    facility_id: str
    target_lot_id: str
    reason: str
    disposition: Optional[str]
    held_lot_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class StorageZone(TypedDict):
    id: str
    facility_id: str
    zone_code: str
    capacity_units: float
    target_temp_c: float
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class StorageBooking(TypedDict):
    id: str
    zone_id: str
    lot_id: str
    start_utc: str
    end_utc: str
    capacity_units: float
    created_at: str
    updated_at: str
    version: int


class RecallTrace(TypedDict):
    recalled_lot_id: str
    one_up_source_lot_ids: List[str]
    one_down_finished_lot_ids: List[str]
    exposure_variant: str
    exposure_qty: float
