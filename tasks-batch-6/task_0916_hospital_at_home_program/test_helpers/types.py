"""Domain types for the Hospital-At-Home Program API.

Status enums, role names and entity shapes exactly as the PRD declares them.
"""

from enum import Enum
from typing import Optional, TypedDict


# ─── Roles (PRD §2.1) ──────────────────────────────────────────────────────

class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    ADMITTING_PHYSICIAN = "AdmittingPhysician"
    FIELD_NURSE = "FieldNurse"
    COMMUNITY_PARAMEDIC = "CommunityParamedic"
    PHARMACY_AUTHORIZER = "PharmacyAuthorizer"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    BILLING_ANALYST = "BillingAnalyst"
    PATIENT = "Patient"


# ─── Controlled vocabularies (PRD §2.10) ───────────────────────────────────

class DiagnosisCode(str, Enum):
    CHF_EXAC = "CHF_EXAC"
    COPD_EXAC = "COPD_EXAC"
    CAP_PNEUMONIA = "CAP_PNEUMONIA"
    CELLULITIS = "CELLULITIS"
    UTI_COMPLICATED = "UTI_COMPLICATED"
    COVID_MODERATE = "COVID_MODERATE"
    OTHER = "OTHER"


class DietCode(str, Enum):
    NONE = "NONE"
    LOW_SODIUM = "LOW_SODIUM"
    RENAL = "RENAL"
    CARB_CONTROLLED = "CARB_CONTROLLED"
    PUREED = "PUREED"


class PatientStatus(str, Enum):
    REGISTERED = "REGISTERED"
    IN_PROGRAM = "IN_PROGRAM"
    DISCHARGED = "DISCHARGED"


class ReferralOrigin(str, Enum):
    ED = "ED"
    INPATIENT_WARD = "INPATIENT_WARD"
    CLINIC = "CLINIC"
    SNF = "SNF"


class Acuity(str, Enum):
    STANDARD = "STANDARD"
    HIGH = "HIGH"


class ReferralStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SCREENING = "SCREENING"
    ELIGIBLE = "ELIGIBLE"
    ADMITTED = "ADMITTED"
    CLOSED = "CLOSED"


class HomeSafetyOutcome(str, Enum):
    PASS = "PASS"
    CONDITIONAL = "CONDITIONAL"
    FAIL = "FAIL"


class BroadbandCheck(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ProgramTrack(str, Enum):
    CMS_WAIVER = "CMS_WAIVER"
    FEE_FOR_SERVICE = "FEE_FOR_SERVICE"


class EpisodeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ESCALATED = "ESCALATED"
    RETURNED_TO_FACILITY = "RETURNED_TO_FACILITY"
    DISCHARGE_PENDING = "DISCHARGE_PENDING"
    DISCHARGED = "DISCHARGED"


class VisitType(str, Enum):
    RN_IN_PERSON = "RN_IN_PERSON"
    PARAMEDIC_IN_PERSON = "PARAMEDIC_IN_PERSON"
    PHYSICIAN_IN_PERSON = "PHYSICIAN_IN_PERSON"
    PHYSICIAN_TELEHEALTH = "PHYSICIAN_TELEHEALTH"


class SchedulingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EN_ROUTE = "EN_ROUTE"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class AttestationStatus(str, Enum):
    UNATTESTED = "UNATTESTED"
    ATTESTED = "ATTESTED"
    AMENDED = "AMENDED"


class ComplianceStatus(str, Enum):
    PENDING = "PENDING"
    COMPLIANT = "COMPLIANT"
    CARVED_OUT = "CARVED_OUT"


class CarveOutReason(str, Enum):
    INSUFFICIENT_IN_PERSON_VISITS = "INSUFFICIENT_IN_PERSON_VISITS"
    MISSING_PHYSICIAN_EVAL = "MISSING_PHYSICIAN_EVAL"
    MONITORING_LAPSE_EXCEEDED = "MONITORING_LAPSE_EXCEEDED"
    KIT_NOT_DEPLOYED = "KIT_NOT_DEPLOYED"


class KitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEPLOYED = "DEPLOYED"
    IN_REFURB = "IN_REFURB"
    RETIRED = "RETIRED"


class ComponentType(str, Enum):
    TABLET = "TABLET"
    BP_CUFF = "BP_CUFF"
    PULSE_OX = "PULSE_OX"
    SCALE = "SCALE"
    THERMOMETER = "THERMOMETER"
    GATEWAY = "GATEWAY"


class ReconciliationStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    DEPLOYED = "DEPLOYED"
    PENDING_RECONCILIATION = "PENDING_RECONCILIATION"
    RETURNED = "RETURNED"
    WRITTEN_OFF = "WRITTEN_OFF"


class LapseCause(str, Enum):
    DEVICE_OFFLINE = "DEVICE_OFFLINE"
    CONNECTIVITY_LOSS = "CONNECTIVITY_LOSS"
    PATIENT_REMOVED = "PATIENT_REMOVED"
    UNKNOWN = "UNKNOWN"


class OrderKind(str, Enum):
    MEDICATION = "MEDICATION"
    DME = "DME"


class DeliveryStatus(str, Enum):
    PENDING_AUTHORIZATION = "PENDING_AUTHORIZATION"
    AUTHORIZED = "AUTHORIZED"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    REFUSED = "REFUSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class MealPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EscalationReason(str, Enum):
    VITALS_OUT_OF_RANGE = "VITALS_OUT_OF_RANGE"
    PATIENT_REQUEST = "PATIENT_REQUEST"
    TELEMETRY_LOSS = "TELEMETRY_LOSS"
    MEDICATION_FAILURE = "MEDICATION_FAILURE"
    FALL = "FALL"


class EscalationStatus(str, Enum):
    TIER1_OPEN = "TIER1_OPEN"
    TIER1_ACKED = "TIER1_ACKED"
    TIER2_OPEN = "TIER2_OPEN"
    TIER2_ACKED = "TIER2_ACKED"
    TIER3_OPEN = "TIER3_OPEN"
    TIER3_ACKED = "TIER3_ACKED"
    TIER4_OPEN = "TIER4_OPEN"
    TIER4_ACKED = "TIER4_ACKED"
    RESOLVED = "RESOLVED"
    BED_RETURN_CONVERTED = "BED_RETURN_CONVERTED"


class ReservationStatus(str, Enum):
    HELD = "HELD"
    OCCUPIED = "OCCUPIED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class ClaimStatus(str, Enum):
    BUILT = "BUILT"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"


# ─── Entity shapes ─────────────────────────────────────────────────────────
# Fourteen of the fifteen resource types carry id/created_at/updated_at/version
# (PRD §2.4).  MonitoringLapse is append-only and carries only id/created_at.


class Patient(TypedDict):
    id: str
    mrn: str
    full_name: str
    home_distance_km: float
    primary_diagnosis_code: str
    diet_restriction: str
    broadband_verified: bool
    caregiver_present: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    patient_id: str
    origin: str
    qualifying_condition_code: str
    acuity: str
    referring_physician_user_id: str
    status: str
    first_failed_gauntlet_rung: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EligibilityAssessment(TypedDict):
    id: str
    referral_id: str
    in_person_eval_at: str
    home_safety_outcome: str
    broadband_check: str
    caregiver_present_confirmed: bool
    consent_signed: bool
    assessor_user_id: str
    created_at: str
    updated_at: str
    version: int


class Episode(TypedDict):
    id: str
    patient_id: str
    referral_id: str
    program_track: str
    acuity: str
    status: str
    admitted_at: str
    physician_eval_at: str
    returned_at: Optional[str]
    discharged_at: Optional[str]
    readmission_count: int
    service_day_count: int
    billable_day_count: int
    carved_out_day_count: int
    pending_day_count: int
    reimbursement_amount_usd: float
    meal_credit_total_usd: float
    travel_reimbursement_total_usd: float
    med_rec_signed: bool
    med_rec_signed_by_user_id: Optional[str]
    open_escalation_count: int
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict):
    id: str
    episode_id: str
    visit_type: str
    staff_user_id: str
    service_date: str
    scheduled_start_at: str
    scheduled_end_at: str
    distance_km: float
    scheduling_status: str
    attestation_status: str
    attested_by_user_id: Optional[str]
    travel_payment_usd: float
    created_at: str
    updated_at: str
    version: int


