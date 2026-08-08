"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in this system carries the four system-managed common fields
(id, created_at, updated_at, version) per the PRD's common resource properties.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------- roles
class UserRole(str, Enum):
    CLINIC_ADMIN = "ClinicAdmin"
    CLINICIAN = "Clinician"
    PHARMACIST = "Pharmacist"
    PATIENT = "Patient"


# --------------------------------------------------------------------------- enums
class PatientSex(str, Enum):
    MALE = "MALE"
    OTHER = "OTHER"


class MembershipTier(str, Enum):
    CORE = "CORE"
    PLUS = "PLUS"
    ELITE = "ELITE"


class SubscriptionStatus(str, Enum):
    TRIAL = "TRIAL"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"


class PanelType(str, Enum):
    BASELINE = "BASELINE"
    MONITORING = "MONITORING"


class LabPanelStatus(str, Enum):
    ORDERED = "ORDERED"
    DRAWN = "DRAWN"
    RESULTED = "RESULTED"
    REVIEWED = "REVIEWED"


class LabDrawAppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TelehealthVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ProtocolType(str, Enum):
    TRT_INJECTION = "TRT_INJECTION"
    TRT_TOPICAL = "TRT_TOPICAL"
    ED_THERAPY = "ED_THERAPY"


class TreatmentPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TITRATION_PENDING = "TITRATION_PENDING"
    MONITORING_HOLD = "MONITORING_HOLD"
    SUSPENDED = "SUSPENDED"


class DoseTitrationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class PrescriptionStatus(str, Enum):
    ISSUED = "ISSUED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    EXHAUSTED = "EXHAUSTED"


class RefillOrderStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    DISPENSED = "DISPENSED"
    CANCELLED = "CANCELLED"
    REVERSED = "REVERSED"


class AdverseEventSeverity(str, Enum):
    MILD = "MILD"
    SEVERE = "SEVERE"


class AdverseEventStatus(str, Enum):
    REPORTED = "REPORTED"
    MILD_LOGGED = "MILD_LOGGED"
    SEVERE_ESCALATED = "SEVERE_ESCALATED"
    RESOLVED = "RESOLVED"


# --------------------------------------------------------------------------- entities
class Clinician(TypedDict):
    id: str
    full_name: str
    npi: str
    dea_number: str
    created_at: str
    updated_at: str
    version: int


class Pharmacist(TypedDict):
    id: str
    full_name: str
    license_number: str
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    sex: str
    email: str
    created_at: str
    updated_at: str
    version: int


class MembershipPlan(TypedDict):
    id: str
    tier: str
    monthly_fee_cents: int
    cycle_days: int
    included_refills_per_cycle: int
    included_lab_draw_credits: int
    refill_discount_pct: float
    titration_visit_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    patient_id: str
    plan_id: str
    subscription_status: str
    payment_status: str
    lab_draw_credits_remaining: int
    cycle_anchor_date: str
    last_change_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class DrawStation(TypedDict):
    id: str
    name: str
    concurrent_capacity: int
    created_at: str
    updated_at: str
    version: int


class LabPanel(TypedDict):
    id: str
    patient_id: str
    clinician_id: str
    panel_type: str
    total_testosterone_ng_dl: int
    psa_ng_ml: float
    hematocrit_pct: float
    drawn_at: str
    is_unsafe: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class LabDrawAppointment(TypedDict):
    id: str
    patient_id: str
    draw_station_id: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TelehealthVisit(TypedDict):
    id: str
    patient_id: str
    clinician_id: str
    start_at: str
    end_at: str
    reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TreatmentPlan(TypedDict):
    id: str
    patient_id: str
    clinician_id: str
    baseline_panel_id: str
    protocol_type: str
    starting_dose_mg: float
    current_dose_mg: float
    round_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DoseTitration(TypedDict):
    id: str
    plan_id: str
    round_index: int
    previous_dose_mg: float
    proposed_dose_mg: float
    applied: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ControlledSubstancePrescription(TypedDict):
    id: str
    plan_id: str
    patient_id: str
    prescriber_id: str
    drug_name: str
    unit_price_cents: int
    quantity_per_fill: int
    refills_authorized: int
    refills_remaining: int
    is_controlled: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RefillOrder(TypedDict):
    id: str
    prescription_id: str
    membership_id: str
    patient_id: str
    requested_quantity_units: int
    dispensed_quantity_units: int
    provisional_charge_cents: int
    final_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AdverseEvent(TypedDict):
    id: str
    patient_id: str
    plan_id: str
    reported_by: Optional[str]
    description: str
    severity: str
    status: str
    created_at: str
    updated_at: str
    version: int
