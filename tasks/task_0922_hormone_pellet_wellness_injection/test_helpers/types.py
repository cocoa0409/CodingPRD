"""Domain types: entity TypedDicts, status enums, role enum."""

from enum import Enum
from typing import List, Optional, TypedDict


# ── Roles (PRD 2.1) ──────────────────────────────────────────────────────────
class UserRole(str, Enum):
    CLINIC_ADMIN = "ClinicAdmin"
    PHYSICIAN = "Physician"
    NURSE_INJECTOR = "NurseInjector"
    INVENTORY_MANAGER = "InventoryManager"
    FRONT_DESK = "FrontDesk"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PATIENT = "Patient"


# ── Shared vocabularies ──────────────────────────────────────────────────────
class HormoneType(str, Enum):
    TESTOSTERONE = "TESTOSTERONE"
    ESTRADIOL = "ESTRADIOL"


class InjectionType(str, Enum):
    B12 = "B12"
    LIPOTROPIC = "LIPOTROPIC"
    VITAMIN_D = "VITAMIN_D"
    GLUTATHIONE = "GLUTATHIONE"


class Analyte(str, Enum):
    TOTAL_TESTOSTERONE = "TOTAL_TESTOSTERONE"
    ESTRADIOL = "ESTRADIOL"
    HEMATOCRIT = "HEMATOCRIT"


# ── State vocabularies ───────────────────────────────────────────────────────
class EligibilityStatus(str, Enum):
    CLEAR = "CLEAR"
    CLINICAL_HOLD = "CLINICAL_HOLD"
    FINANCIAL_HOLD = "FINANCIAL_HOLD"
    DUAL_HOLD = "DUAL_HOLD"


class ConsentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class LabPanelStatus(str, Enum):
    RECORDED = "RECORDED"
    CRITICAL_FLAGGED = "CRITICAL_FLAGGED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    SUPERSEDED = "SUPERSEDED"


class LabReferenceBand(str, Enum):
    BELOW_REF = "BELOW_REF"
    IN_REF = "IN_REF"
    ABOVE_REF = "ABOVE_REF"


class ClinicOptimalBand(str, Enum):
    BELOW_OPTIMAL = "BELOW_OPTIMAL"
    IN_OPTIMAL = "IN_OPTIMAL"
    ABOVE_OPTIMAL = "ABOVE_OPTIMAL"


class SterilityStatus(str, Enum):
    QUARANTINED = "QUARANTINED"
    RELEASED = "RELEASED"
    RECALLED = "RECALLED"


class RecallSeverityClass(str, Enum):
    CLASS_I = "CLASS_I"
    CLASS_II = "CLASS_II"


class StandingOrderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class ProcedureStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONSENTED = "CONSENTED"
    SUPPLY_OPENED = "SUPPLY_OPENED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    VOIDED = "VOIDED"
    SUPPLY_HOLD = "SUPPLY_HOLD"


class ProcedureRecallStatus(str, Enum):
    NONE = "NONE"
    RECALL_AFFECTED = "RECALL_AFFECTED"
    NOTIFIED = "NOTIFIED"


class ProcedureType(str, Enum):
    INITIAL = "INITIAL"
    REDOSE = "REDOSE"


class CancelTier(str, Enum):
    NONE = "NONE"
    TIER1 = "TIER1"
    TIER2 = "TIER2"
    NO_SHOW = "NO_SHOW"


class HoldReason(str, Enum):
    STANDING_ORDER_SUSPENDED = "STANDING_ORDER_SUSPENDED"
    LOT_RECALL = "LOT_RECALL"
    PATIENT_FINANCIAL_HOLD = "PATIENT_FINANCIAL_HOLD"


class AllocationStatus(str, Enum):
    RESERVED = "RESERVED"
    OPENED = "OPENED"
    CONSUMED = "CONSUMED"
    WASTED = "WASTED"
    RELEASED = "RELEASED"
    RECALL_RELEASED = "RECALL_RELEASED"
    RECALL_FLAGGED = "RECALL_FLAGGED"


