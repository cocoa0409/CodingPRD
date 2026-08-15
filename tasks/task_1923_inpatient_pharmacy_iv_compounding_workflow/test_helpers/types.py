"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PHARMACY_ADMIN = "PharmacyAdmin"
    PRESCRIBER = "Prescriber"
    PHARMACIST = "Pharmacist"
    PHARMACY_TECHNICIAN = "PharmacyTechnician"
    NURSE = "Nurse"
    DIVERSION_OFFICER = "DiversionOfficer"


class StaffRole(str, Enum):
    PRESCRIBER = "PRESCRIBER"
    PHARMACIST = "PHARMACIST"
    TECHNICIAN = "TECHNICIAN"
    NURSE = "NURSE"


# Staff roster enum value -> calling-role header value (PRD §3.1 note).
STAFF_ROLE_TO_USER_ROLE = {
    StaffRole.PRESCRIBER.value: UserRole.PRESCRIBER.value,
    StaffRole.PHARMACIST.value: UserRole.PHARMACIST.value,
    StaffRole.TECHNICIAN.value: UserRole.PHARMACY_TECHNICIAN.value,
    StaffRole.NURSE.value: UserRole.NURSE.value,
}


class Sex(str, Enum):
    M = "M"
    F = "F"


class DrugSchedule(str, Enum):
    NON_CONTROLLED = "NON_CONTROLLED"
    C_II = "C_II"
    C_III = "C_III"
    C_IV = "C_IV"
    C_V = "C_V"


class DrugStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class RenalDosingPolicy(str, Enum):
    IBW = "IBW"
    ABW_WHEN_OBESE = "ABW_WHEN_OBESE"


class IsoClass(str, Enum):
    ISO_5 = "ISO_5"
    ISO_7 = "ISO_7"
    ISO_8 = "ISO_8"


class HoodSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_USE = "IN_USE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Route(str, Enum):
    IV = "IV"
    PO = "PO"
    IM = "IM"


class VerificationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    ON_HOLD = "ON_HOLD"
    DISCONTINUED = "DISCONTINUED"
    SUPERSEDED = "SUPERSEDED"


class FulfillmentStatus(str, Enum):
    NONE = "NONE"
    QUEUED = "QUEUED"
    COMPOUNDING = "COMPOUNDING"
    READY = "READY"
    DISPENSED = "DISPENSED"
    ADMINISTERED = "ADMINISTERED"


class InterventionType(str, Enum):
    DOSE_CLARIFICATION = "DOSE_CLARIFICATION"
    ALLERGY = "ALLERGY"
    RENAL = "RENAL"
    SHORTAGE = "SHORTAGE"
    OTHER = "OTHER"


class UspRiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class BatchStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_PROGRESS = "IN_PROGRESS"
    QA_REVIEW = "QA_REVIEW"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class PreparationStatus(str, Enum):
    PLANNED = "PLANNED"
    COMPOUNDED = "COMPOUNDED"
    QA_PASSED = "QA_PASSED"
    DISPENSED = "DISPENSED"
    CANCELLED = "CANCELLED"
    WASTED = "WASTED"
    EXPIRED = "EXPIRED"


class StorageCondition(str, Enum):
    ROOM = "ROOM"
    REFRIGERATED = "REFRIGERATED"
    FROZEN = "FROZEN"


class PocketStatus(str, Enum):
    ACTIVE = "ACTIVE"
    QUARANTINED = "QUARANTINED"


class InventoryEventType(str, Enum):
    RESTOCK = "RESTOCK"
    DISPENSE = "DISPENSE"
    RETURN = "RETURN"
    WASTE = "WASTE"
    COUNT = "COUNT"
    ADJUSTMENT = "ADJUSTMENT"


class DiscrepancyCaseStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class DiscrepancyResolution(str, Enum):
    FOUND_ERROR = "FOUND_ERROR"
    UNRESOLVED_ESCALATE = "UNRESOLVED_ESCALATE"


class DiversionCaseStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUBSTANTIATED = "SUBSTANTIATED"
    CLOSED_UNSUBSTANTIATED = "CLOSED_UNSUBSTANTIATED"


class DiversionOutcome(str, Enum):
    SUBSTANTIATED = "SUBSTANTIATED"
    CLOSED_UNSUBSTANTIATED = "CLOSED_UNSUBSTANTIATED"


class OpenedVia(str, Enum):
    MANUAL = "MANUAL"
    RISK_SCORE = "RISK_SCORE"
    ESCALATION = "ESCALATION"


class ProtocolStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


# --- Entity TypedDicts ---
# Versioned resources carry id + created_at + updated_at + version (PRD §2.4).
# Append-only records (ClinicalIntervention, InventoryEvent, WasteRecord) carry
# ONLY id + created_at; updated_at and version are absent (PRD §2.4, §3.9).


