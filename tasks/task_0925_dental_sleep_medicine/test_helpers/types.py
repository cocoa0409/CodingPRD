"""Domain types: entity TypedDicts, status enums, role enum."""

from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SLEEP_PHYSICIAN = "SleepPhysician"
    DENTIST = "Dentist"
    LAB_TECHNICIAN = "LabTechnician"
    BILLING_SPECIALIST = "BillingSpecialist"
    CLINIC_COORDINATOR = "ClinicCoordinator"
    PATIENT = "Patient"


class ProviderType(str, Enum):
    SLEEP_PHYSICIAN = "SLEEP_PHYSICIAN"
    DENTIST = "DENTIST"
    DENTAL_LAB = "DENTAL_LAB"


class ProviderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PayerKind(str, Enum):
    MEDICAL = "MEDICAL"
    DENTAL = "DENTAL"


class Modality(str, Enum):
    HSAT = "HSAT"
    PSG = "PSG"


class StudyPurpose(str, Enum):
    DIAGNOSTIC = "DIAGNOSTIC"
    EFFICACY = "EFFICACY"


class SleepStudyStatus(str, Enum):
    ORDERED = "ORDERED"
    DIAGNOSTIC_VALID = "DIAGNOSTIC_VALID"
    NON_DIAGNOSTIC = "NON_DIAGNOSTIC"


class SeverityBand(str, Enum):
    NONE = "NONE"
    MILD = "MILD"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class CpapHistory(str, Enum):
    NONE = "NONE"
    FAILURE = "FAILURE"
    INTOLERANCE = "INTOLERANCE"
    REFUSAL = "REFUSAL"


class EligibilityBasis(str, Enum):
    FIRST_LINE_MILD_MODERATE = "FIRST_LINE_MILD_MODERATE"
    CPAP_INTOLERANT_SEVERE = "CPAP_INTOLERANT_SEVERE"


class LoopStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ReferralStatus(str, Enum):
    ISSUED = "ISSUED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"


class Hcpcs(str, Enum):
    E0486 = "E0486"
    A9270 = "A9270"
    K0739 = "K0739"


class WrittenOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    SUPERSEDED = "SUPERSEDED"


class DenialReason(str, Enum):
    NOT_MEDICALLY_NECESSARY = "NOT_MEDICALLY_NECESSARY"
    MISSING_DOCUMENTATION = "MISSING_DOCUMENTATION"
    NON_COVERED_ITEM = "NON_COVERED_ITEM"


class PriorAuthStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    DENIED_FINAL = "DENIED_FINAL"
    EXPIRED = "EXPIRED"


class ApplianceKind(str, Enum):
    CUSTOM_FABRICATED = "CUSTOM_FABRICATED"
    PREFABRICATED = "PREFABRICATED"


class CaptureMethod(str, Enum):
    PVS_IMPRESSION = "PVS_IMPRESSION"
    DIGITAL_SCAN = "DIGITAL_SCAN"


class LabOrderStatus(str, Enum):
    RECORDS_CAPTURED = "RECORDS_CAPTURED"
    IN_FABRICATION = "IN_FABRICATION"
    SHIPPED = "SHIPPED"
    RECEIVED_ACCEPTED = "RECEIVED_ACCEPTED"
    REMAKE_REQUIRED = "REMAKE_REQUIRED"
    CANCELLED = "CANCELLED"


class RecallSeverity(str, Enum):
    CLASS_I = "CLASS_I"
    CLASS_II = "CLASS_II"
    CLASS_III = "CLASS_III"


class ApplianceLotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RECALL_ISSUED = "RECALL_ISSUED"
    REMEDIATION_COMPLETE = "REMEDIATION_COMPLETE"


class LifecycleStatus(str, Enum):
    FABRICATED = "FABRICATED"
    DELIVERED = "DELIVERED"
    IN_TITRATION = "IN_TITRATION"
    TITRATION_SUSPENDED = "TITRATION_SUSPENDED"
    TITRATION_PLATEAU = "TITRATION_PLATEAU"
    EFFICACY_PENDING = "EFFICACY_PENDING"
    ACTIVE_THERAPY = "ACTIVE_THERAPY"
    RETIRED = "RETIRED"
    REPLACED = "REPLACED"


