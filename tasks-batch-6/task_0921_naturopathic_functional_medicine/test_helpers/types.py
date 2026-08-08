"""Domain types: entity TypedDicts, status enums, role enum."""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    PRACTICE_ADMIN = "PracticeAdmin"
    NATUROPATHIC_DOCTOR = "NaturopathicDoctor"
    HEALTH_COACH = "HealthCoach"
    DISPENSARY_TECH = "DispensaryTech"
    CLINICAL_DIRECTOR = "ClinicalDirector"
    BILLING_SPECIALIST = "BillingSpecialist"
    PATIENT = "Patient"


# --------------------------------------------------------------------------- #
# Status / enum vocabularies
# --------------------------------------------------------------------------- #
class Credential(str, Enum):
    ND = "ND"
    HEALTH_COACH = "HEALTH_COACH"
    DISPENSARY_TECH = "DISPENSARY_TECH"
    CLINICAL_DIRECTOR = "CLINICAL_DIRECTOR"


class ClinicalStatus(str, Enum):
    INTAKE = "INTAKE"
    ESTABLISHED = "ESTABLISHED"
    INACTIVE = "INACTIVE"


class ScopeReviewStatus(str, Enum):
    NONE = "NONE"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLEARED = "CLEARED"
    RESTRICTED = "RESTRICTED"


class ClinicalWriteGate(str, Enum):
    OPEN = "OPEN"
    FROZEN_SCOPE_REVIEW = "FROZEN_SCOPE_REVIEW"
    FROZEN_RED_FLAG = "FROZEN_RED_FLAG"


class SectionType(str, Enum):
    CHIEF_COMPLAINT_TIMELINE = "CHIEF_COMPLAINT_TIMELINE"
    SYSTEMS_REVIEW = "SYSTEMS_REVIEW"
    DIET_LIFESTYLE = "DIET_LIFESTYLE"
    MEDICATIONS_SUPPLEMENTS = "MEDICATIONS_SUPPLEMENTS"
    FAMILY_HISTORY = "FAMILY_HISTORY"


class IntakeSectionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ATTESTED = "ATTESTED"
    EXPIRED = "EXPIRED"


class MembershipTier(str, Enum):
    FOUNDATION = "FOUNDATION"
    CORE = "CORE"
    PREMIER = "PREMIER"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    EXPIRED = "EXPIRED"


class PanelCode(str, Enum):
    SERUM_METABOLIC = "SERUM_METABOLIC"
    DUTCH_HORMONE = "DUTCH_HORMONE"
    SALIVA_CORTISOL = "SALIVA_CORTISOL"
    STOOL_GI_MAP = "STOOL_GI_MAP"


class SpecimenType(str, Enum):
    SERUM = "SERUM"
    DRIED_URINE = "DRIED_URINE"
    SALIVA = "SALIVA"
    STOOL = "STOOL"


class FundingSource(str, Enum):
    MEMBERSHIP_CREDIT = "MEMBERSHIP_CREDIT"
    CASH = "CASH"


class LabOrderStatus(str, Enum):
    ORDERED = "ORDERED"
    WASHOUT_HOLD = "WASHOUT_HOLD"
    COLLECTED = "COLLECTED"
    RESULTED = "RESULTED"
    CRITICAL_ESCALATED = "CRITICAL_ESCALATED"
    INTERPRETED = "INTERPRETED"
    CANCELLED = "CANCELLED"


class StandardBand(str, Enum):
    LOW = "LOW"
    IN_RANGE = "IN_RANGE"
    HIGH = "HIGH"


class OptimalBand(str, Enum):
    BELOW_OPTIMAL = "BELOW_OPTIMAL"
    OPTIMAL = "OPTIMAL"
    ABOVE_OPTIMAL = "ABOVE_OPTIMAL"


class ProtocolStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"
    DISCONTINUED = "DISCONTINUED"


class ProtocolItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    HELD = "HELD"
    DISCONTINUED = "DISCONTINUED"
    COMPLETED = "COMPLETED"


class TitrationDecision(str, Enum):
    ADVANCE = "ADVANCE"
    HOLD = "HOLD"
    REDUCE = "REDUCE"
    DISCONTINUE = "DISCONTINUE"


class DiscontinueReason(str, Enum):
    ADVERSE_REACTION = "ADVERSE_REACTION"
    SUPERSEDED_BY_REVISION = "SUPERSEDED_BY_REVISION"
    PROTOCOL_DISCONTINUED = "PROTOCOL_DISCONTINUED"


