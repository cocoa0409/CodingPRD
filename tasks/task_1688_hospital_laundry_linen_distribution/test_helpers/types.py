"""Domain types: entity shapes, status enums, and the role enum.

All resources carry the standard system-managed fields from PRD 2.4
(id, created_at, updated_at, version).
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    LINEN_MANAGER = "LinenManager"
    EVS_OPERATOR = "EVSOperator"
    LAUNDRY_VENDOR = "LaundryVendor"
    UNIT_CLERK = "UnitClerk"
    INFECTION_CONTROL_OFFICER = "InfectionControlOfficer"


class SurgePosture(str, Enum):
    NORMAL = "NORMAL"
    SURGE = "SURGE"


class UnitTier(str, Enum):
    CRITICAL = "CRITICAL"
    STANDARD = "STANDARD"


class QualityFlag(str, Enum):
    CLEAR = "CLEAR"
    WATCH = "WATCH"


class LinenCategory(str, Enum):
    FLATWORK = "FLATWORK"
    TERRY = "TERRY"
    PATIENT_APPAREL = "PATIENT_APPAREL"
    ISOLATION = "ISOLATION"


class StockPosture(str, Enum):
    SUFFICIENT = "SUFFICIENT"
    LOW = "LOW"
    CRITICAL = "CRITICAL"


class ShrinkageStatus(str, Enum):
    NORMAL = "NORMAL"
    INVESTIGATION = "INVESTIGATION"


class CartCycle(str, Enum):
    DAILY = "DAILY"
    TWICE_DAILY = "TWICE_DAILY"
    WEEKLY = "WEEKLY"


class CartRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    DISPUTED = "DISPUTED"
    RECOUNTED = "RECOUNTED"
    RECONCILED = "RECONCILED"


class ManifestStatus(str, Enum):
    DISPATCHED = "DISPATCHED"
    RETURNED = "RETURNED"
    RECONCILED = "RECONCILED"


class InvoiceStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"


class ComplaintType(str, Enum):
    STAINS = "STAINS"
    TEARS = "TEARS"
    FOREIGN_OBJECT = "FOREIGN_OBJECT"
    ODOR = "ODOR"
    ISOLATION_BREACH = "ISOLATION_BREACH"


class ComplaintStatus(str, Enum):
    OPEN = "OPEN"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    RESCINDED = "RESCINDED"
    RESOLVED = "RESOLVED"


class SurgeSeverity(str, Enum):
    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"


class SurgeStatus(str, Enum):
    DECLARED = "DECLARED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class Facility(TypedDict, total=False):
    id: str
    name: str
    rate_per_lb_cents: int
    isolation_surcharge_pct: float
    monthly_cap_cents: Optional[int]
    surge_posture: str
    credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict, total=False):
    id: str
    facility_id: str
    name: str
    unit_tier: str
    quality_flag: str
    created_at: str
    updated_at: str
    version: int


class LinenStock(TypedDict, total=False):
    id: str
    facility_id: str
    sku: str
    display_name: str
    category: str
    piece_weight_lbs: float
    unit_cost_cents: int
    max_wash_cycles: int
    reorder_point_pieces: int
    opening_pieces: int
    opening_reserve_pieces: int
    in_circulation: int
    in_wash: int
    reserve_pieces: int
    retired_pieces: int
    lost_pieces: int
    wash_cycles_completed: int
    posture: str
    shrinkage_status: str
    created_at: str
    updated_at: str
    version: int


class ParLevel(TypedDict, total=False):
    id: str
    unit_id: str
    stock_id: str
    base_par_quantity: int
    cart_cycle: str
    on_hand: int
    effective_par: int
    created_at: str
    updated_at: str
    version: int


class SoiledLine(TypedDict):
    stock_id: str
    pieces: int


class CartExchangeRun(TypedDict, total=False):
    id: str
    unit_id: str
    manifest_id: Optional[str]
    scheduled_start: str
    scheduled_end: str
    status: str
    soiled_lines: List[dict]
    restock_lines: List[dict]
    shortage_flag: bool
    storage_attested: bool
    completed_at: Optional[str]
    late_delivery: bool
    created_at: str
    updated_at: str
    version: int


class ManifestLine(TypedDict):
    stock_id: str
    weight_lbs: float
    isolation_flag: bool


class ReturnedLine(TypedDict):
    stock_id: str
    pieces: int
    condemned_pieces: int


class SoiledManifest(TypedDict, total=False):
    id: str
    facility_id: str
    invoice_id: Optional[str]
    lines: List[dict]
    isolation_protocol_ack: bool
    returned_lines: List[dict]
    status: str
    recorded_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class VendorInvoice(TypedDict, total=False):
    id: str
    facility_id: str
    period_start: str
    period_end: str
    period_adjusted_patient_days: int
    status: str
    provisional_total_cents: int
    final_total_cents: Optional[int]
    credit_total_cents: int
    billed_total_cents: Optional[int]
    cost_per_apd_cents: Optional[float]
    created_by_user_id: str
    finalized_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict, total=False):
    id: str
    unit_id: str
    manifest_id: str
    stock_id: str
    complaint_type: str
    pieces_affected: int
    status: str
    credit_cents: int
    routed_invoice_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SurgeEvent(TypedDict, total=False):
    id: str
    facility_id: str
    severity: str
    par_multiplier: float
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
