"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4: PlantingBatch, StorageBin, LogisticsLeg, InspectionReport, Distributor,
RecallOrder carry the standard {id, created_at, updated_at, version} block.
PesticideRegistry, AgrochemicalApplication, HarvestRecord, SensorReading, QRCode,
AuditLog are append-only/registry-style and carry only id and created_at.
"""
from enum import Enum
from typing import TypedDict, List, Optional, Any


# ------------------------------- Role enum --------------------------------

class UserRole(str, Enum):
    GROWER = "Grower"
    INSPECTOR = "Inspector"
    REGULATORY_OFFICER = "RegulatoryOfficer"
    LOGISTICS_OPERATOR = "LogisticsOperator"
    DISTRIBUTOR = "Distributor"
    CONSUMER = "Consumer"


# ------------------------------ Status enums ------------------------------

class PlantingBatchStatus(str, Enum):
    REGISTERED = "REGISTERED"
    GROWING = "GROWING"
    HARVESTED = "HARVESTED"
    INSPECTED_PASS = "INSPECTED_PASS"
    INSPECTED_FAIL = "INSPECTED_FAIL"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    RECALLED = "RECALLED"
    DISPOSED = "DISPOSED"


class PlantingBatchPosture(str, Enum):
    CLEAN = "CLEAN"
    FLAGGED = "FLAGGED"
    BLOCKED = "BLOCKED"


class PlantingBatchRecallStatus(str, Enum):
    NONE = "NONE"
    ACTIVE_RECALL = "ACTIVE_RECALL"
    COMPLETED = "COMPLETED"


class InspectionReportStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    REVOKED = "REVOKED"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    PENDING = "PENDING"


class TestItem(str, Enum):
    PESTICIDE_RESIDUE = "PESTICIDE_RESIDUE"
    HEAVY_METALS = "HEAVY_METALS"
    MICROORGANISMS = "MICROORGANISMS"


class SamplingRule(str, Enum):
    RANDOM_5PCT = "RANDOM_5PCT"
    FIXED_3KG = "FIXED_3KG"
    FULL_LOT = "FULL_LOT"


class QualityGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    REJECT = "REJECT"


class StorageBinStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    FULL = "FULL"
    QUARANTINE = "QUARANTINE"


class LogisticsLegStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_TRANSIT = "IN_TRANSIT"
    HANDED_OVER = "HANDED_OVER"
    ABNORMAL = "ABNORMAL"


class RecallOrderStatus(str, Enum):
    INITIATED = "INITIATED"
    NOTIFIED = "NOTIFIED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RecallClass(str, Enum):
    CLASS_I = "CLASS_I"
    CLASS_II = "CLASS_II"
    CLASS_III = "CLASS_III"


class RecallReasonCode(str, Enum):
    INSPECTION_FAIL = "INSPECTION_FAIL"
    COLD_CHAIN_BREACH = "COLD_CHAIN_BREACH"
    PROHIBITED_SUBSTANCE = "PROHIBITED_SUBSTANCE"
    CONSUMER_COMPLAINT = "CONSUMER_COMPLAINT"


class RegistryCategory(str, Enum):
    PESTICIDE = "PESTICIDE"
    FERTILIZER = "FERTILIZER"


class DistributorTier(str, Enum):
    WHOLESALE = "WHOLESALE"
    RETAIL = "RETAIL"


class AuditAction(str, Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    STATE_TRANSITION = "STATE_TRANSITION"
    RECALL_INITIATE = "RECALL_INITIATE"
    RECALL_NOTIFY = "RECALL_NOTIFY"
    RECALL_DISPOSE = "RECALL_DISPOSE"
    RECALL_COMPLETE = "RECALL_COMPLETE"


# ----------------------------- Entity TypedDicts --------------------------
# Append-only / registry entities (PRD §2.4): only id + created_at.

class PesticideRegistry(TypedDict, total=False):
    id: str
    created_at: str
    registration_no: str
    product_name: str
    category: str
    withdrawal_period_days: int
    max_dosage_per_hectare_g: float
    prohibited: bool
    prohibited_since: Optional[str]


class AgrochemicalApplication(TypedDict, total=False):
    id: str
    created_at: str
    planting_batch_id: str
    registration_no: str
    application_date: str
    dosage_g_per_hectare: float
    applied_by_user_id: str
    withdrawal_end_date: Optional[str]


class HarvestRecord(TypedDict, total=False):
    id: str
    created_at: str
    planting_batch_id: str
    harvest_date: str
    quantity_kg: float
    quality_grade: str
    packaging_spec: str
    storage_bin_id: str


class SensorReading(TypedDict, total=False):
    id: str
    created_at: str
    logistics_leg_id: str
    device_id: str
    idempotency_key: str
    reading_at: str
    temperature_c: float
    out_of_range: bool


class QRCode(TypedDict, total=False):
    id: str
    created_at: str
    planting_batch_id: str
    harvest_record_id: str
    qr_code_value: str
    anti_counterfeit_token: str
    scan_count: int
    revoked: bool


class AuditLog(TypedDict, total=False):
    id: str
    created_at: str
    actor_user_id: str
    actor_role: str
    entity_type: str
    entity_id: str
    action: str
    before_state: Optional[str]
    after_state: Optional[str]
    change_summary: dict


# Common-fields entities (PRD §2.4): id + created_at + updated_at + version.

class PlantingBatch(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    batch_code: str
    field_plot_id: str
    plot_area_hectares: float
    crop_variety: str
    planting_date: str
    expected_harvest_start: str
    expected_harvest_end: str
    grower_id: str
    grower_name: str
    status: str
    posture: str
    earliest_legal_harvest_date: Optional[str]
    total_quantity_kg: float
    recall_status: str


class StorageBin(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    bin_code: str
    warehouse_zone: str
    capacity_kg: float
    occupied_kg: float
    status: str


class LogisticsLeg(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    planting_batch_id: str
    leg_index: int
    from_party_id: str
    to_party_id: str
    depart_at: str
    arrive_at: str
    temperature_min_c: float
    temperature_max_c: float
    status: str
    abnormal_segment_count: int
    handover_acknowledged: bool


class InspectionReport(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    planting_batch_id: str
    sampling_rule: str
    test_items: List[str]
    pesticide_residue_mg_per_kg: Optional[float]
    heavy_metals_mg_per_kg: Optional[float]
    microorganism_cfu_per_g: Optional[int]
    status: str
    result: str
    issued_at: Optional[str]
    inspector_id: str


class Distributor(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    contact_email: str
    tier: str
    notification_endpoint: str


class RecallOrder(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    planting_batch_id: str
    recall_class: str
    reason_code: str
    scope_distributor_ids: List[str]
    status: str
    initiated_by_user_id: str
    total_quantity_recalled_kg: float
    total_quantity_disposed_kg: float
    disposal_records: List[dict]
