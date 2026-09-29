"""Domain types for the Cord Blood Banking & Unit Release API.

Status enums, role enum and entity TypedDicts, all named exactly as the PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    INTAKE_COORDINATOR = "IntakeCoordinator"
    PARENT_GUARDIAN = "ParentGuardian"
    COLLECTION_SITE = "CollectionSite"
    PROCESSING_TECHNOLOGIST = "ProcessingTechnologist"
    MEDICAL_DIRECTOR = "MedicalDirector"
    REGISTRY_OPERATOR = "RegistryOperator"
    TRANSPLANT_CENTER = "TransplantCenter"
    BILLING_ADMINISTRATOR = "BillingAdministrator"
    FACILITIES_ENGINEER = "FacilitiesEngineer"
    PLATFORM_ADMIN = "PlatformAdmin"


ALL_ROLE_NAMES = [r.value for r in UserRole]


class ProgramType(str, Enum):
    PRIVATE_FAMILY = "PRIVATE_FAMILY"
    PUBLIC_DONATION = "PUBLIC_DONATION"


class EnrollmentLifecycleStatus(str, Enum):
    CONSENT_PENDING = "CONSENT_PENDING"
    ACTIVE = "ACTIVE"
    KIT_DISPATCHED = "KIT_DISPATCHED"
    COLLECTED = "COLLECTED"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class EnrollmentConsentStatus(str, Enum):
    PENDING = "PENDING"
    CONSENTED = "CONSENTED"
    AMENDMENT_PENDING = "AMENDMENT_PENDING"
    REVOKED = "REVOKED"


class CollectionKitStatus(str, Enum):
    DISPATCHED = "DISPATCHED"
    HELD = "HELD"
    USED = "USED"
    EXPIRED = "EXPIRED"
    RETURNED = "RETURNED"


class CollectionStatus(str, Enum):
    COLLECTED = "COLLECTED"
    RECEIVED = "RECEIVED"
    REJECTED_LATE = "REJECTED_LATE"
    REJECTED_TEMP = "REJECTED_TEMP"
    REJECTED_VOLUME = "REJECTED_VOLUME"
    DISCARDED = "DISCARDED"


class DeliveryMode(str, Enum):
    VAGINAL = "VAGINAL"
    CESAREAN = "CESAREAN"


class UnitProcessingStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    VOLUME_REDUCED = "VOLUME_REDUCED"
    CRYOPRESERVED = "CRYOPRESERVED"
    DISCARDED = "DISCARDED"


class UnitAvailabilityStatus(str, Enum):
    UNAVAILABLE = "UNAVAILABLE"
    PRIVATE_STORED = "PRIVATE_STORED"
    LISTED = "LISTED"
    RESERVED = "RESERVED"
    QUARANTINED = "QUARANTINED"
    PENDING_ABANDONMENT = "PENDING_ABANDONMENT"
    RELEASED = "RELEASED"
    DISPOSED = "DISPOSED"


class UnitEligibilityStatus(str, Enum):
    PENDING = "PENDING"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    INDETERMINATE = "INDETERMINATE"


class ProcessingRunStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ProcessingMethod(str, Enum):
    HES_SEDIMENTATION = "HES_SEDIMENTATION"
    AUTOMATED_SEPARATION = "AUTOMATED_SEPARATION"


class QualityTestKind(str, Enum):
    POST_PROCESSING = "POST_PROCESSING"
    CONFIRMATORY = "CONFIRMATORY"


class SterilityResult(str, Enum):
    NEGATIVE = "NEGATIVE"
    POSITIVE = "POSITIVE"
    PENDING = "PENDING"


class QualityTestOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class SerologyResult(str, Enum):
    NON_REACTIVE = "NON_REACTIVE"
    REACTIVE = "REACTIVE"
    INDETERMINATE = "INDETERMINATE"
    PENDING = "PENDING"


class MaternalScreeningStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    INVALID = "INVALID"
    EXPIRED = "EXPIRED"


class StorageTankStatus(str, Enum):
    ONLINE = "ONLINE"
    ALARM = "ALARM"
    MAINTENANCE = "MAINTENANCE"
    OFFLINE = "OFFLINE"


class TankClass(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class ExcursionStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    CLOSED_LOSS = "CLOSED_LOSS"


class ExcursionDisposition(str, Enum):
    NO_IMPACT = "NO_IMPACT"
    REQUALIFY = "REQUALIFY"
    TOTAL_LOSS = "TOTAL_LOSS"


class ListingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    MATCHED = "MATCHED"
    WITHDRAWN = "WITHDRAWN"


class SuspensionReasonCode(str, Enum):
    UNIT_QUARANTINED = "UNIT_QUARANTINED"
    CONSENT_AMENDMENT_PENDING = "CONSENT_AMENDMENT_PENDING"
    MATERNAL_REACTIVE = "MATERNAL_REACTIVE"
    SCREENING_EXPIRED = "SCREENING_EXPIRED"
    REGISTRY_HOLD = "REGISTRY_HOLD"


class PotencyGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class StorageAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    DELINQUENT = "DELINQUENT"
    ABANDONMENT_NOTICE = "ABANDONMENT_NOTICE"
    ABANDONED = "ABANDONED"
    CLOSED = "CLOSED"


class StorageInvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAST_DUE = "PAST_DUE"
    DELINQUENT = "DELINQUENT"
    PAID = "PAID"
    VOID = "VOID"
    WRITTEN_OFF = "WRITTEN_OFF"


class ReservationStatus(str, Enum):
    PENDING_CONFIRMATORY = "PENDING_CONFIRMATORY"
    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    RELEASED = "RELEASED"


class DoseVariant(str, Enum):
    PRE_CRYO = "PRE_CRYO"
    POST_THAW = "POST_THAW"


class DispositionReason(str, Enum):
    ABANDONED_NONPAYMENT = "ABANDONED_NONPAYMENT"
    QUALITY_FAILURE = "QUALITY_FAILURE"
    MATERNAL_INELIGIBLE = "MATERNAL_INELIGIBLE"
    CONSENT_REVOKED = "CONSENT_REVOKED"
    EXCURSION_LOSS = "EXCURSION_LOSS"
    TRANSPLANT_RELEASED = "TRANSPLANT_RELEASED"


# --- Entity shapes ---------------------------------------------------------


class Enrollment(TypedDict):
    id: str
    program_type: str
    primary_parent_name: str
    expected_delivery_date: str
    collection_site_code: str
    research_use_authorized: bool
    hla_typing_consent: bool
    lifecycle_status: str
    consent_status: str
    consent_version: int
    consent_amendment_count: int
    consent_signed_at: Optional[str]
    withdrawal_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StorageAccount(TypedDict):
    id: str
    enrollment_id: str
    billing_contact_email: str
    plan_term_years: int
    prepaid_through_date: str
    paid_through_date: str
    status: str
    balance_cents: int
    lifetime_paid_cents: int
    last_settlement_total_cents: Optional[int]
    delinquency_stage_entered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CollectionKit(TypedDict):
    id: str
    enrollment_id: str
    kit_lot_code: str
    courier_tracking_code: str
    dispatched_at: str
    expires_at: str
    status: str
    hold_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Collection(TypedDict):
    id: str
    kit_id: str
    collected_at: str
    collection_volume_ml: float
    anticoagulant_volume_ml: float
    delivery_mode: str
    transport_temp_c: Optional[float]
    net_volume_ml: float
    received_at: Optional[str]
    hours_to_receipt: Optional[float]
    status: str
    rejection_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CordBloodUnit(TypedDict):
    id: str
    collection_id: str
    tank_id: Optional[str]
    storage_account_id: Optional[str]
    unit_registry_code: str
    program_type: str
    processing_status: str
    availability_status: str
    eligibility_status: str
    eligibility_reason_code: Optional[str]
    eligibility_determined_by_user_id: Optional[str]
    post_processing_volume_ml: Optional[float]
    post_processing_tnc_millions: Optional[int]
    post_processing_cd34_thousands: Optional[int]
    post_processing_viability_pct: Optional[float]
    quality_acceptance_score: Optional[float]
    slot_code: Optional[str]
    cryopreserved_at: Optional[str]
    quarantine_reason_code: Optional[str]
    disposition_reason: Optional[str]
    disposed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProcessingRun(TypedDict):
    id: str
    unit_id: str
    method: str
    pre_tnc_millions: int
    pre_volume_ml: float
    post_volume_ml: Optional[float]
    post_tnc_millions: Optional[int]
    tnc_recovery_pct: Optional[float]
    volume_reduction_pct: Optional[float]
    started_at: str
    completed_at: Optional[str]
    operator_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class QualityTest(TypedDict):
    """A quality test record is immutable once written: it carries only
    ``id`` and ``created_at`` from the audit fields — no ``updated_at``,
    no ``version``.
    """

    id: str
    unit_id: str
    test_kind: str
    tnc_millions: int
    cd34_thousands: int
    viability_pct: float
    volume_ml: float
    sterility_result: str
    performed_at: str
    performed_by_user_id: str
    outcome: str
    failure_reason_codes: List[str]
    created_at: str


class MaternalScreening(TypedDict):
    id: str
    enrollment_id: str
    collected_at: str
    hiv_result: str
    hbv_result: str
    hcv_result: str
    htlv_result: str
    syphilis_result: str
    cmv_result: Optional[str]
    nat_confirmed: bool
    overall_result: Optional[str]
    reactive_marker_codes: List[str]
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class StorageTank(TypedDict):
    id: str
    tank_code: str
    tank_class: str
    capacity_slots: int
    maintenance_window_start: Optional[str]
    maintenance_window_end: Optional[str]
    occupied_slots: int
    status: str
    last_temperature_c: Optional[float]
    last_reading_at: Optional[str]
    cumulative_excursion_minutes_30d: int
    created_at: str
    updated_at: str
    version: int


class TemperatureExcursion(TypedDict):
    id: str
    tank_id: str
    detected_at: str
    peak_temperature_c: Optional[float]
    acknowledged_at: Optional[str]
    acknowledged_by_user_id: Optional[str]
    resolved_at: Optional[str]
    duration_minutes: Optional[int]
    disposition: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RegistryListing(TypedDict):
    id: str
    unit_id: str
    registry_code: str
    hla_a: str
    hla_b: str
    hla_drb1: str
    listed_at: str
    potency_grade: str
    listing_status: str
    suspension_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StorageInvoice(TypedDict):
    id: str
    account_id: str
    billing_period_start: str
    billing_period_end: str
    prorated_days: int
    due_date: str
    base_line_cents: int
    surcharge_line_cents: int
    admin_line_cents: int
    late_fee_line_cents: int
    amount_due_cents: int
    amount_paid_cents: int
    stage_advanced_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    unit_id: str
    superseded_by_reservation_id: Optional[str]
    confirmatory_test_id: Optional[str]
    requesting_center_user_id: str
    requesting_center_name: str
    patient_weight_kg: float
    patient_hla_match_count: int
    hold_from: str
    hold_until: str
    intended_transplant_date: Optional[str]
    pre_cryo_dose_x1e7_per_kg: Optional[float]
    post_thaw_dose_x1e7_per_kg: Optional[float]
    dose_variant_applied: Optional[str]
    settlement_total_cents: Optional[int]
    released_at: Optional[str]
    cancellation_reason_code: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
