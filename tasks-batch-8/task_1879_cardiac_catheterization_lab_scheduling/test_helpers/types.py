"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1 — five roles, spelled exactly)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    CATH_LAB_SCHEDULER = "CathLabScheduler"
    INTERVENTIONAL_CARDIOLOGIST = "InterventionalCardiologist"
    CATH_LAB_TECHNOLOGIST = "CathLabTechnologist"
    RECOVERY_NURSE_MANAGER = "RecoveryNurseManager"
    REGISTRY_COORDINATOR = "RegistryCoordinator"


# ---------------------------------------------------------------------------
# Status / field enums
# ---------------------------------------------------------------------------

class RoomStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class EquipmentCode(str, Enum):
    BIPLANE_ANGIOGRAPHY = "BIPLANE_ANGIOGRAPHY"
    IVUS = "IVUS"
    OCT = "OCT"
    FFR = "FFR"
    ROTATIONAL_ATHERECTOMY = "ROTATIONAL_ATHERECTOMY"
    IABP = "IABP"
    MECHANICAL_SUPPORT = "MECHANICAL_SUPPORT"


class StaffRole(str, Enum):
    INTERVENTIONAL_CARDIOLOGIST = "INTERVENTIONAL_CARDIOLOGIST"
    SCRUB_TECHNOLOGIST = "SCRUB_TECHNOLOGIST"
    CIRCULATING_NURSE = "CIRCULATING_NURSE"


class ProcedureType(str, Enum):
    DIAGNOSTIC_CATHETERIZATION = "DIAGNOSTIC_CATHETERIZATION"
    PCI = "PCI"
    STEMI_PCI = "STEMI_PCI"
    DEVICE_IMPLANT = "DEVICE_IMPLANT"
    EP_STUDY = "EP_STUDY"


class CasePriority(str, Enum):
    ELECTIVE = "ELECTIVE"
    URGENT = "URGENT"
    STEMI = "STEMI"


class CaseStatus(str, Enum):
    POSTED = "POSTED"
    SCHEDULED = "SCHEDULED"
    BUMPED = "BUMPED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RoleInCase(str, Enum):
    PRIMARY_OPERATOR = "PRIMARY_OPERATOR"
    SCRUB = "SCRUB"
    CIRCULATOR = "CIRCULATOR"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    RELEASED = "RELEASED"


class DeviceType(str, Enum):
    STENT_DES = "STENT_DES"
    STENT_BMS = "STENT_BMS"
    PACEMAKER_LEAD = "PACEMAKER_LEAD"
    ICD_LEAD = "ICD_LEAD"
    CLOSURE_DEVICE = "CLOSURE_DEVICE"


class DeviceOwnership(str, Enum):
    OWNED = "OWNED"
    CONSIGNMENT = "CONSIGNMENT"


class DeviceLotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LOW_STOCK = "LOW_STOCK"
    DEPLETED = "DEPLETED"


class DeviceUsageStatus(str, Enum):
    RESERVED = "RESERVED"
    IMPLANTED = "IMPLANTED"
    RELEASED = "RELEASED"


class DoseRecordType(str, Enum):
    CONTRAST = "CONTRAST"
    RADIATION = "RADIATION"


class DoseRecordStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class BedStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class AucStatus(str, Enum):
    NOT_DOCUMENTED = "NOT_DOCUMENTED"
    DOCUMENTED = "DOCUMENTED"


class AucScore(str, Enum):
    APPROPRIATE = "APPROPRIATE"
    MAY_BE_APPROPRIATE = "MAY_BE_APPROPRIATE"
    RARELY_APPROPRIATE = "RARELY_APPROPRIATE"


class RegistryName(str, Enum):
    NCDR_CATHPCI = "NCDR_CATHPCI"
    NCDR_ICD = "NCDR_ICD"
    NCDR_EP = "NCDR_EP"


class SubmissionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class SubmissionOutcome(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — all nine resource types carry the common system-managed
# properties id / created_at / updated_at / version (PRD §2.4).
# ---------------------------------------------------------------------------

class CathLabRoom(TypedDict, total=False):
    id: str
    room_name: str
    equipment_profile: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict, total=False):
    id: str
    full_name: str
    staff_role: str
    credentials: List[str]
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class CathCase(TypedDict, total=False):
    id: str
    patient_mrn: str
    procedure_type: str
    priority: str
    performing_physician_id: str
    weight_kg: float
    serum_creatinine: float
    equipment_needs: List[str]
    lab_id: Optional[str]
    scheduled_start: Optional[str]
    scheduled_end: Optional[str]
    actual_start: Optional[str]
    actual_end: Optional[str]
    contrast_limit_ml: float
    cumulative_contrast_ml: float
    cumulative_radiation_mgy: float
    radiation_alert: bool
    bump_count: int
    auc_status: str
    auc_score: Optional[str]
    auc_criterion_code: Optional[str]
    ordering_physician_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class StaffAssignment(TypedDict, total=False):
    id: str
    case_id: str
    staff_id: str
    role_in_case: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DeviceLot(TypedDict, total=False):
    id: str
    device_type: str
    manufacturer: str
    model_number: str
    lot_number: str
    ownership: str
    quantity_on_hand: int
    allocated_units: int
    available_units: int
    reorder_threshold: int
    expiration_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DeviceUsage(TypedDict, total=False):
    id: str
    case_id: str
    lot_id: str
    quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DoseRecord(TypedDict, total=False):
    id: str
    case_id: str
    record_type: str
    contrast_ml: Optional[float]
    fluoroscopy_mgy: Optional[float]
    cine_mgy: Optional[float]
    record_total_mgy: float
    status: str
    created_at: str
    updated_at: str
    version: int


class RecoveryBed(TypedDict, total=False):
    id: str
    bed_label: str
    status: str
    held_case_id: Optional[str]
    window_start: Optional[str]
    window_end: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RegistrySubmission(TypedDict, total=False):
    id: str
    case_id: str
    registry_name: str
    completeness_pct: float
    submitted_at: Optional[str]
    decided_at: Optional[str]
    rejection_reason: Optional[str]
    correction_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
