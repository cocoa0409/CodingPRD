"""Domain types: status enums, enumerated field sets and entity TypedDicts."""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    """The seven roles, spelled exactly as they appear in X-User-Role."""

    INTAKE_COORDINATOR = "IntakeCoordinator"
    PHYSICIAN = "Physician"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"
    RESPIRATORY_THERAPIST = "RespiratoryTherapist"
    DELIVERY_DRIVER = "DeliveryDriver"
    BRANCH_MANAGER = "BranchManager"
    BILLING_SPECIALIST = "BillingSpecialist"


# ─── Enumerated field domains ─────────────────────────

class EquipmentClass(str, Enum):
    STATIONARY_CONCENTRATOR = "STATIONARY_CONCENTRATOR"
    PORTABLE_CONCENTRATOR = "PORTABLE_CONCENTRATOR"
    LIQUID_RESERVOIR = "LIQUID_RESERVOIR"
    LIQUID_PORTABLE = "LIQUID_PORTABLE"
    COMPRESSED_CYLINDER = "COMPRESSED_CYLINDER"


class EquipmentUnitStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    RESERVED = "RESERVED"
    DEPLOYED = "DEPLOYED"
    IN_QUARANTINE = "IN_QUARANTINE"
    RETIRED = "RETIRED"


class QuarantineReason(str, Enum):
    NONE = "NONE"
    RECALL = "RECALL"
    MALFUNCTION = "MALFUNCTION"
    SAFETY = "SAFETY"
    TRANSFER = "TRANSFER"


class PayerType(str, Enum):
    MEDICARE_COMPETITIVE_BID = "MEDICARE_COMPETITIVE_BID"
    MEDICARE_NON_BID = "MEDICARE_NON_BID"
    MEDICAID = "MEDICAID"
    COMMERCIAL = "COMMERCIAL"


class MobilityProfile(str, Enum):
    HOMEBOUND = "HOMEBOUND"
    LIMITED_AMBULATORY = "LIMITED_AMBULATORY"
    ACTIVE_AMBULATORY = "ACTIVE_AMBULATORY"


class PatientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TRANSFER_PENDING = "TRANSFER_PENDING"
    DISCHARGED = "DISCHARGED"


class RiskVariant(str, Enum):
    NONE = "NONE"
    INITIAL_ASSESSMENT = "INITIAL_ASSESSMENT"
    ONGOING_SURVEILLANCE = "ONGOING_SURVEILLANCE"


class TestType(str, Enum):
    RESTING_ROOM_AIR = "RESTING_ROOM_AIR"
    EXERCISE = "EXERCISE"
    NOCTURNAL_OVERNIGHT_OXIMETRY = "NOCTURNAL_OVERNIGHT_OXIMETRY"
    SLEEP_STUDY = "SLEEP_STUDY"


class QualifyingGroup(str, Enum):
    GROUP_I = "GROUP_I"
    GROUP_II = "GROUP_II"
    NON_QUALIFYING = "NON_QUALIFYING"


class CmnFormType(str, Enum):
    INITIAL = "INITIAL"
    RECERTIFICATION = "RECERTIFICATION"
    REVISED = "REVISED"


class CmnStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PHYSICIAN_SIGNED = "PHYSICIAN_SIGNED"
    RETURNED_FOR_CORRECTION = "RETURNED_FOR_CORRECTION"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"
    SUPERSEDED = "SUPERSEDED"


class CurrentCmnStatus(str, Enum):
    """The mirrored certificate status on a patient: the certificate state set
    plus the NONE sentinel."""

    NONE = "NONE"
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PHYSICIAN_SIGNED = "PHYSICIAN_SIGNED"
    RETURNED_FOR_CORRECTION = "RETURNED_FOR_CORRECTION"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"
    SUPERSEDED = "SUPERSEDED"


class PricingBasis(str, Enum):
    COMPETITIVE_BID_SINGLE_PAYMENT = "COMPETITIVE_BID_SINGLE_PAYMENT"
    FEE_SCHEDULE_ADJUSTED = "FEE_SCHEDULE_ADJUSTED"
    CASH = "CASH"