class MembershipTier(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    ELITE = "ELITE"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class SeriesPackStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"
    REFUNDED = "REFUNDED"


class InjectionVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ADMINISTERED = "ADMINISTERED"
    CANCELLED = "CANCELLED"
    VOIDED = "VOIDED"


class PaymentSource(str, Enum):
    SERIES = "SERIES"
    MEMBERSHIP_INCLUDED = "MEMBERSHIP_INCLUDED"
    SELF_PAY = "SELF_PAY"


class AdverseEventSeverity(str, Enum):
    MILD = "MILD"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"
    SURVEILLANCE = "SURVEILLANCE"


class AdverseEventSource(str, Enum):
    CLINICAL_REPORT = "CLINICAL_REPORT"
    RECALL_SURVEILLANCE = "RECALL_SURVEILLANCE"


class AdverseEventStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    ESCALATED = "ESCALATED"


class AdverseEventDisposition(str, Enum):
    CLOSED = "CLOSED"
    ESCALATED = "ESCALATED"


class FinancingPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"
    DEFAULTED = "DEFAULTED"
    PAID_OFF = "PAID_OFF"
    CANCELLED = "CANCELLED"


class ScheduleEntryStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    MISSED = "MISSED"
    WAIVED = "WAIVED"


class NotificationType(str, Enum):
    RECALL = "RECALL"
    ADVERSE_EVENT = "ADVERSE_EVENT"
    CONSENT_REQUIRED = "CONSENT_REQUIRED"


class NotificationStatus(str, Enum):
    PENDING = "PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    OVERDUE = "OVERDUE"


class HoldKind(str, Enum):
    CLINICAL = "CLINICAL"
    FINANCIAL = "FINANCIAL"


class HoldAction(str, Enum):
    SET = "SET"
    CLEAR = "CLEAR"


class SexAtBirth(str, Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"


class ProviderType(str, Enum):
    PHYSICIAN = "PHYSICIAN"
    NURSE_INJECTOR = "NURSE_INJECTOR"


# ── Entity shapes ────────────────────────────────────────────────────────────
# Records carry id, created_at, updated_at and version, with one exception:
# a published Protocol is immutable and carries only id and created_at.


class Patient(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    email: str
    sex_at_birth: str
    clinical_hold: bool
    financial_hold: bool
    eligibility_status: str
    cumulative_mg_testosterone: float
    cumulative_mg_estradiol: float
    last_insertion_at: Optional[str]
    last_insertion_hormone_type: Optional[str]
    open_notification_count: int
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict):
    id: str
    full_name: str
    provider_type: str
    npi: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class Protocol(TypedDict):
    """Immutable historical record: id and created_at only, no updated_at, no version."""

    id: str
    hormone_type: str
    protocol_version: int
    title: str
    published_by_provider_id: str
    effective_at: str
    created_at: str


class ConsentRecord(TypedDict):
    id: str
    patient_id: str
    hormone_type: str
    protocol_version: int
    consented_max_dose_mg: float
    signed_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Consult(TypedDict):
    id: str
    patient_id: str
    physician_id: str
    hormone_type: str
    prescribed_dose_mg: float
    symptom_score: int
    indication: str
    planned_large_count: int
    planned_small_count: int
    planned_total_mg: float
    planned_pellet_count: int
    created_at: str
    updated_at: str
    version: int


class LabPanel(TypedDict):
    id: str
    patient_id: str
    ordered_by_provider_id: str
    acknowledged_by_provider_id: Optional[str]
    analyte: str
    value: float
    unit: str
    drawn_at: str
    resulted_at: str
    is_trough_draw: bool
    lab_reference_band: str
    clinic_optimal_band: str
    critical_flag: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PelletLot(TypedDict):
    id: str
    lot_code: str
    hormone_type: str
    strength_mg: float
    expiry_date: str
    qty_received: int
    qty_on_hand: int
    qty_reserved: int
    qty_consumed: int
    qty_wasted: int
    qty_returned: int
    sterility_status: str
    recall_severity: Optional[str]
    recalled_at: Optional[str]
    recall_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StandingOrder(TypedDict):
    id: str
    physician_id: str
    scope_hormone_types: List[str]
    scope_injection_types: List[str]
    max_dose_mg: float
    valid_from: str
    valid_until: str
    status: str
    suspended_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Procedure(TypedDict):
    id: str
    patient_id: str
    provider_id: str
    consult_id: str
    standing_order_id: str
    consent_record_id: Optional[str]
    lab_panel_id: Optional[str]
    membership_id: Optional[str]
    procedure_type: str
    hormone_type: str
    room_code: str
    scheduled_start: str
    scheduled_end: str
    planned_pellet_count: int
    planned_total_mg: float
    pellets_allocated: int
    pellets_opened: int
    pellets_inserted: int
    pellets_wasted: int
    delivered_total_mg: float
    status: str
    recall_status: str
    charge_cents: int
    cancel_tier: Optional[str]
    cancel_fee_cents: int
    performed_at: Optional[str]
    hold_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PelletAllocation(TypedDict):
    id: str
    procedure_id: str
    lot_id: str
    strength_mg: float
    quantity: int
    allocation_rank: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    patient_id: str
    tier: str
    monthly_fee_cents: int
    discount_pct: float
    included_visits_allowance: int
    included_visits_used: int
    period_start: str
    period_end: str
    status: str
    paused_at: Optional[str]
    pause_days_used: int
    pause_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class SeriesPack(TypedDict):
    id: str
    patient_id: str
    series_type: str
    purchased_visits: int
    remaining_visits: int
    redeemed_visits: int
    refunded_visits: int
    forfeited_visits: int
    price_cents: int
    per_visit_value_cents: int
    purchased_at: str
    expires_at: str
    refunded_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InjectionVisit(TypedDict):
    id: str
    patient_id: str
    provider_id: str
    standing_order_id: str
    series_pack_id: Optional[str]
    membership_id: Optional[str]
    injection_type: str
    room_code: str
    scheduled_start: str
    scheduled_end: str
    payment_source: Optional[str]
    charge_cents: int
    series_debit_cents: int
    administered_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AdverseEvent(TypedDict):
    id: str
    patient_id: str
    procedure_id: Optional[str]
    injection_visit_id: Optional[str]
    lot_id: Optional[str]
    standing_order_id: Optional[str]
    reported_by_provider_id: str
    reviewed_by_provider_id: Optional[str]
    severity: str
    source: str
    narrative: str
    onset_at: str
    review_due_at: Optional[str]
    disposition_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FinancingPlan(TypedDict):
    id: str
    patient_id: str
    procedure_id: str
    principal_cents: int
    down_payment_cents: int
    installment_count: int
    first_due_date: str
    schedule: List[dict]
    paid_installment_cents: int
    outstanding_cents: int
    waived_cents: int
    refunded_cents: int
    late_fee_cents: int
    missed_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PatientNotification(TypedDict):
    id: str
    patient_id: str
    procedure_id: Optional[str]
    lot_id: Optional[str]
    notification_type: str
    severity_class: Optional[str]
    message: str
    due_at: str
    acknowledged_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
