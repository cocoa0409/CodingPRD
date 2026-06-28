"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this API carry the full common-field complement
(id, created_at, updated_at, version) per PRD Section 2.4.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Dict


# ─── Role enum ────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    CLINIC_ADMIN = "ClinicAdmin"
    PRACTITIONER = "Practitioner"
    PHARMACIST = "Pharmacist"
    PATIENT = "Patient"


# ─── Status enums ─────────────────────────────────────────────────────────
class PatientIntakeStatus(str, Enum):
    PENDING_INTAKE = "PENDING_INTAKE"
    INTAKE_COMPLETE = "INTAKE_COMPLETE"


class MembershipStatus(str, Enum):
    NONE = "NONE"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"


class PayerMode(str, Enum):
    CASH = "CASH"
    INSURANCE = "INSURANCE"


class IntakeStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class TreatmentPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PackageSeriesStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    CANCELLED = "CANCELLED"


class ChargeSource(str, Enum):
    PER_VISIT = "PER_VISIT"
    PACKAGE = "PACKAGE"


class ArrivalClass(str, Enum):
    PENDING = "PENDING"
    ON_TIME = "ON_TIME"
    LATE = "LATE"


class ClinicalStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    BILLED = "BILLED"
    WAIVED = "WAIVED"
    PENALTY_DUE = "PENALTY_DUE"


class AddOnModality(str, Enum):
    CUPPING = "CUPPING"
    MOXA = "MOXA"


class AddOnStatus(str, Enum):
    ATTACHED = "ATTACHED"
    VOIDED = "VOIDED"


class FormulaDispenseStatus(str, Enum):
    REQUESTED = "REQUESTED"
    FILLED = "FILLED"
    REVERSED = "REVERSED"


class ChargeType(str, Enum):
    VISIT = "VISIT"
    PENALTY = "PENALTY"


class ChargeStatus(str, Enum):
    OPEN = "OPEN"
    VOID = "VOID"


class SuperbillStatus(str, Enum):
    ISSUED = "ISSUED"
    VOID = "VOID"


class StockStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    LOW_STOCK = "LOW_STOCK"


# Diagnostic finding enums
class TongueFinding(str, Enum):
    PALE = "PALE"
    RED = "RED"
    PURPLE = "PURPLE"
    NORMAL = "NORMAL"


class TongueCoating(str, Enum):
    THIN_WHITE = "THIN_WHITE"
    THICK_YELLOW = "THICK_YELLOW"
    NONE = "NONE"
    GREASY = "GREASY"


class PulseFinding(str, Enum):
    WIRY = "WIRY"
    SLIPPERY = "SLIPPERY"
    THREADY = "THREADY"
    RAPID = "RAPID"
    DEEP = "DEEP"
    FLOATING = "FLOATING"


class TcmPattern(str, Enum):
    QI_STAGNATION = "QI_STAGNATION"
    BLOOD_DEFICIENCY = "BLOOD_DEFICIENCY"
    DAMP_HEAT = "DAMP_HEAT"
    YANG_DEFICIENCY = "YANG_DEFICIENCY"
    YIN_DEFICIENCY = "YIN_DEFICIENCY"


# ─── Entity TypedDicts (all carry id/created_at/updated_at/version) ────────
class Patient(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    payer_mode: str
    insurance_member_id: Optional[str]
    coinsurance_rate: float
    intake_status: str
    membership_status: str
    strike_count: int
    created_at: str
    updated_at: str
    version: int


class Intake(TypedDict):
    id: str
    patient_id: str
    chief_complaint: str
    tongue_finding: str
    tongue_coating: str
    pulse_finding: str
    tcm_pattern: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TreatmentPlan(TypedDict):
    id: str
    patient_id: str
    practitioner_id: str
    intake_id: str
    acupoints: List[str]
    planned_sessions: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PackageSeries(TypedDict):
    id: str
    patient_id: str
    total_credits: int
    price_paid_cents: int
    reserved_credits: int
    consumed_credits: int
    provisional_remaining_credits: int
    finalized_remaining_credits: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Practitioner(TypedDict):
    id: str
    full_name: str
    license_number: str
    turnover_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class TreatmentRoom(TypedDict):
    id: str
    room_name: str
    cleanup_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    patient_id: str
    treatment_plan_id: str
    practitioner_id: str
    room_id: str
    package_series_id: Optional[str]
    charge_source: str
    scheduled_start: str
    scheduled_end: str
    base_fee_cents: int
    checked_in_at: Optional[str]
    arrival_class: str
    clinical_status: str
    billing_status: str
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict):
    id: str
    appointment_id: str
    modality: str
    fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class HerbalFormula(TypedDict):
    id: str
    formula_name: str
    line_items: List[Dict]
    created_at: str
    updated_at: str
    version: int


class HerbItem(TypedDict):
    id: str
    herb_name: str
    initial_grams: int
    on_hand_grams: int
    reorder_threshold_grams: int
    stock_status: str
    created_at: str
    updated_at: str
    version: int


class FormulaDispense(TypedDict):
    id: str
    patient_id: str
    treatment_plan_id: str
    herbal_formula_id: str
    doses: int
    total_grams_by_herb: Dict[str, int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Charge(TypedDict):
    id: str
    appointment_id: str
    subtotal_cents: int
    cash_discount_cents: int
    total_due_cents: int
    charge_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Superbill(TypedDict):
    id: str
    appointment_id: str
    line_charges_cents: List[int]
    insurance_allowed_cents: int
    patient_responsibility_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