class BillingStatus(str, Enum):
    ACCRUING = "ACCRUING"
    CAP_REACHED = "CAP_REACHED"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ServiceStatus(str, Enum):
    PENDING_SETUP = "PENDING_SETUP"
    IN_SERVICE = "IN_SERVICE"
    PICKUP_SCHEDULED = "PICKUP_SCHEDULED"
    RETURNED = "RETURNED"
    SETUP_FAILED = "SETUP_FAILED"


class SuspensionReason(str, Enum):
    NONE = "NONE"
    CMN_VOIDED = "CMN_VOIDED"
    CMN_EXPIRED = "CMN_EXPIRED"
    RECALL = "RECALL"
    TRANSFER = "TRANSFER"
    SETUP_FAILED = "SETUP_FAILED"


class PlacementRole(str, Enum):
    PRIMARY_STATIONARY = "PRIMARY_STATIONARY"
    PORTABLE = "PORTABLE"
    BACKUP = "BACKUP"


class PlacementStatus(str, Enum):
    RESERVED = "RESERVED"
    PLACED = "PLACED"
    REMOVED = "REMOVED"
    RECALLED_OUT_OF_SERVICE = "RECALLED_OUT_OF_SERVICE"


class RemovalReason(str, Enum):
    NONE = "NONE"
    RELEASED = "RELEASED"
    SETUP_FAILED = "SETUP_FAILED"
    RECALL = "RECALL"
    MALFUNCTION = "MALFUNCTION"
    PICKUP = "PICKUP"
    TRANSFER = "TRANSFER"


class RouteStatus(str, Enum):
    PLANNING = "PLANNING"
    LOCKED = "LOCKED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"


class StopType(str, Enum):
    SETUP_DELIVERY = "SETUP_DELIVERY"
    TANK_EXCHANGE = "TANK_EXCHANGE"
    PORTABLE_REFILL = "PORTABLE_REFILL"
    PICKUP = "PICKUP"
    MAINTENANCE_SWAP = "MAINTENANCE_SWAP"


class StopStatus(str, Enum):
    PLANNED = "PLANNED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class SafetyResult(str, Enum):
    NOT_ASSESSED = "NOT_ASSESSED"
    PASS = "PASS"
    FAIL = "FAIL"


class MalfunctionSymptom(str, Enum):
    NONE = "NONE"
    NO_FLOW = "NO_FLOW"
    ALARM_CONTINUOUS = "ALARM_CONTINUOUS"
    LOW_PURITY = "LOW_PURITY"
    POWER_FAILURE = "POWER_FAILURE"
    LEAK = "LEAK"


class SeverityTier(str, Enum):
    NONE = "NONE"
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class RecallSeverity(str, Enum):
    CLASS_I = "CLASS_I"
    CLASS_II = "CLASS_II"
    CLASS_III = "CLASS_III"


class RecallStatus(str, Enum):
    OPEN = "OPEN"
    IN_REMEDIATION = "IN_REMEDIATION"
    CLOSED = "CLOSED"


class TravelAuthorizationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


# ─── Entity shapes ────────────────────────────────────
# Every entity below carries id, created_at, updated_at and version, except
# QualifyingTest, whose row is immutable and therefore carries only id and
# created_at.


class Branch(TypedDict):
    id: str
    name: str
    state_code: str
    competitive_bid_area: bool
    liquid_oxygen_certified: bool
    refill_capacity_per_day: int
    tank_exchange_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    mrn: str
    full_name: str
    branch_id: str
    payer_type: str
    mobility_profile: str
    altitude_feet: int
    status: str
    current_cmn_status: str
    oxygen_safety_risk_score: float
    risk_variant_applied: str
    compliance_hold: bool
    transfer_to_branch_id: Optional[str]
    transfer_effective_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QualifyingTest(TypedDict):
    """Immutable clinical record: carries only id and created_at."""

    id: str
    patient_id: str
    test_type: str
    tested_at: str
    ordering_physician_npi: str
    spo2_percent: Optional[int]
    pao2_mmhg: Optional[int]
    desat_minutes: int
    cor_pulmonale_or_edema: bool
    validity_days: int
    test_validity_expires_at: str
    qualifying_group: str
    created_at: str


