"""Domain types for the Correctional Healthcare API: status enums, role enum, entity shapes."""

from enum import Enum
from typing import TypedDict, Optional, List, Any


# ─── Roles (PRD §2.1) ─────────────────────────────────

class UserRole(str, Enum):
    INTAKE_OFFICER = "IntakeOfficer"
    NURSE = "Nurse"
    PROVIDER = "Provider"
    UTILIZATION_REVIEWER = "UtilizationReviewer"
    PEER_REVIEWER = "PeerReviewer"
    CUSTODY_OFFICER = "CustodyOfficer"
    HEALTH_SERVICES_ADMIN = "HealthServicesAdmin"
    GRIEVANCE_COORDINATOR = "GrievanceCoordinator"
    INMATE = "Inmate"


# ─── Inmate (PRD §2.6, §3.1) ──────────────────────────

class CustodyStatus(str, Enum):
    IN_CUSTODY = "IN_CUSTODY"
    RELEASED = "RELEASED"
    DECEASED = "DECEASED"


class RecordsState(str, Enum):
    OPEN = "OPEN"
    FROZEN = "FROZEN"


class CustodyLevel(str, Enum):
    MINIMUM = "MINIMUM"
    MEDIUM = "MEDIUM"
    MAXIMUM = "MAXIMUM"


class AdmissionType(str, Enum):
    NEW_BOOKING = "NEW_BOOKING"
    INTER_FACILITY_TRANSFER = "INTER_FACILITY_TRANSFER"


# ─── Intake screening (PRD §3.1) ──────────────────────

class ScreeningType(str, Enum):
    RECEIVING = "RECEIVING"
    FULL_ASSESSMENT = "FULL_ASSESSMENT"


class ScreeningStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    OVERDUE = "OVERDUE"
    REFUSED = "REFUSED"


class FindingsCode(str, Enum):
    NO_FINDINGS = "NO_FINDINGS"
    CHRONIC_CONDITION = "CHRONIC_CONDITION"
    ACUTE_NEED = "ACUTE_NEED"
    MENTAL_HEALTH_REFERRAL = "MENTAL_HEALTH_REFERRAL"


# ─── Chronic care (PRD §3.2) ──────────────────────────

class ConditionCode(str, Enum):
    DIABETES = "DIABETES"
    HYPERTENSION = "HYPERTENSION"
    ASTHMA = "ASTHMA"
    SEIZURE_DISORDER = "SEIZURE_DISORDER"
    HIV = "HIV"


class Severity(str, Enum):
    MILD = "MILD"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class CareTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class EnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    RESOLVED = "RESOLVED"


class VisitOutcome(str, Enum):
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    REFUSED = "REFUSED"


# ─── Sick call (PRD §3.3) ─────────────────────────────

class Acuity(str, Enum):
    EMERGENT = "EMERGENT"
    URGENT = "URGENT"
    ROUTINE = "ROUTINE"


class SickCallStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    TRIAGED = "TRIAGED"
    SCHEDULED = "SCHEDULED"
    SEEN = "SEEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class EncounterType(str, Enum):
    SICK_CALL = "SICK_CALL"
    NURSE_TRIAGE = "NURSE_TRIAGE"
    PROVIDER_VISIT = "PROVIDER_VISIT"
    DENTAL = "DENTAL"
    SPECIALTY_OFFSITE = "SPECIALTY_OFFSITE"
    MENTAL_HEALTH = "MENTAL_HEALTH"
    EMERGENCY = "EMERGENCY"
    COMMUNICABLE_DISEASE = "COMMUNICABLE_DISEASE"
    CHRONIC_FOLLOWUP = "CHRONIC_FOLLOWUP"
    INTAKE_SCREENING = "INTAKE_SCREENING"
    STAFF_INITIATED = "STAFF_INITIATED"


# ─── Medication (PRD §3.4) ────────────────────────────

class DrugClass(str, Enum):
    PSYCHOTROPIC = "PSYCHOTROPIC"
    CONTROLLED = "CONTROLLED"
    CHRONIC_MAINTENANCE = "CHRONIC_MAINTENANCE"
    ACUTE_SHORT_COURSE = "ACUTE_SHORT_COURSE"


class RouteMode(str, Enum):
    DOT = "DOT"
    KOP = "KOP"


class OrderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    HELD = "HELD"
    DISCONTINUED = "DISCONTINUED"
    COMPLETED = "COMPLETED"


