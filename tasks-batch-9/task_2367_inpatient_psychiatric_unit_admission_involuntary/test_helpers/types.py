"""Typed shapes for the Inpatient Psychiatric Admission API.

Every one of the thirteen persisted resource types carries the same four
system-managed properties — ``id``, ``created_at``, ``updated_at`` and
``version`` — "with no exceptions and no type-specific omissions" (PRD 2.5), so
each entity TypedDict below extends :class:`CommonFields`.

The string enums exist so a test can name a state rather than repeat a literal;
their values are the wire values the API returns.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles and credentials
# ---------------------------------------------------------------------------


class Role(str, Enum):
    """The five values ``X-User-Role`` may take (PRD 2.1)."""

    COMPLIANCE_OFFICER = "ComplianceOfficer"
    INTAKE_CLINICIAN = "IntakeClinician"
    ATTENDING_PSYCHIATRIST = "AttendingPsychiatrist"
    CHARGE_NURSE = "ChargeNurse"
    PATIENT_RIGHTS_ADVOCATE = "PatientRightsAdvocate"


class StaffRole(str, Enum):
    """Roster credential class, independent of the ``X-User-Role`` header."""

    INTAKE_CLINICIAN = "INTAKE_CLINICIAN"
    PSYCHIATRIST = "PSYCHIATRIST"
    CHARGE_NURSE = "CHARGE_NURSE"
    RIGHTS_ADVOCATE = "RIGHTS_ADVOCATE"


# ---------------------------------------------------------------------------
# Unit, bed and patient enums
# ---------------------------------------------------------------------------


class GenderMixingPolicy(str, Enum):
    SEPARATE_BY_ROOM = "SEPARATE_BY_ROOM"
    SEPARATE_BY_WING = "SEPARATE_BY_WING"
    MIXED_ALLOWED = "MIXED_ALLOWED"


class UnitPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class BedType(str, Enum):
    STANDARD = "STANDARD"
    LIGATURE_RESISTANT_OBSERVATION = "LIGATURE_RESISTANT_OBSERVATION"
    SECLUSION = "SECLUSION"


class BedStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"
    BLOCKED_CLEANING = "BLOCKED_CLEANING"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class GenderCareCategory(str, Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    NONBINARY = "NONBINARY"


# ---------------------------------------------------------------------------
# Evaluation enums
# ---------------------------------------------------------------------------


class EvaluationStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"


class AcuityTier(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class RecommendedStatus(str, Enum):
    NO_ADMISSION = "NO_ADMISSION"
    VOLUNTARY = "VOLUNTARY"
    INVOLUNTARY_HOLD = "INVOLUNTARY_HOLD"


# ---------------------------------------------------------------------------
# Hold, petition and hearing enums
# ---------------------------------------------------------------------------


class HoldType(str, Enum):
    EMERGENCY_72H = "EMERGENCY_72H"
    EXTENSION_14D = "EXTENSION_14D"


class HoldStatus(str, Enum):
    PENDING_CERTIFICATION = "PENDING_CERTIFICATION"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    RESCINDED = "RESCINDED"
    SUPERSEDED = "SUPERSEDED"
    CONVERTED_VOLUNTARY = "CONVERTED_VOLUNTARY"
    DISCHARGED_BY_COURT = "DISCHARGED_BY_COURT"


class PetitionStatus(str, Enum):
    FILED = "FILED"
    HEARING_SCHEDULED = "HEARING_SCHEDULED"
    CONTINUED = "CONTINUED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class HearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    CONTINUED = "CONTINUED"
    VACATED = "VACATED"


class HearingOutcome(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    CONTINUED = "CONTINUED"


# ---------------------------------------------------------------------------
# Admission enums
# ---------------------------------------------------------------------------


class LegalStatus(str, Enum):
    VOLUNTARY = "VOLUNTARY"
    INVOLUNTARY = "INVOLUNTARY"


class PlacementStatus(str, Enum):
    PENDING_PLACEMENT = "PENDING_PLACEMENT"
    PLACED = "PLACED"
    DISCHARGE_READY = "DISCHARGE_READY"
    DISCHARGED = "DISCHARGED"
    CANCELLED = "CANCELLED"


class SafetySearchStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    REFUSED = "REFUSED"


class SearchType(str, Enum):
    VISUAL = "VISUAL"
    WANDED = "WANDED"
    FULL_BODY_WITH_CONSENT = "FULL_BODY_WITH_CONSENT"


class SearchOutcome(str, Enum):
    """The ``outcome`` a safety search is recorded with (PRD 3.5)."""

    COMPLETED = "COMPLETED"
    REFUSED = "REFUSED"


class DischargePlanStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    APPOINTMENT_SECURED = "APPOINTMENT_SECURED"


# ---------------------------------------------------------------------------
# Restraint enums
# ---------------------------------------------------------------------------


class InterventionType(str, Enum):
    PHYSICAL_HOLD = "PHYSICAL_HOLD"
    MECHANICAL_RESTRAINT = "MECHANICAL_RESTRAINT"
    SECLUSION = "SECLUSION"


class RestraintStatus(str, Enum):
    ORDERED = "ORDERED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    DEBRIEFED = "DEBRIEFED"
    EXPIRED_UNAUTHORIZED = "EXPIRED_UNAUTHORIZED"


class CheckType(str, Enum):
    CIRCULATION = "CIRCULATION"
    HYDRATION_OFFERED = "HYDRATION_OFFERED"
    TOILETING = "TOILETING"
    VITALS = "VITALS"


# ---------------------------------------------------------------------------
# Capacity, consent and discharge-request enums
# ---------------------------------------------------------------------------


class DeterminationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class SurrogateRelationship(str, Enum):
    SPOUSE = "SPOUSE"
    PARENT = "PARENT"
    ADULT_CHILD = "ADULT_CHILD"
    GUARDIAN = "GUARDIAN"


class SurrogateAuthorityScope(str, Enum):
    NONE = "NONE"
    MEDICATION_ONLY = "MEDICATION_ONLY"
    FULL = "FULL"


class ConsentBasis(str, Enum):
    PATIENT_CONSENT = "PATIENT_CONSENT"
    SURROGATE_CONSENT = "SURROGATE_CONSENT"
    EMERGENCY_OVERRIDE = "EMERGENCY_OVERRIDE"


class ConsentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class RequestedBy(str, Enum):
    PATIENT = "PATIENT"
    GUARDIAN = "GUARDIAN"


class DischargeDecision(str, Enum):
    PENDING = "PENDING"
    GRANT = "GRANT"
    DENY = "DENY"


class DischargeRequestStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED_DISCHARGE = "GRANTED_DISCHARGE"
    DENIED_HOLD_INITIATED = "DENIED_HOLD_INITIATED"
    EXPIRED_UNANSWERED = "EXPIRED_UNANSWERED"


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------


class CommonFields(TypedDict):
    """The four properties every persisted resource carries (PRD 2.5)."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Clinician(CommonFields):
    full_name: str
    staff_role: str
    license_number: str
    booked_docket_minutes: int


