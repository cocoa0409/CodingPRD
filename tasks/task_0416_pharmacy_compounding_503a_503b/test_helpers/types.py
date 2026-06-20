"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Pharmacy Compounding (503A/503B) PRD. Entities that carry the
standard system-managed fields (id, created_at, updated_at, version) are modeled
with those fields; the immutable EnvironmentalLog reading carries only id and
created_at (no updated_at, no version) per PRD §2.4.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    COMPOUNDING_PHARMACIST = "CompoundingPharmacist"
    QUALITY_ASSURANCE_PHARMACIST = "QualityAssurancePharmacist"
    DISPENSING_PHARMACIST = "DispensingPharmacist"


class RegistrationType(str, Enum):
    R_503A = "503A"
    R_503B = "503B"


class DosageForm(str, Enum):
    ORAL_SOLID = "ORAL_SOLID"
    ORAL_LIQUID = "ORAL_LIQUID"
    TOPICAL = "TOPICAL"
    NONSTERILE_OTHER = "NONSTERILE_OTHER"
    STERILE_AQUEOUS = "STERILE_AQUEOUS"
    STERILE_NONAQUEOUS = "STERILE_NONAQUEOUS"


class MfrStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class LotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    QUARANTINED = "QUARANTINED"
    EXPIRED = "EXPIRED"
    DISCARDED = "DISCARDED"


class UspChapter(str, Enum):
    USP_795 = "USP_795"
    USP_797 = "USP_797"


class ReadingType(str, Enum):
    ISO_PARTICLE_COUNT = "ISO_PARTICLE_COUNT"
    VIABLE_AIR_CFU = "VIABLE_AIR_CFU"
    SURFACE_CFU = "SURFACE_CFU"
    ROOM_TEMP_C = "ROOM_TEMP_C"
    ROOM_HUMIDITY_PCT = "ROOM_HUMIDITY_PCT"


class PrescriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class BatchPurpose(str, Enum):
    PRESCRIPTION = "PRESCRIPTION"
    OFFICE_USE = "OFFICE_USE"


class BatchStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_PROCESS = "IN_PROCESS"
    COMPILED = "COMPILED"
    QUARANTINED = "QUARANTINED"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"
    RECALLED = "RECALLED"


class QcTestType(str, Enum):
    POTENCY_ASSAY = "POTENCY_ASSAY"
    STERILITY = "STERILITY"
    ENDOTOXIN = "ENDOTOXIN"
    VISUAL_INSPECTION = "VISUAL_INSPECTION"


class QcResult(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"


class QcStatus(str, Enum):
    AWAITING_QC = "AWAITING_QC"
    QC_RELEASED = "QC_RELEASED"
    QC_REJECTED = "QC_REJECTED"


class DispenseStatus(str, Enum):
    IN_INVENTORY = "IN_INVENTORY"
    DISPENSED = "DISPENSED"
    RECALLED = "RECALLED"


class RecallReason(str, Enum):
    STERILITY_FAILURE = "STERILITY_FAILURE"
    POTENCY_OOS = "POTENCY_OOS"
    ENDOTOXIN_OOS = "ENDOTOXIN_OOS"
    ENVIRONMENTAL_EXCURSION = "ENVIRONMENTAL_EXCURSION"
    LABELING_ERROR = "LABELING_ERROR"


class RecallClassification(str, Enum):
    CLASS_I = "CLASS_I"
    CLASS_II = "CLASS_II"
    CLASS_III = "CLASS_III"


class RecallStatus(str, Enum):
    INITIATED = "INITIATED"
    IN_PROGRESS = "IN_PROGRESS"
    RECONCILED = "RECONCILED"
    CLOSED = "CLOSED"


# --- Entity TypedDicts (common_fields: true → id, created_at, updated_at, version) ---

class Facility(TypedDict):
    id: str
    name: str
    registration_type: str
    state_code: str
    current_utc: str
    created_at: str
    updated_at: str
    version: int


class MasterFormulationRecord(TypedDict):
    id: str
    facility_id: str
    name: str
    dosage_form: str
    is_sterile: bool
    default_bud_days_nonsterile: int
    theoretical_yield_units: int
    anticipatory_window_days: int
    anticipatory_max_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IngredientLot(TypedDict):
    id: str
    facility_id: str
    parent_lot_id: Optional[str]
    component_name: str
    lot_number: str
    labeled_potency_pct: float
    endotoxin_eu_per_mg: float
    initial_grams: float
    remaining_grams: float
    expiration_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Prescription(TypedDict):
    id: str
    facility_id: str
    master_formulation_record_id: str
    patient_name: str
    prescriber_npi: str
    units_prescribed: int
    units_dispensed: int
    written_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CompoundingBatch(TypedDict):
    id: str
    facility_id: str
    master_formulation_record_id: str
    purpose: str
    prescription_id: Optional[str]
    compiled_by_user_id: Optional[str]
    released_by_user_id: Optional[str]
    theoretical_yield_units: int
    actual_yield_units: Optional[int]
    yield_variance_pct: Optional[float]
    released_at_utc: Optional[str]
    assigned_bud_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BatchIngredientUsage(TypedDict):
    id: str
    compounding_batch_id: str
    ingredient_lot_id: str
    grams_used: float
    potency_adjusted_grams: float
    created_at: str
    updated_at: str
    version: int


class QualityControlTest(TypedDict):
    id: str
    compounding_batch_id: str
    test_type: str
    measured_value: Optional[float]
    lower_limit: Optional[float]
    upper_limit: Optional[float]
    result: str
    created_at: str
    updated_at: str
    version: int


class FinishedPreparation(TypedDict):
    id: str
    compounding_batch_id: str
    facility_id: str
    unit_serial: str
    label_text: str
    beyond_use_utc: str
    qc_status: str
    dispense_status: str
    created_at: str
    updated_at: str
    version: int


class Dispense(TypedDict):
    id: str
    facility_id: str
    finished_preparation_id: str
    prescription_id: Optional[str]
    office_account_name: Optional[str]
    dispensed_utc: str
    created_at: str
    updated_at: str
    version: int


class AnticipatoryLimitLedger(TypedDict):
    id: str
    master_formulation_record_id: str
    window_start_utc: str
    consumed_units: int
    remaining_units: int
    created_at: str
    updated_at: str
    version: int


class Recall(TypedDict):
    id: str
    facility_id: str
    compounding_batch_id: str
    reason: str
    classification: str
    units_in_scope: int
    units_reconciled: int
    status: str
    created_at: str
    updated_at: str
    version: int


# --- common_fields: false → immutable monitoring reading (id + created_at only) ---

class EnvironmentalLog(TypedDict):
    id: str
    facility_id: str
    usp_chapter: str
    reading_type: str
    measured_value: float
    action_limit: float
    in_spec: bool
    reading_utc: str
    created_at: str