class DailyComplianceRecord(TypedDict):
    id: str
    episode_id: str
    service_date: str
    qualified_in_person_visit_count: int
    physician_eval_present: bool
    monitoring_lapse_minutes: int
    kit_deployed_all_day: bool
    status: str
    finalized_at: Optional[str]
    carve_out_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeviceKit(TypedDict):
    id: str
    asset_tag: str
    assigned_episode_id: Optional[str]
    status: str
    refurb_cycle_count: int
    deployed_at: Optional[str]
    component_count: int
    unreconciled_component_count: int
    created_at: str
    updated_at: str
    version: int


class DeviceComponent(TypedDict):
    id: str
    kit_id: str
    component_type: str
    serial_number: str
    replacement_cost_usd: float
    reconciliation_status: str
    reconciled_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MonitoringLapse(TypedDict):
    """Append-only telemetry gap: id and created_at only (PRD §2.4)."""
    id: str
    episode_id: str
    gap_start_at: str
    gap_end_at: str
    cause: str
    created_at: str


class DeliveryOrder(TypedDict):
    id: str
    episode_id: str
    order_kind: str
    is_controlled: bool
    cold_chain_required: bool
    weight_kg: float
    requested_by_user_id: str
    authorized_by_user_id: Optional[str]
    witness_staff_id: Optional[str]
    status: str
    redelivery_count: int
    last_excursion_minutes: Optional[int]
    handling_fee_usd: float
    created_at: str
    updated_at: str
    version: int


class MealPlan(TypedDict):
    id: str
    episode_id: str
    diet_code: str
    daily_delivery_count: int
    activated_on_date: str
    status: str
    suspension_day_count: int
    credited_day_count: int
    meal_credit_total_usd: float
    created_at: str
    updated_at: str
    version: int


class EscalationEvent(TypedDict):
    id: str
    episode_id: str
    reason: str
    opened_by_user_id: str
    status: str
    current_tier: int
    tier_entered_at: str
    ack_deadline_at: str
    promotion_count: int
    acknowledged_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InpatientUnit(TypedDict):
    id: str
    unit_code: str
    total_beds: int
    held_bed_count: int
    occupied_bed_count: int
    available_bed_count: int
    created_at: str
    updated_at: str
    version: int


class BedReservation(TypedDict):
    id: str
    unit_id: str
    episode_id: str
    status: str
    held_at: str
    hold_expires_at: str
    occupied_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BillingClaim(TypedDict):
    id: str
    episode_id: str
    billed_day_count: int
    gross_amount_usd: float
    withhold_rate: float
    withhold_amount_usd: float
    net_payable_usd: float
    paid_amount_usd: float
    status: str
    appeal_count: int
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