class Unit(CommonFields):
    name: str
    gender_mixing_policy: str
    seclusion_room_count: int
    licensed_placement_bed_count: int
    raw_available_bed_count: int
    posture: str
    effective_available_bed_count: int
    occupied_bed_count: int
    active_seclusion_count: int
    open_rights_violation_count: int


class Bed(CommonFields):
    unit_id: str
    room_number: str
    wing_code: str
    bed_label: str
    bed_type: str
    status: str


class Patient(CommonFields):
    mrn: str
    legal_name: str
    age_years: int
    is_minor: bool
    gender_care_category: str
    active_hold_count: int


class EmergencyEvaluation(CommonFields):
    patient_id: str
    evaluating_clinician_id: str
    evaluation_started_at: str
    danger_to_self: bool
    danger_to_others: bool
    grave_disability: bool
    capacity_present: bool
    clinical_summary: str
    prior_admission_count_30d: int
    acuity_score: int
    acuity_tier: str
    recommended_status: str
    status: str
    signed_at: Optional[str]


class HoldOrder(CommonFields):
    patient_id: str
    evaluation_id: str
    predecessor_hold_id: Optional[str]
    initiated_by_clinician_id: str
    certifying_clinician_id: Optional[str]
    hold_type: str
    statutory_hours: int
    clock_started_at: str
    certification_deadline_at: str
    release_deadline_at: str
    petition_filing_deadline_at: str
    certified_at: Optional[str]
    status: str
    closure_reason: Optional[str]