class SupplementClass(str, Enum):
    HORMONE_SUPPORT = "HORMONE_SUPPORT"
    ADAPTOGEN = "ADAPTOGEN"
    PROBIOTIC = "PROBIOTIC"
    BOTANICAL = "BOTANICAL"
    VITAMIN_MINERAL = "VITAMIN_MINERAL"
    ENZYME = "ENZYME"


class InteractionSeverity(str, Enum):
    NONE = "NONE"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class PricingVariant(str, Enum):
    RETAIL = "RETAIL"
    MEMBER = "MEMBER"
    PRACTITIONER_COST = "PRACTITIONER_COST"


class DispenseStatus(str, Enum):
    DISPENSED = "DISPENSED"
    REVERSED = "REVERSED"


class Modality(str, Enum):
    IN_PERSON = "IN_PERSON"
    TELEHEALTH = "TELEHEALTH"
    EVISIT = "EVISIT"


class SchedulingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class BillingStatus(str, Enum):
    CASH_PENDING = "CASH_PENDING"
    ENTITLEMENT_RESERVED = "ENTITLEMENT_RESERVED"
    ENTITLEMENT_CONSUMED = "ENTITLEMENT_CONSUMED"
    CASH_CHARGED = "CASH_CHARGED"
    SUPERBILLED = "SUPERBILLED"
    REFUNDED = "REFUNDED"
    FORFEITED = "FORFEITED"


class ThreadStatus(str, Enum):
    OPEN = "OPEN"
    ANSWERED = "ANSWERED"
    CONVERTED_TO_EVISIT = "CONVERTED_TO_EVISIT"
    CLOSED = "CLOSED"


class SuperbillStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    CLOSED = "CLOSED"


class SuperbillAction(str, Enum):
    ISSUE = "ISSUE"
    VOID = "VOID"
    REISSUE = "REISSUE"
    REPORT_DENIAL = "REPORT_DENIAL"
    APPEAL = "APPEAL"
    CLOSE = "CLOSE"


class ReferralType(str, Enum):
    ROUTINE = "ROUTINE"
    RED_FLAG_AUTO = "RED_FLAG_AUTO"


class ReferralStatus(str, Enum):
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REPORT_RECEIVED = "REPORT_RECEIVED"
    CLOSED = "CLOSED"
    DECLINED = "DECLINED"
    ABANDONED = "ABANDONED"


class ReferralAction(str, Enum):
    ACKNOWLEDGE = "ACKNOWLEDGE"
    REPORT = "REPORT"
    CLOSE = "CLOSE"
    DECLINE = "DECLINE"
    RE_REFER = "RE_REFER"


class AdverseSeverity(str, Enum):
    MILD = "MILD"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class ScopeReviewOutcome(str, Enum):
    CLEARED = "CLEARED"
    RESTRICTED = "RESTRICTED"


# --------------------------------------------------------------------------- #
# Entity shapes
#
# Every resource carries id + created_at. All but LabResult additionally carry
# updated_at and version; LabResult is an immutable observation and carries
# neither.
# --------------------------------------------------------------------------- #
class Practitioner(TypedDict):
    id: str
    full_name: str
    credential: str
    npi: Optional[str]
    licensed_state_codes: List[str]
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    full_name: str
    email: str
    state_code: str
    primary_practitioner_id: str
    telehealth_consent: bool
    medication_classes: List[str]
    clinical_status: str
    scope_review_status: str
    scope_review_reason: Optional[str]
    scope_review_opened_by_user_id: Optional[str]
    intake_booking_score: int
    intake_protocol_score: int
    clinical_write_gate: str
    red_flag_referral_open: bool
    cash_charged_total_cents: int
    cash_refunded_total_cents: int
    created_at: str
    updated_at: str
    version: int