class CertificateOfMedicalNecessity(TypedDict):
    id: str
    patient_id: str
    qualifying_test_id: str
    form_type: str
    prescribed_lpm: float
    hours_per_day: int
    portable_prescribed: bool
    length_of_need_months: int
    narrative_element_count: int
    status: str
    documentation_score: float
    revision_round: int
    correction_notes: Optional[str]
    submitted_by_user_id: Optional[str]
    signed_by_user_id: Optional[str]
    physician_signature_date: Optional[str]
    audited_by_user_id: Optional[str]
    initial_date: Optional[str]
    recert_due_date: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PostedMonth(TypedDict):
    service_month: str
    amount_cents: int
    days_in_service: int
    posted_at: str


class RentalContract(TypedDict):
    id: str
    patient_id: str
    cmn_id: str
    pricing_basis: str
    cap_month_limit: int
    billing_status: str
    service_status: str
    suspension_reason: str
    monthly_allowable_cents: int
    posted_months: List[PostedMonth]
    posted_month_count: int
    lifetime_paid_cents: int
    first_service_month: Optional[str]
    last_posted_service_month: Optional[str]
    malfunction_count: int
    cumulative_oxygen_gap_minutes: int
    created_at: str
    updated_at: str
    version: int


class EquipmentUnit(TypedDict):
    id: str
    branch_id: str
    serial_number: str
    model_code: str
    equipment_class: str
    max_continuous_lpm: float
    max_pulse_setting: int
    pm_interval_days: int
    next_pm_due_date: str
    replaces_unit_id: Optional[str]
    status: str
    quarantine_reason: str
    recall_remediated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Placement(TypedDict):
    id: str
    contract_id: str
    equipment_unit_id: str
    role: str
    status: str
    placed_at: Optional[str]
    removed_at: Optional[str]
    removal_reason: str
    malfunction_count: int
    last_symptom: str
    last_severity_tier: str
    created_at: str
    updated_at: str
    version: int


class DeliveryRoute(TypedDict):
    id: str
    branch_id: str
    service_date: str
    driver_user_id: str
    shift_start_utc: str
    shift_end_utc: str
    status: str
    total_o2_liters_committed: int
    refill_slots_used: int
    planned_stop_count: int
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict):
    id: str
    route_id: str
    contract_id: str
    stop_type: str
    window_start_utc: str
    window_end_utc: str
    service_minutes: int
    cylinders_requested: int
    liters_committed: int
    sequence_index: int
    status: str
    safety_result: str
    smoking_in_home: Optional[bool]
    electrical_pass: Optional[bool]
    patient_teachback_score: Optional[int]
    education_topics_covered: List[str]
    safety_findings_count: int
    completed_at: Optional[str]
    completed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecallNotice(TypedDict):
    id: str
    model_code: str
    severity: str
    status: str
    issued_at: str
    remediation_deadline_utc: str
    affected_unit_count: int
    auto_quarantined_unit_count: int
    remediated_unit_count: int
    created_at: str
    updated_at: str
    version: int


class TravelAuthorization(TypedDict):
    id: str
    contract_id: str
    receiving_branch_id: Optional[str]
    depart_utc: str
    return_utc: str
    destination_altitude_feet: int
    status: str
    trip_hours: int
    altitude_factor: float
    effective_lpm: float
    base_liters: int
    reserve_liters: int
    required_liters: int
    cylinders_raw: int
    handling_surcharge_cylinders: int
    supply_cylinders_authorized: int
    decided_by_user_id: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── Computed read shapes (persist nothing) ───────────


class RiskAssessmentRead(TypedDict):
    patient_id: str
    factor_smoking: float
    factor_electrical: float
    factor_teachback: float
    factor_flow: float
    factor_incident: float
    initial_assessment_score: float
    ongoing_surveillance_score: float
    persisted_score: float
    persisted_variant: str
    compliance_hold: bool


class CapSummaryRead(TypedDict):
    contract_id: str
    candidate_service_month: Optional[str]
    service_month_basis_position: int
    paid_month_basis_position: int
    variant_applied: str
    effective_position: int
    cap_month_limit: int
    months_remaining: int
    monthly_allowable_cents: int
    lifetime_paid_cents: int
    posted_month_count: int


class RouteManifestRead(TypedDict):
    route_id: str
    status: str
    planned_stop_count: int
    completed_stop_count: int
    missed_stop_count: int
    cancelled_stop_count: int
    refill_slots_used: int
    refill_capacity_per_day: int
    total_o2_liters_committed: int


class ClockAdvanceResult(TypedDict):
    current_utc: str
    previous_utc: str
    expired_cmn_count: int
    suspended_contract_count: int