class StaffMember(TypedDict, total=False):
    id: str
    full_name: str
    staff_role: str
    hd_compounding_certified: bool
    hd_cert_expires_at: Optional[str]
    active: bool
    created_at: str
    updated_at: str
    version: int


class PatientProfile(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    sex: str
    height_cm: float
    weight_kg: float
    scr_mg_dl: float
    allergy_drug_product_ids: list
    age_years: int
    bmi: float
    ibw_kg: float
    abw_kg: Optional[float]
    crcl_ibw_ml_min: float
    crcl_abw_ml_min: Optional[float]
    created_at: str
    updated_at: str
    version: int


class DrugProduct(TypedDict, total=False):
    id: str
    name: str
    schedule: str
    is_hazardous: bool
    concentration_mg_per_ml: float
    vial_size_ml: float
    has_stability_data: bool
    stability_hours_room: Optional[int]
    stability_hours_refrigerated: Optional[int]
    stability_hours_frozen: Optional[int]
    renal_dosing_policy: str
    in_shortage: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CompoundingHood(TypedDict, total=False):
    id: str
    name: str
    iso_class: str
    is_hd_rated: bool
    created_at: str
    updated_at: str
    version: int


class HoodSession(TypedDict, total=False):
    id: str
    hood_id: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CoverageShift(TypedDict, total=False):
    id: str
    staff_id: str
    zone: str
    start_at: str
    end_at: str
    created_at: str
    updated_at: str
    version: int


class MedicationOrder(TypedDict, total=False):
    id: str
    patient_id: str
    prescriber_staff_id: str
    drug_product_id: str
    substituted_by_protocol_id: Optional[str]
    route: str
    ordered_dose_mg: float
    frequency_per_day: int
    duration_days: int
    verification_status: str
    fulfillment_status: str
    substitution_pending: bool
    crcl_used_ml_min: Optional[float]
    renal_adjusted_dose_mg: Optional[float]
    final_dose_ml: Optional[float]
    discontinue_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClinicalIntervention(TypedDict, total=False):
    # Append-only: id + created_at only among common fields (PRD §2.4).
    id: str
    order_id: str
    pharmacist_staff_id: str
    intervention_type: str
    note: str
    placed_on_hold: bool
    created_at: str


class CompoundingBatch(TypedDict, total=False):
    id: str
    hood_session_id: str
    compounder_staff_id: str
    qa_pharmacist_staff_id: Optional[str]
    usp_risk_level: str
    documents_stability_source: bool
    status: str
    rework_count: int
    demand_ml: float
    vials_used: int
    total_drawn_ml: float
    delivered_ml: float
    waste_ml: float
    overage_pct: float
    created_at: str
    updated_at: str
    version: int


class CompoundedPreparation(TypedDict, total=False):
    id: str
    batch_id: str
    order_id: str
    drug_product_id: str
    status: str
    prepared_volume_ml: Optional[float]
    storage_condition: Optional[str]
    bud_expiry: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ADCStation(TypedDict, total=False):
    id: str
    name: str
    zone: str
    created_at: str
    updated_at: str
    version: int


class ADCPocket(TypedDict, total=False):
    id: str
    station_id: str
    drug_product_id: str
    max_units: int
    on_hand_units: int
    status: str
    pick_blocked: bool
    created_at: str
    updated_at: str
    version: int


class InventoryEvent(TypedDict, total=False):
    # Append-only: id + created_at only among common fields (PRD §2.4).
    id: str
    pocket_id: str
    order_id: Optional[str]
    recorded_by_staff_id: str
    witness_staff_id: Optional[str]
    event_type: str
    units_delta: int
    observed_count_units: Optional[int]
    expected_on_hand_after: int
    occurred_at: str
    created_at: str


class DiscrepancyCase(TypedDict, total=False):
    id: str
    pocket_id: str
    variance_units: int
    status: str
    resolution: Optional[str]
    adjustment_units: Optional[int]
    resolved_by_staff_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DiversionCase(TypedDict, total=False):
    id: str
    station_id: str
    subject_staff_id: str
    source_discrepancy_case_id: Optional[str]
    reason: str
    status: str
    outcome_note: Optional[str]
    opened_via: str
    created_at: str
    updated_at: str
    version: int


class SubstitutionProtocol(TypedDict, total=False):
    id: str
    shortage_drug_product_id: str
    substitute_drug_product_id: str
    conversion_factor: float
    min_dose_mg: float
    max_dose_mg: float
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WasteRecord(TypedDict, total=False):
    # Append-only: id + created_at only among common fields (PRD §2.4, §3.9).
    id: str
    batch_id: Optional[str]
    pocket_id: Optional[str]
    volume_ml: Optional[float]
    units: Optional[int]
    reason: str
    recorded_by_staff_id: str
    witness_staff_id: Optional[str]
    created_at: str