class AdministrationOutcome(str, Enum):
    SCHEDULED = "SCHEDULED"
    ADMINISTERED = "ADMINISTERED"
    REFUSED = "REFUSED"
    MISSED = "MISSED"
    VOIDED = "VOIDED"


class TimingClass(str, Enum):
    ON_TIME = "ON_TIME"
    LATE = "LATE"
    MISSED_WINDOW = "MISSED_WINDOW"


# ─── Referral / utilization review (PRD §3.5) ─────────

class Specialty(str, Enum):
    CARDIOLOGY = "CARDIOLOGY"
    ONCOLOGY = "ONCOLOGY"
    ORTHOPEDICS = "ORTHOPEDICS"
    OPHTHALMOLOGY = "OPHTHALMOLOGY"
    DIALYSIS = "DIALYSIS"


class Urgency(str, Enum):
    EMERGENT = "EMERGENT"
    ROUTINE = "ROUTINE"


class ReferralStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PENDING_UR = "PENDING_UR"
    AUTHORIZED = "AUTHORIZED"
    DENIED = "DENIED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"
    DEFER = "DEFER"


class PeerDecision(str, Enum):
    OVERTURN = "OVERTURN"
    UPHOLD = "UPHOLD"


class ReviewStatus(str, Enum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    DEFERRED = "DEFERRED"
    PEER_REVIEW = "PEER_REVIEW"
    OVERTURNED = "OVERTURNED"
    UPHELD = "UPHELD"


# ─── Transport (PRD §3.6) ─────────────────────────────

class EscortLevel(str, Enum):
    ESCORT_1 = "ESCORT_1"
    ESCORT_2 = "ESCORT_2"
    ESCORT_2_ARMED = "ESCORT_2_ARMED"


class TransportStatus(str, Enum):
    DRAFT = "DRAFT"
    ESCORT_ASSIGNED = "ESCORT_ASSIGNED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class TransportOutcome(str, Enum):
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"


class CancelReason(str, Enum):
    FACILITY_LOCKDOWN = "FACILITY_LOCKDOWN"
    VENDOR_CANCELLED = "VENDOR_CANCELLED"
    ESCORT_UNAVAILABLE = "ESCORT_UNAVAILABLE"
    CLINICAL_CHANGE = "CLINICAL_CHANGE"


# ─── Trust account (PRD §3.7) ─────────────────────────

class ChargeVariant(str, Enum):
    EXEMPT = "EXEMPT"
    FUNDED = "FUNDED"
    INDIGENT = "INDIGENT"


class ChargeStatus(str, Enum):
    POSTED = "POSTED"
    WAIVED = "WAIVED"
    REVERSED = "REVERSED"
    DEBT_LIEN = "DEBT_LIEN"


class EntryType(str, Enum):
    DEPOSIT = "DEPOSIT"
    CHARGE = "CHARGE"
    LIEN = "LIEN"
    REVERSAL = "REVERSAL"


# ─── Grievance (PRD §3.8) ─────────────────────────────

class GrievanceStage(str, Enum):
    INFORMAL = "INFORMAL"
    FORMAL = "FORMAL"
    APPEAL = "APPEAL"


class GrievanceStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    DECIDED = "DECIDED"
    REMANDED = "REMANDED"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class GrievanceOutcome(str, Enum):
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


# ─── Release / mortality (PRD §3.9) ───────────────────

class ReleaseType(str, Enum):
    SCHEDULED = "SCHEDULED"
    UNEXPECTED = "UNEXPECTED"


class ReleasePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    EXECUTED = "EXECUTED"
    VOIDED = "VOIDED"


class MannerOfDeath(str, Enum):
    NATURAL = "NATURAL"
    ACCIDENT = "ACCIDENT"
    SUICIDE = "SUICIDE"
    HOMICIDE = "HOMICIDE"
    UNDETERMINED = "UNDETERMINED"


class MortalityReviewStatus(str, Enum):
    OPEN = "OPEN"
    CORRECTIVE_ACTIONS_ISSUED = "CORRECTIVE_ACTIONS_ISSUED"
    CLOSED = "CLOSED"


# ─── Entity shapes ────────────────────────────────────
# Most resources carry id + created_at + updated_at + version (PRD §2.4).
# ChronicCareVisit and LedgerEntry are immutable audit records and carry
# ONLY id + created_at — no updated_at and no version.


class Inmate(TypedDict):
    id: str
    booking_number: str
    full_name: str
    facility_code: str
    custody_level: str
    booked_at: str
    admission_type: str
    prior_full_assessment_at: Optional[str]
    scheduled_release_date: Optional[str]
    custody_status: str
    records_state: str
    account_balance_cents: int
    indigent_flag: bool
    open_sick_call_count: int
    no_show_count: int
    created_at: str
    updated_at: str
    version: int


class IntakeScreening(TypedDict):
    id: str
    inmate_id: str
    screening_type: str
    due_at: str
    completed_at: Optional[str]
    status: str
    findings_code: Optional[str]
    completed_late: bool
    created_at: str
    updated_at: str
    version: int


class ChronicCareEnrollment(TypedDict):
    id: str
    inmate_id: str
    condition_code: str
    severity: str
    tier: str
    periodicity_days: int
    enrolled_at: str
    last_visit_at: Optional[str]
    next_due_date: Optional[str]
    missed_visit_count: int
    status: str
    escalated: bool
    created_at: str
    updated_at: str
    version: int


class ChronicCareVisit(TypedDict):
    # Immutable audit record: id + created_at only, no updated_at, no version.
    id: str
    enrollment_id: str
    recorded_at: str
    outcome: str
    due_at_snapshot: Optional[str]
    recorded_by_user_id: str
    created_at: str


class SickCallRequest(TypedDict):
    id: str
    inmate_id: str
    complaint_text: str
    submitted_at: str
    acuity: Optional[str]
    triaged_at: Optional[str]
    deadline_anchor_at: Optional[str]
    response_deadline_at: Optional[str]
    seen_at: Optional[str]
    sla_breached: bool
    retriage_count: int
    encounter_type: str
    status: str
    copay_charge_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MedicationOrder(TypedDict):
    id: str
    inmate_id: str
    drug_name: str
    drug_class: str
    route_mode: str
    doses_per_day: int
    start_date: str
    end_date: str
    units_dispensed: int
    units_returned: int
    consecutive_missed_count: int
    consecutive_refused_count: int
    adherence_pct: float
    escalated_to_prescriber: bool
    forced_dot: bool
    status: str
    prescriber_user_id: str
    created_at: str
    updated_at: str
    version: int


class MedicationAdministration(TypedDict):
    id: str
    order_id: str
    scheduled_at: str
    acted_at: Optional[str]
    outcome: str
    observed_swallow: Optional[bool]
    diversion_observed: bool
    timing_class: Optional[str]
    administered_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SpecialtyReferral(TypedDict):
    id: str
    inmate_id: str
    specialty: str
    urgency: str
    requested_at: str
    status: str
    no_show_count: int
    authorized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UtilizationReview(TypedDict):
    id: str
    referral_id: str
    opened_at: str
    turnaround_deadline_at: str
    decision: Optional[str]
    decided_at: Optional[str]
    decided_by_user_id: Optional[str]
    peer_reviewer_user_id: Optional[str]
    defer_count: int
    turnaround_breached: bool
    retrospective: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class TransportOrder(TypedDict):
    id: str
    referral_id: str
    appointment_at: str
    required_escort_level: str
    assigned_escort_level: Optional[str]
    lead_minutes: int
    status: str
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CopayCharge(TypedDict):
    id: str
    inmate_id: str
    encounter_type: str
    source_sick_call_id: Optional[str]
    scheduled_amount_cents: int
    amount_cents: int
    charge_variant: str
    indigency_snapshot: bool
    status: str
    reversal_grievance_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LedgerEntry(TypedDict):
    # Immutable audit record: id + created_at only, no updated_at, no version.
    id: str
    inmate_id: str
    entry_type: str
    amount_cents: int
    balance_after_cents: int
    source_copay_charge_id: Optional[str]
    memo: str
    created_at: str


class Grievance(TypedDict):
    id: str
    inmate_id: str
    subject_copay_charge_id: Optional[str]
    grievance_text: str
    grieved_event_at: str
    stage: str
    stage_entered_at: str
    response_due_at: str
    response_breached: bool
    remand_count: int
    outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReleasePlan(TypedDict):
    id: str
    inmate_id: str
    release_type: str
    planned_release_at: str
    bridge_supply_total_days: int
    bridge_supply_lines: List[Any]
    reentry_referral_required: bool
    records_packet_ready: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class MortalityReview(TypedDict):
    id: str
    inmate_id: str
    death_at: str
    manner: str
    due_at: str
    corrective_action_count: int
    corrective_actions: List[Any]
    closed_at: Optional[str]
    closed_late: bool
    status: str
    created_at: str
    updated_at: str
    version: int