class HoldPetition(CommonFields):
    hold_id: str
    petitioning_clinician_id: str
    requested_hold_type: str
    petition_grounds: str
    filed_at: str
    continuance_count: int
    status: str


class CourtHearing(CommonFields):
    petition_id: str
    advocate_clinician_id: str
    scheduled_start_at: str
    duration_minutes: int
    scheduled_end_at: str
    status: str
    outcome: str
    findings_note: Optional[str]


class Admission(CommonFields):
    patient_id: str
    evaluation_id: str
    unit_id: str
    bed_id: Optional[str]
    admitting_clinician_id: str
    search_performed_by_clinician_id: Optional[str]
    search_witness_clinician_id: Optional[str]
    legal_status: str
    placement_status: str
    acuity_tier: str
    admitted_at: str
    placed_at: Optional[str]
    discharged_at: Optional[str]
    safety_search_status: str
    search_type: Optional[str]
    search_items_secured_count: int
    contraband_found: bool
    capacity_present: Optional[bool]
    discharge_plan_status: str
    follow_up_provider_name: Optional[str]
    follow_up_appointment_at: Optional[str]
    follow_up_guarantee_days: Optional[int]
    follow_up_guarantee_deadline_at: Optional[str]
    observation_staff_quarter_hours: int
    rights_violation_flag: bool
    discharge_summary: Optional[str]


class MonitoringCheck(TypedDict):
    """One element of ``monitoring_check_log`` (PRD 3.6)."""

    recorded_at: str
    check_type: str
    recorded_by_clinician_id: str
    note: Optional[str]


class RestraintEpisode(CommonFields):
    admission_id: str
    ordered_by_clinician_id: str
    face_to_face_clinician_id: Optional[str]
    intervention_type: str
    ordered_duration_minutes: int
    clinical_justification: str
    started_at: str
    authorized_until_at: str
    face_to_face_deadline_at: str
    face_to_face_at: Optional[str]
    released_at: Optional[str]
    actual_duration_minutes: Optional[int]
    monitoring_interval_minutes: int
    required_check_count: Optional[int]
    monitoring_check_log: List[MonitoringCheck]
    grid_satisfied_slot_count: Optional[int]
    grid_compliance_pct: Optional[float]
    raw_compliance_pct: Optional[float]
    status: str
    debrief_completed_at: Optional[str]
    patient_participated_in_debrief: Optional[bool]
    staff_participants_count: Optional[int]
    debrief_note: Optional[str]


class CapacityDetermination(CommonFields):
    admission_id: str
    determined_by_clinician_id: str
    capacity_present: bool
    surrogate_name: Optional[str]
    surrogate_relationship: Optional[str]
    surrogate_authority_scope: Optional[str]
    determined_at: str
    status: str


class MedicationConsent(CommonFields):
    admission_id: str
    capacity_determination_id: Optional[str]
    prescribing_clinician_id: str
    medication_name: str
    consent_basis: str
    emergency_justification: Optional[str]
    expires_at: Optional[str]
    status: str


class DischargeRequest(CommonFields):
    admission_id: str
    recorded_by_clinician_id: str
    responding_clinician_id: Optional[str]
    requested_by: str
    requested_at: str
    response_deadline_at: str
    decision: str
    status: str
    response_note: Optional[str]


#: The shape of a sweep response body (PRD 2.4).
class SweepCounts(TypedDict):
    expired_hold_count: int
    expired_restraint_count: int
    expired_discharge_request_count: int
    expired_consent_count: int


JsonDict = Dict[str, Any]
