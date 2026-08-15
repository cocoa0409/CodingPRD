"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PACKINGHOUSE_ADMIN = "PackinghouseAdmin"
    FIELD_SUPERVISOR = "FieldSupervisor"
    QUALITY_INSPECTOR = "QualityInspector"
    LINE_OPERATOR = "LineOperator"
    POOL_ACCOUNTANT = "PoolAccountant"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    GROWER = "Grower"


class Variety(str, Enum):
    HAMLIN = "HAMLIN"
    VALENCIA = "VALENCIA"
    RED_GRAPEFRUIT = "RED_GRAPEFRUIT"
    TANGERINE = "TANGERINE"


class GrowerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class GroveLifecycle(str, Enum):
    PRODUCTIVE = "PRODUCTIVE"
    RETIRED = "RETIRED"


class QuarantinePosture(str, Enum):
    CLEAR = "CLEAR"
    QUARANTINED = "QUARANTINED"


class MaturityResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class MaturityTestStatus(str, Enum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"


class CrewStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class AssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DeliveryProcessingStatus(str, Enum):
    RECEIVED = "RECEIVED"
    IN_DEGREENING = "IN_DEGREENING"
    READY_TO_SORT = "READY_TO_SORT"
    SORTED = "SORTED"
    CLOSED = "CLOSED"


class DeliveryRegulatoryStatus(str, Enum):
    CLEAR = "CLEAR"
    HELD = "HELD"
    RELEASED = "RELEASED"
    CONDEMNED = "CONDEMNED"


class RoomStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"


class SessionStatus(str, Enum):
    CONDITIONING = "CONDITIONING"
    RELEASED = "RELEASED"
    ABORTED = "ABORTED"


class SortRunStatus(str, Enum):
    OPEN = "OPEN"
    VERIFIED = "VERIFIED"
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class Grade(str, Enum):
    FANCY = "FANCY"
    CHOICE = "CHOICE"
    STANDARD = "STANDARD"
    JUICE = "JUICE"


class ChannelType(str, Enum):
    EXPORT = "EXPORT"
    DOMESTIC_FRESH = "DOMESTIC_FRESH"
    JUICE = "JUICE"


class DestinationMarket(str, Enum):
    JAPAN = "JAPAN"
    EU = "EU"
    KOREA = "KOREA"
    DOMESTIC = "DOMESTIC"
    NONE = "NONE"


class PoolStatus(str, Enum):
    OPEN = "OPEN"
    INTAKE_CLOSED = "INTAKE_CLOSED"
    PRICED = "PRICED"
    SETTLED = "SETTLED"


class RecoupPolicy(str, Enum):
    NEXT_SETTLEMENT_FULL = "NEXT_SETTLEMENT_FULL"
    PRO_RATA_THIRDS = "PRO_RATA_THIRDS"


class AdvanceStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ISSUED = "ISSUED"
    DENIED = "DENIED"
    PARTIALLY_RECOUPED = "PARTIALLY_RECOUPED"
    RECOUPED = "RECOUPED"
    WRITTEN_OFF = "WRITTEN_OFF"


class ServiceType(str, Enum):
    SPRAY = "SPRAY"
    FERTILIZE = "FERTILIZE"
    PRUNE = "PRUNE"
    MOW = "MOW"


class RateTier(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class ServiceOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    INVOICED = "INVOICED"
    CANCELLED = "CANCELLED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    VOID = "VOID"


class QuarantineScope(str, Enum):
    GROVE = "GROVE"
    COUNTY_ZONE = "COUNTY_ZONE"


class PestType(str, Enum):
    CANKER = "CANKER"
    HLB_GREENING = "HLB_GREENING"
    FRUIT_FLY = "FRUIT_FLY"
    BLACK_SPOT = "BLACK_SPOT"


class QuarantineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class ExportLotStatus(str, Enum):
    BUILDING = "BUILDING"
    INSPECTION_READY = "INSPECTION_READY"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"
    SHIPPED = "SHIPPED"
    DIVERTED = "DIVERTED"


class CertificateStatus(str, Enum):
    ISSUED = "ISSUED"
    CONSUMED = "CONSUMED"
    REVOKED = "REVOKED"


# All entities carry the common system fields: id, created_at, updated_at, version.

class Grower(TypedDict, total=False):
    id: str
    grower_code: str
    display_name: str
    status: str
    advance_outstanding_cents: int
    caretaking_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Grove(TypedDict, total=False):
    id: str
    grower_id: str
    block_code: str
    variety: str
    acreage: float
    county_code: str
    caretaking_enrolled: bool
    lifecycle_status: str
    quarantine_posture: str
    created_at: str
    updated_at: str
    version: int


class MaturityTest(TypedDict, total=False):
    id: str
    grove_id: str
    sampled_at: str
    brix: float
    acid_pct: float
    juice_pct: float
    ratio: float
    result: str
    status: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class HarvestCrew(TypedDict, total=False):
    id: str
    crew_code: str
    daily_capacity_boxes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class HarvestAssignment(TypedDict, total=False):
    id: str
    crew_id: str
    grove_id: str
    window_start: str
    window_end: str
    planned_boxes: int
    actual_boxes: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Delivery(TypedDict, total=False):
    id: str
    grove_id: str
    assignment_id: str
    received_at: str
    variety: str
    gross_boxes: int
    tare_boxes: int
    net_boxes: int
    processing_status: str
    regulatory_status: str
    pool_id: Optional[str]
    requires_degreening: bool
    created_at: str
    updated_at: str
    version: int


class DegreeningRoom(TypedDict, total=False):
    id: str
    room_code: str
    capacity_boxes: int
    min_hours: int
    max_hours: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DegreeningSession(TypedDict, total=False):
    id: str
    room_id: str
    delivery_id: str
    boxes: int
    planned_hours: int
    color_add_applied: bool
    started_at: str
    released_at: Optional[str]
    duration_hours: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class SortRun(TypedDict, total=False):
    id: str
    delivery_id: str
    fancy_boxes: int
    choice_boxes: int
    standard_boxes: int
    juice_boxes: int
    cull_boxes: int
    color_score: int
    defect_pct: float
    fresh_eligible: bool
    ge_boxes: float
    proceeds_cents: Optional[int]
    allocation: Optional[List[Dict[str, Any]]]
    created_by: str
    verified_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AllocationChannel(TypedDict, total=False):
    id: str
    channel_code: str
    channel_type: str
    destination_market: str
    variety: str
    week_start: str
    allocation_boxes: int
    price_cents_per_box: int
    priority_rank: int
    accepts_grades: List[str]
    remaining_boxes: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Pool(TypedDict, total=False):
    id: str
    variety: str
    week_start: str
    status: str
    posted_ge_boxes: float
    posted_proceeds_cents: int
    sorted_field_boxes: int
    provisional_price_cents_per_ge_box: int
    final_price_cents_per_ge_box: Optional[int]
    created_at: str
    updated_at: str
    version: int


class AdvancePayment(TypedDict, total=False):
    id: str
    grower_id: str
    pool_id: str
    amount_cents: int
    recoup_policy: str
    status: str
    issued_at: Optional[str]
    recouped_cents: int
    written_off_cents: int
    outstanding_cents: int
    created_at: str
    updated_at: str
    version: int


class CaretakingServiceOrder(TypedDict, total=False):
    id: str
    grove_id: str
    service_type: str
    service_date: str
    acres_treated: float
    chemical_cost_cents: int
    rate_tier: Optional[str]
    line_amount_cents: Optional[int]
    invoice_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CaretakingInvoice(TypedDict, total=False):
    id: str
    grower_id: str
    period_start: str
    period_end: str
    line_order_ids: List[str]
    total_cents: int
    paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class QuarantineOrder(TypedDict, total=False):
    id: str
    scope_type: str
    grove_id: Optional[str]
    county_code: Optional[str]
    pest_type: str
    status: str
    issued_at: str
    issued_by: str
    released_at: Optional[str]
    released_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExportLot(TypedDict, total=False):
    id: str
    destination_market: str
    variety: str
    grade: str
    boxes: int
    source_channel_id: str
    source_grove_id: str
    cold_treatment_hours: int
    pool_id: str
    inspection_requested_by: Optional[str]
    phyto_certificate_id: Optional[str]
    diverted_to: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PhytosanitaryCertificate(TypedDict, total=False):
    id: str
    export_lot_id: str
    certificate_number: str
    inspection_result: str
    issued_at: str
    issued_by: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
