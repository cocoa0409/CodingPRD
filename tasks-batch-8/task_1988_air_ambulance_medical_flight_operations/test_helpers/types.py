"""Domain types: entity TypedDicts, status enums, role enum.

Field names mirror the PRD exactly. WeatherAssessment is an immutable
observation carrying only id + created_at (no updated_at / version).
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    OPS_ADMIN = "OpsAdmin"
    DISPATCHER = "Dispatcher"
    MEDICAL_DIRECTOR = "MedicalDirector"
    FLIGHT_CREW = "FlightCrew"
    BILLING_SPECIALIST = "BillingSpecialist"
    QA_REVIEWER = "QaReviewer"


class AircraftClass(str, Enum):
    ROTOR_WING = "ROTOR_WING"
    FIXED_WING = "FIXED_WING"


class MedicalConfig(str, Enum):
    BLS_CAPABLE = "BLS_CAPABLE"
    ALS_CAPABLE = "ALS_CAPABLE"
    CCT_CAPABLE = "CCT_CAPABLE"


class AircraftStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    MAINTENANCE = "MAINTENANCE"


class CrewRole(str, Enum):
    PILOT = "PILOT"
    NURSE = "NURSE"
    PARAMEDIC = "PARAMEDIC"


class CrewMemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMEDIATION_HOLD = "REMEDIATION_HOLD"
    INACTIVE = "INACTIVE"


class CrewShiftStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class MembershipTier(str, Enum):
    STANDARD = "STANDARD"
    FAMILY = "FAMILY"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    TERMINATED = "TERMINATED"


class TransportClass(str, Enum):
    EMERGENCY_SCENE = "EMERGENCY_SCENE"
    EMERGENCY_INTERFACILITY = "EMERGENCY_INTERFACILITY"
    SCHEDULED_INTERFACILITY = "SCHEDULED_INTERFACILITY"
    INTERNATIONAL_REPATRIATION = "INTERNATIONAL_REPATRIATION"


class AcuityTier(str, Enum):
    BLS = "BLS"
    ALS = "ALS"
    CCT = "CCT"


class MissionRequestStatus(str, Enum):
    RECEIVED = "RECEIVED"
    TRIAGED = "TRIAGED"
    PENDING_INFO = "PENDING_INFO"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class MissionStatus(str, Enum):
    PLANNING = "PLANNING"
    LAUNCHED = "LAUNCHED"
    WEATHER_HOLD = "WEATHER_HOLD"
    AT_PATIENT = "AT_PATIENT"
    IN_TRANSIT = "IN_TRANSIT"
    DIVERTED = "DIVERTED"
    AT_DESTINATION = "AT_DESTINATION"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    CANCELLED = "CANCELLED"


class CrewAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    RELEASED = "RELEASED"
    COMPLETED = "COMPLETED"


class WeatherDecision(str, Enum):
    GO = "GO"
    MARGINAL = "MARGINAL"
    NO_GO = "NO_GO"


class Precip(str, Enum):
    NONE = "NONE"
    LIGHT = "LIGHT"
    HEAVY = "HEAVY"
    ICE = "ICE"


class DayNight(str, Enum):
    DAY = "DAY"
    NIGHT = "NIGHT"


class Terrain(str, Enum):
    FLAT = "FLAT"
    MOUNTAINOUS = "MOUNTAINOUS"


class LegType(str, Enum):
    ORIGIN = "ORIGIN"
    DESTINATION = "DESTINATION"


class GroundLegStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ENROUTE = "ENROUTE"
    AT_BEDSIDE = "AT_BEDSIDE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class GroundCoordinationStatus(str, Enum):
    COORDINATED = "COORDINATED"
    PENDING = "PENDING"
    NEEDS_REPLAN = "NEEDS_REPLAN"


class BedType(str, Enum):
    ICU = "ICU"
    CCU = "CCU"
    MED_SURGE = "MED_SURGE"
    NICU = "NICU"


class BedReservationStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"
    CONSUMED = "CONSUMED"


class InsuranceAuthorizationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    PARTIAL = "PARTIAL"
    DENIED = "DENIED"
    APPEALED = "APPEALED"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    RESUBMITTED = "RESUBMITTED"


class MemberAdjustmentStatus(str, Enum):
    UNEVALUATED = "UNEVALUATED"
    MEMBER_PROTECTED = "MEMBER_PROTECTED"
    NON_MEMBER = "NON_MEMBER"
    WRITEOFF_POSTED = "WRITEOFF_POSTED"
    BALANCE_BILLED = "BALANCE_BILLED"


class RepatriationCaseStatus(str, Enum):
    COLLECTING = "COLLECTING"
    READY_TO_FLY = "READY_TO_FLY"


class DocType(str, Enum):
    PASSPORT = "PASSPORT"
    VISA = "VISA"
    FIT_TO_FLY = "FIT_TO_FLY"
    CUSTOMS_PRECLEARANCE = "CUSTOMS_PRECLEARANCE"


class PcrStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    QA_APPROVED = "QA_APPROVED"
    QA_FLAGGED = "QA_FLAGGED"
    AMENDED = "AMENDED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields entities carry id/created_at/updated_at/version)
# ---------------------------------------------------------------------------

class Base(TypedDict, total=False):
    id: str
    name: str
    region: str
    created_at: str
    updated_at: str
    version: int


class Aircraft(TypedDict, total=False):
    id: str
    base_id: str
    tail_number: str
    aircraft_class: str
    medical_config: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CrewMember(TypedDict, total=False):
    id: str
    base_id: str
    full_name: str
    crew_role: str
    status: str
    deficiency_points_90d: int
    duty_minutes_calendar_day: int
    created_at: str
    updated_at: str
    version: int


class CrewShift(TypedDict, total=False):
    id: str
    crew_member_id: str
    planned_start_iso: str
    planned_end_iso: str
    actual_end_iso: Optional[str]
    planned_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    weight_kg: float
    created_at: str
    updated_at: str
    version: int


class MembershipSubscription(TypedDict, total=False):
    id: str
    patient_id: str
    tier: str
    effective_from: str
    status: str
    lapsed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MissionRequest(TypedDict, total=False):
    id: str
    patient_id: str
    transport_class: str
    origin_facility: str
    destination_facility: str
    destination_country: Optional[str]
    reported_cardio: int
    reported_resp: int
    reported_neuro: int
    reported_interventions: int
    onset_iso: str
    triage_acuity_score: float
    acceptance_acuity_score: float
    acuity_tier: str
    emergency_override: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Mission(TypedDict, total=False):
    id: str
    mission_request_id: str
    aircraft_id: str
    transport_class: str
    acuity_tier: str
    destination_facility: str
    estimated_loaded_miles: float
    planned_launch_iso: str
    planned_duration_min: int
    alternate_destination: Optional[str]
    launched_at: Optional[str]
    completed_at: Optional[str]
    last_weather_decision: Optional[str]
    ground_coordination_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CrewAssignment(TypedDict, total=False):
    id: str
    mission_id: str
    crew_member_id: str
    role_in_mission: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WeatherAssessment(TypedDict, total=False):
    """Immutable observation: carries id + created_at only (no updated_at/version)."""
    id: str
    mission_id: str
    ceiling_ft: int
    visibility_sm: float
    wind_kt: int
    precip: str
    day_night: str
    terrain: str
    decision: str
    assessed_at: str
    created_at: str


class GroundTransportLeg(TypedDict, total=False):
    id: str
    mission_id: str
    leg_type: str
    provider_name: str
    scheduled_pickup_iso: str
    estimated_ground_miles: Optional[float]
    bed_reservation_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BedReservation(TypedDict, total=False):
    id: str
    mission_id: str
    facility_name: str
    bed_type: str
    hold_until_iso: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InsuranceAuthorization(TypedDict, total=False):
    id: str
    mission_id: str
    payer_name: str
    policy_number: str
    approved_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    mission_id: str
    membership_id: Optional[str]
    estimated_loaded_miles: float
    actual_loaded_miles: Optional[float]
    base_line_cents: int
    mileage_line_cents: int
    fuel_line_cents: int
    acuity_line_cents: int
    logistics_line_cents: int
    ground_line_cents: int
    provisional_total_cents: int
    final_total_cents: Optional[int]
    insurer_paid_cents: int
    contractual_adjustment_cents: int
    member_writeoff_cents: int
    patient_responsibility_cents: int
    appeal_count: int
    claim_status: str
    member_adjustment_status: str
    created_at: str
    updated_at: str
    version: int


class RepatriationCase(TypedDict, total=False):
    id: str
    mission_id: str
    destination_country: str
    receiving_facility: str
    documents: List[Dict[str, Any]]
    status: str
    created_at: str
    updated_at: str
    version: int


class PatientCareReport(TypedDict, total=False):
    id: str
    mission_id: str
    author_crew_id: str
    vitals_summary: str
    interventions_summary: str
    meds_summary: str
    last_review_points: int
    submitted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
