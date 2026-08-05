"""Domain types for the GLP-1 weight-loss telehealth API.

Entity TypedDicts, status enumerations and the caller-role enumeration, all
named exactly as the PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Caller roles
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    PATIENT = "Patient"
    PROVIDER = "Provider"
    COACH = "Coach"
    PHARMACY_OPERATOR = "PharmacyOperator"
    BILLING_ADMIN = "BillingAdmin"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Status enumerations
# ---------------------------------------------------------------------------


class PatientEligibilityStatus(str, Enum):
    NOT_SCREENED = "NOT_SCREENED"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    DEFERRED = "DEFERRED"


class PaymentMode(str, Enum):
    INSURANCE = "INSURANCE"
    CASH = "CASH"


class ProviderType(str, Enum):
    CLINICIAN = "CLINICIAN"
    COACH = "COACH"


class ProviderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DispenseType(str, Enum):
    COMPOUNDED = "COMPOUNDED"
    BRANDED = "BRANDED"


class PharmacyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SupplyLotStatus(str, Enum):
    RELEASED = "RELEASED"
    QUARANTINED = "QUARANTINED"


class ScreeningStatus(str, Enum):
    DRAFT = "DRAFT"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    DEFERRED = "DEFERRED"


class EligibilityBand(str, Enum):
    OBESITY = "OBESITY"
    COMORBID = "COMORBID"
    NONE = "NONE"


class DecisionReason(str, Enum):
    BMI_QUALIFIED = "BMI_QUALIFIED"
    COMORBID_QUALIFIED = "COMORBID_QUALIFIED"
    BMI_BELOW_BAND = "BMI_BELOW_BAND"
    RENAL_EXCLUSION = "RENAL_EXCLUSION"
    STALE_LABS = "STALE_LABS"


class ConsultStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED_PRESCRIBED = "COMPLETED_PRESCRIBED"
    COMPLETED_DECLINED = "COMPLETED_DECLINED"
    NO_SHOW = "NO_SHOW"


class ConsultOutcome(str, Enum):
    PRESCRIBE = "PRESCRIBE"
    DECLINE = "DECLINE"
    NO_SHOW = "NO_SHOW"


class DrugFamily(str, Enum):
    SEMAGLUTIDE = "SEMAGLUTIDE"
    TIRZEPATIDE = "TIRZEPATIDE"


class ClinicalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    HELD = "HELD"
    DISCONTINUED = "DISCONTINUED"


class FulfillmentStatus(str, Enum):
    UNROUTED = "UNROUTED"
    ROUTED = "ROUTED"
    DISPENSED = "DISPENSED"
    REFILL_DUE = "REFILL_DUE"


class RouteMode(str, Enum):
    INSURANCE = "INSURANCE"
    CASH = "CASH"


class DiscontinueReason(str, Enum):
    PATIENT_REQUEST = "PATIENT_REQUEST"
    CLINICAL = "CLINICAL"
    SUPERSEDED = "SUPERSEDED"


class TitrationStepStatus(str, Enum):
    DUE = "DUE"
    ADMINISTERED = "ADMINISTERED"
    HELD = "HELD"
    REDUCED = "REDUCED"


class HoldReason(str, Enum):
    SIDE_EFFECT = "SIDE_EFFECT"
    PROVIDER_HOLD = "PROVIDER_HOLD"


class PriorAuthorizationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"


class PriorAuthorizationDecision(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class PharmacyOrderStatus(str, Enum):
    CREATED = "CREATED"
    RESERVED = "RESERVED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class CancelReason(str, Enum):
    OPERATOR = "OPERATOR"
    PA_DENIED = "PA_DENIED"
    CLINICAL_HOLD = "CLINICAL_HOLD"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class BillingCycleStatus(str, Enum):
    OPEN = "OPEN"
    INVOICED = "INVOICED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class ChargeBasis(str, Enum):
    CASH_PAY = "CASH_PAY"
    INSURANCE_ADJUDICATED = "INSURANCE_ADJUDICATED"


class VoidReason(str, Enum):
    ADMIN_REVERSAL = "ADMIN_REVERSAL"
    SUBSCRIPTION_PAUSED = "SUBSCRIPTION_PAUSED"
    SUBSCRIPTION_CANCELLED = "SUBSCRIPTION_CANCELLED"


class CheckInStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CLEARED = "CLEARED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class CoachingSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FORFEITED = "FORFEITED"


class ComorbidityCode(str, Enum):
    TYPE_2_DIABETES = "TYPE_2_DIABETES"
    HYPERTENSION = "HYPERTENSION"
    DYSLIPIDEMIA = "DYSLIPIDEMIA"
    OSA = "OSA"
    CVD = "CVD"


# ---------------------------------------------------------------------------
# Entity shapes — every resource carries id, created_at, updated_at, version
# ---------------------------------------------------------------------------


class Patient(TypedDict):
    id: str
    email: str
    full_name: str
    state_code: str
    height_cm: float
    weight_kg: float
    comorbidity_codes: List[str]
    payment_mode: str
    current_bmi: float
    eligibility_status: str
    lifetime_charged_cents: int
    lifetime_credited_cents: int
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict):
    id: str
    full_name: str
    provider_type: str
    npi: Optional[str]
    licensed_state_codes: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Pharmacy(TypedDict):
    id: str
    name: str
    dispense_type: str
    served_state_codes: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SupplyLot(TypedDict):
    id: str
    pharmacy_id: str
    lot_code: str
    strength_mg: float
    total_units: int
    window_capacity_units: int
    available_units: int
    reserved_units: int
    dispensed_units: int
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EligibilityScreening(TypedDict):
    id: str
    patient_id: str
    status: str
    recorded_weight_kg: float
    recorded_height_cm: float
    egfr: float
    a1c_pct: Optional[float]
    lab_collected_at: str
    comorbidity_count: int
    assessed_bmi: Optional[float]
    eligibility_band: Optional[str]
    decision_reason: Optional[str]
    submitted_at: Optional[str]
    submit_count: int
    created_at: str
    updated_at: str
    version: int


class Consult(TypedDict):
    id: str
    patient_id: str
    provider_id: str
    scheduled_start_at: str
    scheduled_end_at: str
    status: str
    outcome_note: Optional[str]
    reschedule_count: int
    created_at: str
    updated_at: str
    version: int


class Prescription(TypedDict):
    id: str
    patient_id: str
    consult_id: str
    prescriber_provider_id: str
    screening_id: str
    supersedes_prescription_id: Optional[str]
    drug_family: str
    units_per_cycle: int
    dose_level: int
    dose_mg: float
    clinical_status: str
    fulfillment_status: str
    active_route_mode: str
    last_dose_change_at: str
    severity_index_rolling: int
    severity_index_since_dose_change: int
    discontinue_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TitrationStep(TypedDict):
    id: str
    prescription_id: str
    second_signer_provider_id: Optional[str]
    step_number: int
    dose_level: int
    dose_mg: float
    status: str
    earliest_escalation_at: str
    administered_at: Optional[str]
    hold_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PriorAuthorization(TypedDict):
    id: str
    prescription_id: str
    payer_reference: str
    status: str
    appeal_count: int
    decided_at: Optional[str]
    denial_reason: Optional[str]
    approved_through_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PharmacyOrder(TypedDict):
    id: str
    prescription_id: str
    titration_step_id: str
    pharmacy_id: str
    supply_lot_id: str
    units_requested: int
    window_start_at: str
    window_end_at: str
    status: str
    dispense_type_at_route: str
    reserved_at: Optional[str]
    shipped_at: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    patient_id: str
    prescription_id: str
    anchor_at: str
    coaching_addon_enabled: bool
    status: str
    coaching_credits_granted: int
    coaching_credits_reserved: int
    coaching_credits_consumed: int
    coaching_credits_forfeited: int
    coaching_credits_available: int
    paused_at: Optional[str]
    pause_days_used: int
    cycle_count: int
    created_at: str
    updated_at: str
    version: int


class BillingCycle(TypedDict):
    id: str
    subscription_id: str
    sequence_number: int
    period_start_at: str
    period_end_at: str
    status: str
    charge_basis: Optional[str]
    medication_charge_cents: int
    coaching_addon_fee_cents: int
    dispensing_fee_cents: int
    adherence_credit_cents: int
    total_due_cents: int
    settled_amount_cents: int
    proration_credit_cents: int
    coaching_unused_credit_cents: int
    invoiced_at: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CheckIn(TypedDict):
    id: str
    patient_id: str
    prescription_id: str
    triaged_by_provider_id: Optional[str]
    nausea_score: int
    vomiting_score: int
    dehydration_flag: bool
    severity_score: int
    status: str
    submitted_at: str
    triaged_at: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CoachingSession(TypedDict):
    id: str
    subscription_id: str
    coach_provider_id: str
    billing_cycle_id: str
    scheduled_start_at: str
    scheduled_end_at: str
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
