"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PHARMACY_ADMIN = "PharmacyAdmin"
    PHARMACIST = "Pharmacist"
    TECHNICIAN = "Technician"
    CASHIER = "Cashier"


# ---------------------------------------------------------------------------
# Status / enum vocabularies (PRD §2.11)
# ---------------------------------------------------------------------------
class DrugStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class DeaSchedule(str, Enum):
    NONE = "NONE"
    CII = "CII"
    CIII = "CIII"
    CIV = "CIV"
    CV = "CV"


class PrescriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"
    DISCONTINUED = "DISCONTINUED"


class FillStatus(str, Enum):
    ENTERED = "ENTERED"
    DUR_REVIEW = "DUR_REVIEW"
    ADJUDICATING = "ADJUDICATING"
    PA_REFERRAL = "PA_REFERRAL"
    READY_FILL = "READY_FILL"
    WILL_CALL = "WILL_CALL"
    DISPENSED = "DISPENSED"
    RETURNED_TO_STOCK = "RETURNED_TO_STOCK"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    UNCLAIMED = "UNCLAIMED"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    REJECTED = "REJECTED"
    PA_PENDING = "PA_PENDING"
    REVERSED = "REVERSED"


class PaStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class PaReason(str, Enum):
    DRUG_PA_REQUIRED = "DRUG_PA_REQUIRED"
    PLAN_PA_REQUIRED = "PLAN_PA_REQUIRED"
    CONTROLLED_PA_REQUIRED = "CONTROLLED_PA_REQUIRED"


class PdmpFlag(str, Enum):
    CLEAR = "CLEAR"
    REVIEW = "REVIEW"
    BLOCKED = "BLOCKED"


class ControlledStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    LOCKED = "LOCKED"


class DurSeverity(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class AlertType(str, Enum):
    INTERACTION = "INTERACTION"
    ALLERGY = "ALLERGY"
    DUPLICATE_THERAPY = "DUPLICATE_THERAPY"
    HIGH_DOSE = "HIGH_DOSE"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

# The logical clock is a singleton: id + created_at + current_utc only.
# It has neither updated_at nor version (PRD §2.4).
class PharmacyClock(TypedDict):
    id: str
    created_at: str
    current_utc: str


# All entities below are mutable: id + created_at + updated_at + version.
class DrugProduct(TypedDict):
    id: str
    ndc: str
    name: str
    dea_schedule: str
    unit_price_cents: int
    pa_required: bool
    therapeutic_substitute_of_id: Optional[str]
    is_active: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class InsurancePlan(TypedDict):
    id: str
    bin: str
    pcn: str
    name: str
    copay_pct: float
    copay_min_cents: int
    copay_max_cents: int
    dispensing_fee_cents: int
    refill_too_soon_threshold_pct: float
    requires_pa_for_controlled: bool
    created_at: str
    updated_at: str
    version: int


class FormularyEntry(TypedDict):
    id: str
    plan_id: str
    drug_id: str
    tier: int
    allowed_amount_cents: int
    requires_pa: bool
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    plan_id: Optional[str]
    allergy_classes: List[str]
    auto_refill_enrolled: bool
    med_sync_day: Optional[int]
    pdmp_flag: str
    controlled_status: str
    created_at: str
    updated_at: str
    version: int


class Prescriber(TypedDict):
    id: str
    full_name: str
    npi: str
    dea_number: Optional[str]
    dea_active: bool
    created_at: str
    updated_at: str
    version: int


class Prescription(TypedDict):
    id: str
    patient_id: str
    prescriber_id: str
    drug_id: str
    quantity_per_fill: int
    days_supply: int
    refills_authorized: int
    refills_remaining: int
    written_utc: str
    expires_utc: str
    last_dispensed_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Fill(TypedDict):
    id: str
    prescription_id: str
    fill_sequence: int
    quantity_dispensed: int
    days_supply: int
    gross_amount_cents: int
    provisional_copay_cents: Optional[int]
    final_copay_cents: Optional[int]
    plan_paid_cents: Optional[int]
    dur_severity: str
    dur_override_by: Optional[str]
    claim_status: str
    pickup_deadline_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DurAlert(TypedDict):
    id: str
    fill_id: str
    alert_type: str
    severity: str
    detail: str
    overridden: bool
    override_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InteractionRule(TypedDict):
    id: str
    drug_a_id: str
    drug_b_id: str
    severity: str
    detail: str
    created_at: str
    updated_at: str
    version: int


class PriorAuthRequest(TypedDict):
    id: str
    fill_id: str
    prescription_id: str
    reason: str
    submitted_utc: str
    decided_utc: Optional[str]
    expires_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PdmpReport(TypedDict):
    id: str
    patient_id: str
    fill_id: Optional[str]
    lookback_days: int
    controlled_fill_count: int
    distinct_prescriber_count: int
    risk_score: int
    resulting_flag: str
    created_at: str
    updated_at: str
    version: int


class PaymentRecord(TypedDict):
    id: str
    fill_id: str
    amount_cents: int
    tendered_by: str
    refunded: bool
    created_at: str
    updated_at: str
    version: int
