"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    SPONSOR_ADMIN = "SponsorAdmin"
    PHARMACIST = "Pharmacist"
    UNBLINDED_PHARMACIST = "UnblindedPharmacist"
    MONITOR = "Monitor"
    INVESTIGATOR = "Investigator"


class StudyStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class StudyPhase(str, Enum):
    PHASE_I = "PHASE_I"
    PHASE_II = "PHASE_II"
    PHASE_III = "PHASE_III"
    PHASE_IV = "PHASE_IV"


class BlindingModel(str, Enum):
    DOUBLE_BLIND = "DOUBLE_BLIND"
    SINGLE_BLIND = "SINGLE_BLIND"
    OPEN_LABEL = "OPEN_LABEL"


class SiteStatus(str, Enum):
    INITIATED = "INITIATED"
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    CLOSED = "CLOSED"


class LotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"


class KitStatus(str, Enum):
    IN_TRANSIT = "IN_TRANSIT"
    QUARANTINED_RECEIPT = "QUARANTINED_RECEIPT"
    AVAILABLE = "AVAILABLE"
    QUARANTINED_EXCURSION = "QUARANTINED_EXCURSION"
    ALLOCATED = "ALLOCATED"
    DISPENSED = "DISPENSED"
    RETURNED = "RETURNED"
    DESTRUCTION_PENDING = "DESTRUCTION_PENDING"
    EXPIRED = "EXPIRED"
    DESTROYED = "DESTROYED"


class TemperatureSource(str, Enum):
    MANUAL = "MANUAL"
    DATALOGGER = "DATALOGGER"


class ExcursionStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED_ACCEPTABLE = "RESOLVED_ACCEPTABLE"
    RESOLVED_UNACCEPTABLE = "RESOLVED_UNACCEPTABLE"
    VOIDED = "VOIDED"


class ExcursionOutcome(str, Enum):
    ACCEPTABLE = "ACCEPTABLE"
    UNACCEPTABLE = "UNACCEPTABLE"
    VOID = "VOID"


class EnrollmentStatus(str, Enum):
    SCREENING = "SCREENING"
    SCREEN_FAILED = "SCREEN_FAILED"
    RANDOMIZED = "RANDOMIZED"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class BlindedStatus(str, Enum):
    BLINDED = "BLINDED"
    UNBLINDED = "UNBLINDED"


class Stratum(str, Enum):
    STANDARD = "STANDARD"
    HIGH_RISK = "HIGH_RISK"


class SlotStatus(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"
    RELEASED = "RELEASED"


class DispensingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETURNED = "RETURNED"
    RECONCILED = "RECONCILED"


class ReturnStatus(str, Enum):
    RECORDED = "RECORDED"
    VERIFIED = "VERIFIED"


class DestructionMethod(str, Enum):
    INCINERATION = "INCINERATION"
    CHEMICAL_NEUTRALIZATION = "CHEMICAL_NEUTRALIZATION"
    RETURN_TO_SPONSOR = "RETURN_TO_SPONSOR"


class DestructionStatus(str, Enum):
    DRAFT = "DRAFT"
    WITNESSED = "WITNESSED"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


class UnblindingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"


class MonitorVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED_RECONCILED = "CLOSED_RECONCILED"
    CLOSED_DISCREPANCY = "CLOSED_DISCREPANCY"


class FeeScheduleStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class InvoiceVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


# --- Entity TypedDicts (PRD §2.4 common fields: id, created_at, updated_at, version) ---

class Study(TypedDict, total=False):
    id: str
    protocol_number: str
    title: str
    phase: str
    blinding_model: str
    status: str
    max_dose_per_visit_mg: int
    unblinding_suspension_threshold_pct: int
    randomized_subject_count: int
    unblinded_subject_count: int
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict, total=False):
    id: str
    study_id: str
    site_number: str
    name: str
    principal_investigator: str
    status: str
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PharmacyStaff(TypedDict, total=False):
    id: str
    site_id: str
    full_name: str
    license_number: str
    is_unblinded: bool
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict, total=False):
    id: str
    study_id: str
    lot_number: str
    product_name: str
    strength_mg: int
    dosage_form: str
    expiry_date: str
    storage_temp_min_celsius: float
    storage_temp_max_celsius: float
    stability_budget_minutes: int
    stability_minutes_consumed: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Kit(TypedDict, total=False):
    id: str
    lot_id: str
    site_id: str
    kit_number: str
    status: str
    pre_quarantine_status: Optional[str]
    excursion_id: Optional[str]
    allocated_subject_id: Optional[str]
    units_received: int
    units_dispensed: int
    units_returned: int
    units_destroyed: int
    units_lost: int
    on_hand_units: int
    created_at: str
    updated_at: str
    version: int


# Append-only observation (PRD §2.4 exception): carries ONLY id + created_at,
# never updated_at / version.
class TemperatureLog(TypedDict, total=False):
    id: str
    site_id: str
    celsius: float
    source: str
    recorded_at: str
    excursion_id: Optional[str]
    created_at: str


class TemperatureExcursion(TypedDict, total=False):
    id: str
    site_id: str
    status: str
    window_start: str
    window_end: str
    min_observed_celsius: float
    max_observed_celsius: float
    severity_minutes_charged: int
    resolution_rationale: Optional[str]
    reference_temp_min_celsius: float
    reference_temp_max_celsius: float
    created_at: str
    updated_at: str
    version: int


class Subject(TypedDict, total=False):
    id: str
    site_id: str
    subject_number: str
    stratum: str
    enrollment_status: str
    blinded_status: str
    rescreen_count: int
    randomized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RandomizationSlot(TypedDict, total=False):
    id: str
    study_id: str
    sequence_number: int
    stratum: str
    kit_number: str
    arm_code: Optional[str]
    status: str
    assigned_subject_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DispensingRecord(TypedDict, total=False):
    id: str
    subject_id: str
    kit_id: str
    visit_number: int
    quantity_dispensed: int
    dose_mg: int
    dispensed_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DrugReturn(TypedDict, total=False):
    id: str
    dispensing_record_id: str
    quantity_returned: int
    status: str
    recorded_by_staff_id: str
    verified_by_staff_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DestructionRecord(TypedDict, total=False):
    id: str
    kit_id: str
    site_id: str
    method: str
    facility_window_start: str
    facility_window_end: str
    quantity_destroyed: int
    witness_staff_id: str
    created_by_staff_id: str
    kit_prior_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class UnblindingRequest(TypedDict, total=False):
    id: str
    subject_id: str
    reason: str
    requested_by_user_id: str
    status: str
    decided_by_staff_id: Optional[str]
    revealed_arm_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MonitorVisit(TypedDict, total=False):
    id: str
    site_id: str
    monitor_name: str
    scheduled_start: str
    scheduled_end: str
    status: str
    started_at: Optional[str]
    closed_at: Optional[str]
    actual_minutes: Optional[int]
    discrepancy_count: int
    created_at: str
    updated_at: str
    version: int


class FeeSchedule(TypedDict, total=False):
    id: str
    study_id: str
    status: str
    setup_fee_cents: int
    dispensing_fee_cents: int
    dispensing_tier_threshold: int
    dispensing_tier_fee_cents: int
    monitoring_fee_cents_per_hour: int
    storage_fee_cents_per_kit_month: int
    unblinding_fee_cents: int
    overhead_pct: float
    created_at: str
    updated_at: str
    version: int