class DeviceHoldStatus(str, Enum):
    NONE = "NONE"
    RECALL_HOLD = "RECALL_HOLD"


class RecallStatus(str, Enum):
    NOT_SCHEDULED = "NOT_SCHEDULED"
    NOT_DUE = "NOT_DUE"
    DUE = "DUE"
    LAPSED = "LAPSED"


class PodMethod(str, Enum):
    IN_PERSON = "IN_PERSON"
    SHIPPED = "SHIPPED"


class SideEffectSeverity(str, Enum):
    NONE = "NONE"
    MILD = "MILD"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class TitrationVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    APPLIED = "APPLIED"
    REDUCED = "REDUCED"
    HELD = "HELD"
    SUPERSEDED = "SUPERSEDED"
    VOIDED_BY_HOLD = "VOIDED_BY_HOLD"


class AdherenceSource(str, Enum):
    OBJECTIVE_MICRORECORDER = "OBJECTIVE_MICRORECORDER"
    PATIENT_ATTESTED = "PATIENT_ATTESTED"


class EfficacyOutcome(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class EfficacyReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SIGNED = "SIGNED"
    DISPUTED = "DISPUTED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"


class ClaimType(str, Enum):
    INITIAL_DEVICE = "INITIAL_DEVICE"
    REPAIR = "REPAIR"
    REPLACEMENT = "REPLACEMENT"
    CONTINUED_USE = "CONTINUED_USE"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    DENIED_FINAL = "DENIED_FINAL"
    VOIDED = "VOIDED"


class RepairReason(str, Enum):
    DEFECT = "DEFECT"
    WEAR = "WEAR"
    ABUSE = "ABUSE"
    LOSS = "LOSS"


class RepairOrderStatus(str, Enum):
    OPEN = "OPEN"
    IN_LAB = "IN_LAB"
    CLOSED_REPAIRED = "CLOSED_REPAIRED"
    CLOSED_NOT_COVERED = "CLOSED_NOT_COVERED"


class AuditHoldStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


# ---------------------------------------------------------------------------
# Entity shapes.  Every entity below carries id / created_at / updated_at /
# version except AdherenceDownload, which carries only id and created_at.
# ---------------------------------------------------------------------------


class Provider(TypedDict):
    id: str
    npi: str
    full_name: str
    provider_type: str
    state_license: str
    dme_supplier_number: Optional[str]
    status: str
    open_efficacy_loop_count: int
    created_at: str
    updated_at: str
    version: int


class Payer(TypedDict):
    id: str
    name: str
    payer_kind: str
    prior_auth_required: bool
    useful_lifetime_months: int
    coinsurance_pct: float
    appeal_limit: int
    residual_ahi_target: float
    pct_reduction_target: float
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    mrn: str
    full_name: str
    date_of_birth: str
    medical_payer_id: str
    dental_payer_id: Optional[str]
    deductible_remaining_cents: int
    epworth_score: int
    records_frozen: bool
    created_at: str
    updated_at: str
    version: int


class SleepStudy(TypedDict):
    id: str
    patient_id: str
    ordering_physician_id: str
    appliance_id: Optional[str]
    modality: str
    study_purpose: str
    performed_on: Optional[str]
    respiratory_events: Optional[int]
    recording_minutes: Optional[int]
    sleep_minutes: Optional[int]
    artifact_pct: Optional[float]
    attended: Optional[bool]
    severity_index: Optional[float]
    severity_band: Optional[str]
    repeat_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    patient_id: str
    referring_physician_id: str
    treating_dentist_id: str
    diagnostic_study_id: str
    cpap_history: str
    cpap_nights_used: int
    cpap_documented_on: Optional[str]
    severity_band_at_referral: Optional[str]
    eligibility_basis: Optional[str]
    diagnosis_valid_until: Optional[str]
    loop_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WrittenOrder(TypedDict):
    id: str
    patient_id: str
    ordering_physician_id: str
    item_hcpcs: str
    order_date: str
    f2f_encounter_date: str
    signed_on: Optional[str]
    f2f_age_days: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class PriorAuth(TypedDict):
    id: str
    patient_id: str
    payer_id: str
    referral_id: str
    requested_hcpcs: str
    submitted_on: str
    decided_on: Optional[str]
    approval_valid_until: Optional[str]
    denial_reason: Optional[str]
    appeal_attempts: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LabOrder(TypedDict):
    id: str
    referral_id: str
    lab_provider_id: str
    appliance_kind: str
    capture_method: str
    max_protrusive_mm: float
    retruded_position_mm: float
    promised_turnaround_days: int
    submitted_on: Optional[str]
    promised_ship_date: Optional[str]
    shipped_on: Optional[str]
    turnaround_on_time: Optional[bool]
    remake_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ApplianceLot(TypedDict):
    id: str
    manufacturer: str
    lot_code: str
    material: str
    notice_reference: Optional[str]
    recall_severity: Optional[str]
    recall_issued_on: Optional[str]
    affected_device_count: int
    remediated_count: int
    pending_remediation_count: int
    retired_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appliance(TypedDict):
    id: str
    patient_id: str
    lab_order_id: str
    lot_id: str
    replaces_appliance_id: Optional[str]
    serial_number: str
    has_microrecorder: bool
    appliance_kind: str
    hcpcs_code: str
    max_protrusive_mm: float
    delivered_on: Optional[str]
    written_order_id: Optional[str]
    pod_signed_on: Optional[str]
    pod_method: Optional[str]
    warranty_end_date: Optional[str]
    useful_lifetime_end_date: Optional[str]
    starting_advancement_mm: Optional[float]
    current_advancement_mm: Optional[float]
    applied_visit_count: int
    plateau_declared_on: Optional[str]
    next_recall_due_on: Optional[str]
    recall_cycle_index: int
    lifecycle_status: str
    device_hold_status: str
    recall_status: str
    created_at: str
    updated_at: str
    version: int


class TitrationVisit(TypedDict):
    id: str
    appliance_id: str
    performed_by_dentist_id: str
    visit_seq: int
    scheduled_for: str
    requested_increment_mm: float
    side_effect_severity: Optional[str]
    applied_increment_mm: Optional[float]
    applied_on: Optional[str]
    days_since_prior_applied: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class AdherenceDownload(TypedDict):
    """Immutable observation: id and created_at only, no updated_at, no version."""

    id: str
    appliance_id: str
    source: str
    window_start: str
    window_end: str
    nights_recorded: int
    nights_at_or_above_min_hours: int
    mean_hours_per_worn_night: float
    rate_of_window: float
    rate_of_recorded: Optional[float]
    compliant: bool
    created_at: str


class EfficacyReport(TypedDict):
    id: str
    patient_id: str
    referral_id: str
    appliance_id: str
    efficacy_study_id: str
    baseline_index: float
    residual_index: float
    pct_reduction: float
    meets_absolute_target: bool
    meets_relative_target: bool
    outcome: str
    due_by: Optional[str]
    submitted_on: Optional[str]
    physician_decision_on: Optional[str]
    dispute_reason: Optional[str]
    revision_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    patient_id: str
    payer_id: str
    appliance_id: str
    prior_auth_id: Optional[str]
    written_order_id: Optional[str]
    repair_order_id: Optional[str]
    claim_type: str
    hcpcs_code: str
    date_of_service: str
    billed_cents: int
    allowed_cents: Optional[int]
    deductible_applied_cents: Optional[int]
    coinsurance_cents: Optional[int]
    patient_responsibility_cents: Optional[int]
    payer_paid_cents: Optional[int]
    adjustment_cents: Optional[int]
    denial_error_id: Optional[str]
    appeal_attempts: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RepairOrder(TypedDict):
    id: str
    appliance_id: str
    loaner_appliance_id: Optional[str]
    reason: str
    reported_on: str
    labor_minutes: int
    returned_on: Optional[str]
    in_warranty: bool
    billable: bool
    labor_units: int
    repair_charge_cents: int
    resets_useful_lifetime: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditHold(TypedDict):
    id: str
    patient_id: str
    payer_id: str
    opened_on: str
    closed_on: Optional[str]
    scope_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
