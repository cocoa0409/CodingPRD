"""Domain types: entity TypedDicts, status enums, role enum.

All entities in the Oncology Infusion API carry the common quartet
(id, created_at, updated_at, version) per PRD §2.4 — there are no
append-only resources here.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum ---------------------------------------------------------------

class UserRole(str, Enum):
    PHARMACIST = "Pharmacist"
    NURSE = "Nurse"
    PRIOR_AUTH_COORDINATOR = "PriorAuthCoordinator"


# --- Status enums ------------------------------------------------------------

class PatientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DECEASED = "DECEASED"


class RegimenProtocolStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class ChairStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class PriorAuthorizationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXHAUSTED = "EXHAUSTED"


class TreatmentCycleStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


class DrugOrderStatus(str, Enum):
    ORDERED = "ORDERED"
    PREPARED = "PREPARED"
    VERIFIED = "VERIFIED"
    ADMINISTERED = "ADMINISTERED"
    CANCELLED = "CANCELLED"


class InfusionAppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# --- Enumerated value sets used in payloads ----------------------------------

class OrderSetItemRole(str, Enum):
    CHEMO = "CHEMO"
    PREMED = "PREMED"


class DosingMethod(str, Enum):
    BSA = "BSA"
    AUC = "AUC"
    FLAT = "FLAT"


# --- Entity TypedDicts -------------------------------------------------------

class Patient(TypedDict):
    id: str
    mrn: str
    full_name: str
    height_cm: float
    weight_kg: float
    gfr_ml_min: float
    bsa_m2: float
    status: str
    created_at: str
    updated_at: str
    version: int


class RegimenProtocol(TypedDict):
    id: str
    code: str
    name: str
    cycle_length_days: int
    total_cycles: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OrderSetItem(TypedDict):
    id: str
    regimen_protocol_id: str
    drug_name: str
    role: str
    dosing_method: str
    dose_per_m2: Optional[float]
    target_auc: Optional[float]
    flat_dose_mg: Optional[float]
    vial_size_mg: float
    day_offset: int
    sequence_index: int
    created_at: str
    updated_at: str
    version: int


class Chair(TypedDict):
    id: str
    label: str
    is_isolation: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Nurse(TypedDict):
    id: str
    full_name: str
    is_chemo_certified: bool
    max_acuity_load: int
    created_at: str
    updated_at: str
    version: int


class PriorAuthorization(TypedDict):
    id: str
    patient_id: str
    drug_name: str
    payer: str
    authorized_units_mg: Optional[float]
    status: str
    consumed_units_mg: float
    created_at: str
    updated_at: str
    version: int


class TreatmentCycle(TypedDict):
    id: str
    patient_id: str
    regimen_protocol_id: str
    treatment_start_date: str
    current_cycle_number: int
    status: str
    bsa_snapshot_m2: Optional[float]
    gfr_snapshot_ml_min: Optional[float]
    created_at: str
    updated_at: str
    version: int


class DrugOrder(TypedDict):
    id: str
    treatment_cycle_id: str
    order_set_item_id: str
    prior_authorization_id: Optional[str]
    dose_reduction_pct: float
    ordered_dose_mg: float
    vials_drawn: int
    supplied_mg: float
    waste_mg: float
    jw_modifier: bool
    administered_dose_mg: float
    prepared_by_nurse_id: Optional[str]
    verified_by_nurse_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InfusionAppointment(TypedDict):
    id: str
    treatment_cycle_id: str
    chair_id: str
    nurse_id: str
    start_at: str
    end_at: str
    acuity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ToxicityEvent(TypedDict):
    id: str
    treatment_cycle_id: str
    drug_order_id: Optional[str]
    ctcae_grade: int
    description: str
    triggered_hold: bool
    created_at: str
    updated_at: str
    version: int