class IntakeSection(TypedDict):
    id: str
    patient_id: str
    section_type: str
    payload_summary: str
    status: str
    weight: int
    submitted_at: str
    attested_at: Optional[str]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    patient_id: str
    tier: str
    status: str
    cycle_start_date: str
    cycle_end_date: str
    cycle_index: int
    paused_at: Optional[str]
    paused_days_total: int
    monthly_fee_cents: int
    dispensary_discount_pct: float
    includes_messaging: bool
    visits_granted: int
    visits_consumed: int
    visits_remaining: int
    visits_forfeited: int
    lab_credits_granted: int
    lab_credits_consumed: int
    lab_credits_remaining: int
    lab_credits_forfeited: int
    last_proration_net_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class LabOrder(TypedDict):
    id: str
    patient_id: str
    ordering_practitioner_id: str
    panel_code: str
    specimen_type: str
    status: str
    funding_source: str
    price_cents: int
    lab_credit_cost: int
    requested_collection_date: str
    fasting_attested: bool
    cycle_day: Optional[int]
    washout_class: Optional[str]
    washout_clearance_date: Optional[str]
    collected_at: Optional[str]
    has_critical_result: bool
    interpretation_summary: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LabResult(TypedDict):
    """Immutable observation: carries id and created_at only."""

    id: str
    lab_order_id: str
    analyte_code: str
    value: float
    unit: str
    standard_low: float
    standard_high: float
    optimal_low: float
    optimal_high: float
    critical_low: float
    critical_high: float
    standard_band: str
    optimal_band: str
    is_critical: bool
    created_at: str


class Protocol(TypedDict):
    id: str
    patient_id: str
    practitioner_id: str
    supersedes_protocol_id: Optional[str]
    title: str
    version_no: int
    status: str
    symptom_score_baseline: int
    advancement_blocked: bool
    interaction_flags: list
    issued_at: Optional[str]
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProtocolItem(TypedDict):
    id: str
    protocol_id: str
    product_id: str
    dose_amount_mg: float
    frequency_per_day: int
    duration_days: int
    titration_interval_days: int
    status: str
    titration_step_no: int
    last_decision: Optional[str]
    last_decision_at: Optional[str]
    next_review_due_at: Optional[str]
    titration_locked: bool
    last_dose_date: Optional[str]
    discontinue_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DispensaryProduct(TypedDict):
    id: str
    sku: str
    name: str
    supplement_class: str
    retail_price_cents: int
    practitioner_cost_cents: int
    interacts_with_med_classes: List[str]
    interaction_severity: str
    stock_on_hand: int
    created_at: str
    updated_at: str
    version: int


class ProductLot(TypedDict):
    id: str
    product_id: str
    lot_code: str
    quantity_initial: int
    quantity_on_hand: int
    expiry_date: str
    is_quarantined: bool
    is_expired: bool
    created_at: str
    updated_at: str
    version: int


class Dispense(TypedDict):
    id: str
    patient_id: str
    protocol_item_id: str
    product_lot_id: str
    dispensed_by_practitioner_id: str
    quantity: int
    pricing_variant: str
    unit_price_cents: int
    total_price_cents: int
    status: str
    dispensed_at: str
    professional_sample: bool
    reversed_at: Optional[str]
    reversal_reason: Optional[str]
    reversal_authorized_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Encounter(TypedDict):
    id: str
    patient_id: str
    practitioner_id: str
    source_thread_id: Optional[str]
    modality: str
    scheduled_start: str
    scheduled_end: str
    scheduling_status: str
    billing_status: str
    duration_minutes: Optional[int]
    service_code: Optional[str]
    diagnosis_codes: List[str]
    base_fee_cents: int
    extended_block_count: int
    cash_charged_cents: int
    entitlement_consumed: bool
    completed_at: Optional[str]
    cancelled_at: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MessageThread(TypedDict):
    id: str
    patient_id: str
    practitioner_id: str
    subject: str
    status: str
    patient_message_count: int
    clinician_message_count: int
    clinical_minutes_total: int
    opened_at: str
    sla_due_at: str
    first_clinical_reply_at: Optional[str]
    sla_breached: bool
    evisit_conversion_eligible: bool
    created_at: str
    updated_at: str
    version: int


class Superbill(TypedDict):
    id: str
    patient_id: str
    encounter_id: str
    revision_no: int
    status: str
    diagnosis_codes: List[str]
    service_code: Optional[str]
    rendering_practitioner_npi: Optional[str]
    billable_total_cents: int
    non_billable_membership_cents: int
    excluded_supplement_cents: int
    denial_code: Optional[str]
    denial_reason: Optional[str]
    appeal_narrative: Optional[str]
    void_reason: Optional[str]
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    patient_id: str
    referring_practitioner_id: str
    lab_order_id: Optional[str]
    referral_type: str
    recipient_name: str
    specialty: str
    reason: str
    status: str
    attempt_no: int
    due_by_date: str
    acknowledged_at: Optional[str]
    report_summary: Optional[str]
    report_received_at: Optional[str]
    closed_at: Optional[str]
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
