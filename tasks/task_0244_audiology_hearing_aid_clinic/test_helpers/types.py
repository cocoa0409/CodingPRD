"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the entities and lifecycles defined in the Audiology & Hearing Aid Clinic PRD.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Roles ---

class UserRole(str, Enum):
    CLINIC_ADMIN = "ClinicAdmin"
    AUDIOLOGIST = "Audiologist"
    BILLING_CLERK = "BillingClerk"
    PATIENT = "Patient"


# --- Status enums ---

class PatientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class DeviceModelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class AllowanceBenefitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"


class HearingEvaluationStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class Severity(str, Enum):
    NORMAL = "NORMAL"
    MILD = "MILD"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"
    PROFOUND = "PROFOUND"


class FittingOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    TRIAL = "TRIAL"
    PURCHASED = "PURCHASED"
    WARRANTY_ACTIVE = "WARRANTY_ACTIVE"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class AdjustmentSessionStatus(str, Enum):
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class AdjustmentReason(str, Enum):
    COMFORT = "COMFORT"
    RECALL_REPROGRAM = "RECALL_REPROGRAM"
    GAIN_TUNE = "GAIN_TUNE"


class WarrantyClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    REPLACED = "REPLACED"


class ClaimType(str, Enum):
    DEFECT = "DEFECT"
    LOSS = "LOSS"
    DAMAGE = "DAMAGE"


class SupplySubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class SupplyCycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SHIPPED = "SHIPPED"
    SKIPPED = "SKIPPED"


class RecallSeverity(str, Enum):
    ADVISORY = "ADVISORY"
    MANDATORY = "MANDATORY"


class RecallStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    CLOSED = "CLOSED"


class LedgerSourceKind(str, Enum):
    ORDER_PURCHASE = "ORDER_PURCHASE"
    ORDER_RETURN = "ORDER_RETURN"
    ALLOWANCE_APPLIED = "ALLOWANCE_APPLIED"
    WARRANTY_DEDUCTIBLE = "WARRANTY_DEDUCTIBLE"
    SUPPLY_BILLING = "SUPPLY_BILLING"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---

class Patient(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    insurer_name: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DeviceModel(TypedDict):
    id: str
    model_code: str
    name: str
    list_price_cents: int
    restock_fee_cents: int
    min_severity: str
    firmware_version: str
    warranty_months: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AllowanceBenefit(TypedDict):
    id: str
    patient_id: str
    plan_name: str
    total_allowance_cents: int
    per_device_cap_cents: int
    coinsurance_pct: float
    consumed_allowance_cents: int
    period_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class HearingEvaluation(TypedDict):
    id: str
    patient_id: str
    audiologist_user_id: str
    pure_tone_avg_db: int
    severity: str
    is_pediatric: bool
    candidate: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class FittingOrder(TypedDict):
    id: str
    patient_id: str
    evaluation_id: str
    device_model_id: str
    allowance_benefit_id: Optional[str]
    ear_count: int
    trial_started_at: Optional[str]
    trial_deadline_at: Optional[str]
    gross_price_cents: Optional[int]
    allowance_applied_cents: int
    patient_due_cents: Optional[int]
    refund_cents: int
    fitted_firmware_version: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AdjustmentSession(TypedDict):
    id: str
    fitting_order_id: str
    audiologist_user_id: str
    reason: str
    applied_firmware_version: Optional[str]
    recall_notice_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    fitting_order_id: str
    claim_type: str
    incident_date: str
    assessed_value_cents: int
    deductible_cents: Optional[int]
    clinic_cost_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class SupplySubscription(TypedDict):
    id: str
    patient_id: str
    fitting_order_id: str
    cadence_days: int
    unit_price_cents: int
    started_at: Optional[str]
    cycles_fulfilled: int
    lifetime_billed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SupplyCycle(TypedDict):
    id: str
    subscription_id: str
    cycle_index: int
    due_at: str
    billed_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class RecallNotice(TypedDict):
    id: str
    device_model_id: str
    affected_firmware_version: str
    target_firmware_version: str
    severity_level: str
    affected_order_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# --- LedgerEntry: common_fields false — only id + created_at, NO updated_at/version ---

class LedgerEntry(TypedDict):
    id: str
    patient_id: str
    source_kind: str
    source_ref_id: str
    amount_cents: int
    memo: Optional[str]
    created_at: str
