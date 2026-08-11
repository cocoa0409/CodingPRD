"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class FormulationStatus(str, Enum):
    DRAFT = "DRAFT"
    EFFECTIVE = "EFFECTIVE"
    WITHDRAWN = "WITHDRAWN"


class BatchStatus(str, Enum):
    MIXING = "MIXING"
    MIXED = "MIXED"
    PACKING = "PACKING"
    PACKED = "PACKED"
    EXPIRED = "EXPIRED"
    VOID = "VOID"


class PackagingRunStatus(str, Enum):
    OPEN = "OPEN"
    SEALED = "SEALED"
    HOLD = "HOLD"
    VOID = "VOID"


class LotQaStatus(str, Enum):
    AWAITING_TEST = "AWAITING_TEST"
    TESTING = "TESTING"
    UNDER_REVIEW = "UNDER_REVIEW"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"


class LotHoldStatus(str, Enum):
    CLEAR = "CLEAR"
    QUARANTINE_HOLD = "QUARANTINE_HOLD"


class CureTestStatus(str, Enum):
    RECORDED = "RECORDED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class CureTestMethod(str, Enum):
    QUICK = "QUICK"
    FULL = "FULL"


class FormulationRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    TECH_REVIEW = "TECH_REVIEW"
    NEEDS_INFO = "NEEDS_INFO"
    APPROVED = "APPROVED"
    IN_DEVELOPMENT = "IN_DEVELOPMENT"
    CONVERTED = "CONVERTED"
    DECLINED = "DECLINED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ConsumptionReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SETTLED = "SETTLED"
    DISPUTED = "DISPUTED"
    VOID = "VOID"


class RebateTier(str, Enum):
    NONE = "NONE"
    TIER1 = "TIER1"
    TIER2 = "TIER2"


class ShipmentStatus(str, Enum):
    DRAFT = "DRAFT"
    PLANNED = "PLANNED"
    CONFIRMED = "CONFIRMED"
    DISPATCHED = "DISPATCHED"
    EXCEPTION = "EXCEPTION"
    CANCELLED = "CANCELLED"


class ShipmentKind(str, Enum):
    SALE = "SALE"
    CONSIGNMENT = "CONSIGNMENT"
    CONSIGNMENT_REPLENISHMENT = "CONSIGNMENT_REPLENISHMENT"


class TransportMode(str, Enum):
    ROAD = "ROAD"
    AIR = "AIR"
    SEA = "SEA"


class PackFormat(str, Enum):
    CARTRIDGE = "CARTRIDGE"
    PAIL = "PAIL"
    DRUM = "DRUM"


class HazmatClass(str, Enum):
    NON_REGULATED = "NON_REGULATED"
    UN1133_CLASS3_PG_III = "UN1133_CLASS3_PG_III"
    UN1133_CLASS3_PG_II = "UN1133_CLASS3_PG_II"


class ChemistryFamily(str, Enum):
    EPOXY = "EPOXY"
    POLYURETHANE = "POLYURETHANE"
    SILICONE = "SILICONE"
    ACRYLIC = "ACRYLIC"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PLANT_MANAGER = "PlantManager"
    BATCH_OPERATOR = "BatchOperator"
    QA_TECHNICIAN = "QATechnician"
    QA_MANAGER = "QAManager"
    TECH_SERVICE_ENGINEER = "TechServiceEngineer"
    COMMERCIAL_MANAGER = "CommercialManager"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    DISTRIBUTOR = "Distributor"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields entities carry id + created_at +
# updated_at + version; the append-only exposure log carries only
# id + created_at).
# ---------------------------------------------------------------------------

class Formulation(TypedDict, total=False):
    id: str
    code: str
    name: str
    chemistry_family: str
    moisture_sensitive: bool
    solvent_content_pct: float
    flash_point_c: float
    pot_life_minutes: int
    shelf_life_months: int
    spec_min_bond_strength_mpa: float
    min_remaining_shelf_life_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MixingVessel(TypedDict, total=False):
    id: str
    vessel_code: str
    capacity_liters: int
    created_at: str
    updated_at: str
    version: int


class DryRoom(TypedDict, total=False):
    id: str
    room_code: str
    max_concurrent_runs: int
    humidity_limit_pct: float
    created_at: str
    updated_at: str
    version: int


class ProductionBatch(TypedDict, total=False):
    id: str
    formulation_id: str
    vessel_id: str
    mix_start_at: str
    mix_end_at: str
    batch_volume_ml: int
    mixed_at: Optional[str]
    pot_life_deadline: Optional[str]
    remaining_bulk_volume_ml: int
    written_off_volume_ml: int
    production_lot_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PackagingRun(TypedDict, total=False):
    id: str
    batch_id: str
    dry_room_id: Optional[str]
    pack_format: str
    unit_volume_ml: int
    planned_units: int
    planned_start_at: str
    planned_end_at: str
    per_unit_fill_ml: Optional[int]
    units_produced: Optional[int]
    total_filled_ml: Optional[int]
    held_from: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MoistureExposureEvent(TypedDict, total=False):
    # Append-only log record: id + created_at only; NO updated_at, NO version.
    id: str
    created_at: str
    packaging_run_id: str
    exposure_minutes: int
    occurred_at: str
    note: Optional[str]


class ProductionLot(TypedDict, total=False):
    id: str
    batch_id: str
    formulation_id: str
    lot_number: str
    manufacture_date: Optional[str]
    expiry_date: Optional[str]
    pack_format: Optional[str]
    unit_volume_ml: Optional[int]
    units_filled: int
    units_quarantined: int
    units_condemned: int
    units_shipped: int
    retest_count: int
    released_by: Optional[str]
    qa_status: str
    hold_status: str
    created_at: str
    updated_at: str
    version: int


class CureTest(TypedDict, total=False):
    id: str
    lot_id: str
    method: str
    specimens: List[float]
    technician_id: str
    evaluated_value_mpa: Optional[float]
    assessment_pass: Optional[bool]
    status: str
    created_at: str
    updated_at: str
    version: int


class FormulationRequest(TypedDict, total=False):
    id: str
    distributor_id: str
    contact_name: str
    target_substrate: str
    required_bond_strength_mpa: float
    application_notes: str
    info_request_note: Optional[str]
    response_note: Optional[str]
    decision_outcome: Optional[str]
    resulting_formulation_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Distributor(TypedDict, total=False):
    id: str
    name: str
    credit_limit_cents: int
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class ConsignmentAgreement(TypedDict, total=False):
    id: str
    distributor_id: str
    formulation_id: str
    unit_price_cents: int
    max_consigned_value_cents: int
    reorder_threshold_units: int
    reorder_qty_units: int
    min_remaining_shelf_life_days: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsignmentStock(TypedDict, total=False):
    id: str
    agreement_id: str
    lot_id: str
    qty_shipped: int
    qty_consumed: int
    qty_returned: int
    qty_on_hand: int
    row_key: str
    created_at: str
    updated_at: str
    version: int


class ConsumptionReport(TypedDict, total=False):
    id: str
    agreement_id: str
    period: str
    consumed_units: int
    provisional_settlement_cents: Optional[int]
    rebate_tier: Optional[str]
    rebate_cents: Optional[int]
    final_net_settlement_cents: Optional[int]
    dispute_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ShipmentLine(TypedDict, total=False):
    lot_id: str
    units: int


class Shipment(TypedDict, total=False):
    id: str
    shipment_kind: str
    distributor_id: str
    agreement_id: Optional[str]
    transport_mode: str
    ship_date: str
    lines: List[Dict[str, Any]]
    hazmat_class: Optional[str]
    auto_replenishment: bool
    proposed_units: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
