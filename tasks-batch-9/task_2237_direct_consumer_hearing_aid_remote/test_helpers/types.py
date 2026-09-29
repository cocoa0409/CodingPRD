"""Domain types: status enums, entity TypedDicts, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PATIENT = "Patient"
    HEARING_PROFESSIONAL = "HearingProfessional"
    LICENSED_AUDIOLOGIST = "LicensedAudiologist"
    CARE_OPS_AGENT = "CareOpsAgent"
    REIMBURSEMENT_SPECIALIST = "ReimbursementSpecialist"
    REPAIR_TECHNICIAN = "RepairTechnician"
    FIRMWARE_ENGINEER = "FirmwareEngineer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class PatientStatus(str, Enum):
    REGISTERED = "REGISTERED"
    SCREENING_IN_PROGRESS = "SCREENING_IN_PROGRESS"
    CANDIDATE_APPROVED = "CANDIDATE_APPROVED"
    REFERRAL_REQUIRED = "REFERRAL_REQUIRED"
    PROVIDER_CLEARED = "PROVIDER_CLEARED"
    MEDICALLY_DISQUALIFIED = "MEDICALLY_DISQUALIFIED"
    DEACTIVATED = "DEACTIVATED"


class ScreeningSessionStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    SCORED = "SCORED"
    INVALIDATED = "INVALIDATED"


class ScreeningOutcome(str, Enum):
    PASS = "PASS"
    ADVISORY_PASS = "ADVISORY_PASS"
    RED_FLAG = "RED_FLAG"


class CandidacyRiskBand(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class CandidacyRiskVariant(str, Enum):
    PROVISIONAL_SELF_REPORTED = "PROVISIONAL_SELF_REPORTED"
    PROVIDER_ADJUSTED = "PROVIDER_ADJUSTED"


class RedFlagSeverity(str, Enum):
    MANDATORY_REFERRAL = "MANDATORY_REFERRAL"
    ADVISORY = "ADVISORY"


class ProviderType(str, Enum):
    TELECARE_FITTER = "TELECARE_FITTER"
    LICENSED_AUDIOLOGIST = "LICENSED_AUDIOLOGIST"


class ProviderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ProviderReferralStatus(str, Enum):
    OPEN = "OPEN"
    SCHEDULED = "SCHEDULED"
    EVALUATED = "EVALUATED"
    CLEARED = "CLEARED"
    NOT_CLEARED = "NOT_CLEARED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class RemoteFittingSessionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class SessionType(str, Enum):
    INITIAL_FIT = "INITIAL_FIT"
    FOLLOW_UP = "FOLLOW_UP"
    REFERRAL_EVALUATION = "REFERRAL_EVALUATION"


class PaymentStatus(str, Enum):
    PENDING_AUTH = "PENDING_AUTH"
    AUTHORIZED = "AUTHORIZED"
    AUTH_FAILED = "AUTH_FAILED"
    CAPTURED = "CAPTURED"
    VOIDED = "VOIDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(str, Enum):
    PENDING_FIT_CONFIRM = "PENDING_FIT_CONFIRM"
    READY_TO_SHIP = "READY_TO_SHIP"
    MEDICAL_HOLD = "MEDICAL_HOLD"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    RETURN_IN_TRANSIT = "RETURN_IN_TRANSIT"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class DeviceStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    ASSIGNED = "ASSIGNED"
    WITH_PATIENT = "WITH_PATIENT"
    IN_REPAIR = "IN_REPAIR"
    RETIRED = "RETIRED"
    REPLACED = "REPLACED"
    LOST = "LOST"


class TrialPeriodStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    RETURN_INITIATED = "RETURN_INITIATED"
    RETURN_SETTLED = "RETURN_SETTLED"
    EXPIRED_KEPT = "EXPIRED_KEPT"
    VOIDED = "VOIDED"


class ReturnAuthorizationStatus(str, Enum):
    ISSUED = "ISSUED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    INSPECTED = "INSPECTED"
    REFUND_SETTLED = "REFUND_SETTLED"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class InspectionGrade(str, Enum):
    RESELLABLE = "RESELLABLE"
    REFURBISHABLE = "REFURBISHABLE"
    DAMAGED = "DAMAGED"


class RestockingVariant(str, Enum):
    FLAT_PCT = "FLAT_PCT"
    PRORATED_DAILY = "PRORATED_DAILY"
    WAIVED = "WAIVED"


class RestockingFeeMode(str, Enum):
    FLAT_PCT = "FLAT_PCT"
    PRORATED_DAILY = "PRORATED_DAILY"
    PROHIBITED = "PROHIBITED"


class FitExchangeStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RESERVED = "RESERVED"
    REJECTED = "REJECTED"
    SHIPPED = "SHIPPED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RepairOrderStatus(str, Enum):
    KIT_REQUESTED = "KIT_REQUESTED"
    KIT_SENT = "KIT_SENT"
    RECEIVED = "RECEIVED"
    IN_REPAIR = "IN_REPAIR"
    REPAIRED = "REPAIRED"
    UNREPAIRABLE = "UNREPAIRABLE"
    RETURNED_TO_PATIENT = "RETURNED_TO_PATIENT"
    ESCALATED_TO_WARRANTY = "ESCALATED_TO_WARRANTY"
    CANCELLED = "CANCELLED"


class WarrantyClaimStatus(str, Enum):
    FILED = "FILED"
    TRIAGED = "TRIAGED"
    APPROVED_REPLACEMENT = "APPROVED_REPLACEMENT"
    APPROVED_REPAIR = "APPROVED_REPAIR"
    DENIED = "DENIED"
    FULFILLED = "FULFILLED"
    WITHDRAWN = "WITHDRAWN"


class WarrantyClaimKind(str, Enum):
    DEFECT = "DEFECT"
    DAMAGE = "DAMAGE"
    LOSS = "LOSS"


class ReimbursementClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class ReimbursementSubjectKind(str, Enum):
    DEVICE_ORDER = "DEVICE_ORDER"
    REPAIR = "REPAIR"
    CARE_PLAN = "CARE_PLAN"


class CarePlanSubscriptionStatus(str, Enum):
    TRIALING = "TRIALING"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class PlanTier(str, Enum):
    BASIC = "BASIC"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class FirmwareCampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    ROLLING = "ROLLING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class FirmwareRolloutStatus(str, Enum):
    PENDING = "PENDING"
    OFFERED = "OFFERED"
    INSTALLING = "INSTALLING"
    INSTALLED = "INSTALLED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"
    CANCELLED_INELIGIBLE = "CANCELLED_INELIGIBLE"


class ComplianceOverrideStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------
class StatePolicy(TypedDict, total=False):
    id: str
    state_code: str
    otc_sales_permitted: bool
    telehealth_fitting_permitted: bool
    min_age_years: int
    trial_period_days: int
    restocking_fee_mode: str
    restocking_fee_pct: float
    restocking_daily_rate_cents: int
    restocking_fee_cap_cents: int
    shipping_refundable: bool
    referral_validity_days: int
    waiver_required: bool
    max_loss_damage_claims: int
    is_retired: bool
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict, total=False):
    id: str
    state_policy_id: str
    state_code: str
    email: str
    full_name: str
    age_years: int
    status: str
    waiver_acknowledged_at: Optional[str]
    candidacy_risk_score: float
    candidacy_risk_variant: Optional[str]
    candidacy_risk_band: str
    advisory_weight_total: float
    open_mandatory_flag_count: int
    lifetime_return_count: int
    screening_attempt_count: int
    deactivated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScreeningSession(TypedDict, total=False):
    id: str
    patient_id: str
    supersedes_session_id: Optional[str]
    status: str
    attempt_ordinal: int
    pure_tone_avg_db: float
    asymmetry_db: float
    self_reported_difficulty_score: int
    speech_in_noise_pct: float
    symptom_codes: List[str]
    screening_outcome: Optional[str]
    submitted_at: Optional[str]
    scored_at: Optional[str]
    invalidated_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RedFlagFinding(TypedDict, total=False):
    """Append-only screening event: carries only id and created_at as common fields."""
    id: str
    screening_session_id: str
    cleared_by_referral_id: Optional[str]
    code: str
    severity: str
    weight: float
    detected_at: str
    created_at: str


class Provider(TypedDict, total=False):
    id: str
    provider_type: str
    npi: str
    full_name: str
    licensed_state_codes: List[str]
    status: str
    daily_capacity_minutes: int
    buffer_minutes: int
    booked_minutes_on_focus_date: int
    utilization_pct: float
    completed_session_count: int
    created_at: str
    updated_at: str
    version: int


class ProviderReferral(TypedDict, total=False):
    id: str
    patient_id: str
    triggering_screening_session_id: str
    provider_id: Optional[str]
    status: str
    reason_codes: List[str]
    issued_at: str
    expires_at: str
    reschedule_count: int
    clearance_outcome: Optional[str]
    clearance_note: Optional[str]
    cleared_finding_count: int
    created_at: str
    updated_at: str
    version: int


class RemoteFittingSession(TypedDict, total=False):
    id: str
    patient_id: str
    provider_id: Optional[str]
    device_order_id: Optional[str]
    provider_referral_id: Optional[str]
    session_type: str
    status: str
    scheduled_start_utc: Optional[str]
    scheduled_end_utc: Optional[str]
    duration_minutes: int
    programming_profile: Optional[str]
    no_show_charged_cents: int
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeviceOrder(TypedDict, total=False):
    id: str
    patient_id: str
    state_policy_id: str
    pinned_state_policy_version: int
    pinned_trial_days: int
    pinned_restocking_mode: str
    payment_status: str
    fulfillment_status: str
    model: str
    dome_size: str
    tip_type: str
    list_price_cents: int
    discount_cents: int
    accessory_subtotal_cents: int
    shipping_cents: int
    tax_cents: int
    total_cents: int
    captured_cents: int
    refunded_cents: int
    retained_cents: int
    open_balance_cents: int
    delivered_at: Optional[str]
    medical_hold_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Device(TypedDict, total=False):
    id: str
    serial_number: str
    device_order_id: Optional[str]
    model: str
    firmware_version: str
    status: str
    shipped_at: Optional[str]
    warranty_expires_at: Optional[str]
    age_months_at_last_claim: Optional[int]
    loss_damage_claims_approved: int
    replaced_by_device_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrialPeriod(TypedDict, total=False):
    id: str
    device_order_id: str
    patient_id: str
    status: str
    started_at: str
    nominal_end_utc: str
    effective_end_utc: str
    pause_intervals: list
    paused_days: int
    days_used: int
    extension_days_granted: int
    created_at: str
    updated_at: str
    version: int


class ReturnAuthorization(TypedDict, total=False):
    id: str
    trial_period_id: str
    rma_code: str
    status: str
    days_used_at_issue: int
    restocking_variant: Optional[str]
    inspection_grade: Optional[str]
    restocking_fee_cents: int
    non_refundable_shipping_cents: int
    refund_amount_cents: int
    received_at: Optional[str]
    settled_at: Optional[str]
    return_deadline_utc: str
    created_at: str
    updated_at: str
    version: int


class FitExchange(TypedDict, total=False):
    id: str
    device_order_id: str
    from_inventory_pool_id: Optional[str]
    to_inventory_pool_id: Optional[str]
    to_dome_size: str
    to_tip_type: str
    status: str
    exchange_ordinal: int
    exchange_fee_cents: int
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InventoryPool(TypedDict, total=False):
    id: str
    sku: str
    model: str
    dome_size: str
    tip_type: str
    on_hand_units: int
    reserved_units: int
    dispatched_units: int
    total_units_received: int
    is_discontinued: bool
    created_at: str
    updated_at: str
    version: int


class RepairOrder(TypedDict, total=False):
    id: str
    device_id: str
    patient_id: str
    care_plan_subscription_id: Optional[str]
    status: str
    fault_code: str
    sla_days: int
    received_at: Optional[str]
    closed_at: Optional[str]
    turnaround_days: Optional[int]
    sla_credit_cents: int
    pauses_trial: bool
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    device_id: str
    patient_id: str
    originating_repair_order_id: Optional[str]
    claim_kind: str
    status: str
    device_age_months: Optional[int]
    claim_ordinal: Optional[int]
    deductible_cents: int
    deductible_paid_cents: int
    replacement_device_id: Optional[str]
    denial_reason: Optional[str]
    triaged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReimbursementClaim(TypedDict, total=False):
    id: str
    patient_id: str
    subject_kind: str
    device_order_id: Optional[str]
    repair_order_id: Optional[str]
    care_plan_subscription_id: Optional[str]
    appeal_of_claim_id: Optional[str]
    status: str
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    document_codes: List[str]
    documentation_complete: bool
    claimed_amount_cents: int
    eligible_amount_cents: int
    insurance_benefit_cap_cents: int
    insurance_benefit_used_cents: int
    fsa_balance_cents: int
    insurance_paid_cents: int
    fsa_paid_cents: int
    patient_responsibility_cents: int
    info_request_count: int
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CarePlanSubscription(TypedDict, total=False):
    id: str
    patient_id: str
    device_order_id: str
    plan_tier: str
    status: str
    base_fee_cents: int
    cycle_ordinal: int
    cycle_start_utc: Optional[str]
    cycle_end_utc: Optional[str]
    last_charge_cents: int
    service_fee_cents: int
    loyalty_discount_cents: int
    credit_balance_cents: int
    dunning_attempts: int
    firmware_auto_update_enabled: bool
    created_at: str
    updated_at: str
    version: int


class FirmwareCampaign(TypedDict, total=False):
    id: str
    campaign_code: str
    model: str
    from_version: str
    to_version: str
    status: str
    window_start_utc: str
    window_end_utc: str
    max_concurrent_installs: int
    batch_size: int
    is_mandatory_safety: bool
    rollout_count: int
    installed_count: int
    failure_rate_pct: float
    created_at: str
    updated_at: str
    version: int


class FirmwareRollout(TypedDict, total=False):
    id: str
    firmware_campaign_id: str
    device_id: str
    status: str
    selection_rank: int
    from_version_observed: str
    attempt_count: int
    failure_code: Optional[str]
    installed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceOverride(TypedDict, total=False):
    id: str
    patient_id: str
    filed_by_user_id: str
    approved_by_user_id: Optional[str]
    justification: str
    status: str
    filed_at: str
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
