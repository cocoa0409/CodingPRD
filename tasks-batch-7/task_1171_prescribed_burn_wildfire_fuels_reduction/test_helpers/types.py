"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    ASSOCIATION_ADMIN = "AssociationAdmin"
    LANDOWNER = "Landowner"
    BURN_BOSS = "BurnBoss"
    AGENCY_REVIEWER = "AgencyReviewer"
    AIR_QUALITY_OFFICER = "AirQualityOfficer"
    INCIDENT_COMMANDER = "IncidentCommander"
    CONTRACTOR = "Contractor"


class FuelModel(str, Enum):
    GRASS = "GRASS"
    BRUSH = "BRUSH"
    TIMBER = "TIMBER"


class SlopeClass(str, Enum):
    FLAT = "FLAT"
    MODERATE = "MODERATE"
    STEEP = "STEEP"


class CertTier(str, Enum):
    RXB1 = "RXB1"
    RXB2 = "RXB2"
    RXB3 = "RXB3"


class ResourceType(str, Enum):
    ENGINE = "ENGINE"
    HAND_CREW = "HAND_CREW"
    DOZER = "DOZER"
    WATER_TENDER = "WATER_TENDER"


class BurnPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class BurnPermitStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    ISSUED = "ISSUED"
    DENIED = "DENIED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class NotificationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"


class SmokeApprovalStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    CONDITIONALLY_APPROVED = "CONDITIONALLY_APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"


class ContingencyPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class IgnitionPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ResourceOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


class CrewAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"
    RELEASED = "RELEASED"
    NO_SHOW = "NO_SHOW"
    COMPLETED = "COMPLETED"


class ExecutionPhase(str, Enum):
    SCHEDULED = "SCHEDULED"
    BRIEFED = "BRIEFED"
    TEST_FIRE = "TEST_FIRE"
    IGNITION = "IGNITION"
    HOLDING = "HOLDING"
    PATROL = "PATROL"
    MOP_UP = "MOP_UP"
    CLOSED = "CLOSED"
    ESCAPED = "ESCAPED"
    WILDFIRE_RESPONSE = "WILDFIRE_RESPONSE"
    STOOD_DOWN = "STOOD_DOWN"
    CANCELLED = "CANCELLED"
    LAPSED = "LAPSED"


class IncidentResponseStatus(str, Enum):
    REPORTED = "REPORTED"
    CONFIRMED = "CONFIRMED"
    CONTAINED = "CONTAINED"
    CLOSED = "CLOSED"
    DISMISSED = "DISMISSED"
    DECLARED_WILDFIRE = "DECLARED_WILDFIRE"


class IncidentBillingStatus(str, Enum):
    UNASSESSED = "UNASSESSED"
    ASSESSED = "ASSESSED"
    BILLED = "BILLED"
    SETTLED = "SETTLED"
    DISPUTED = "DISPUTED"


class MonitoringReportStatus(str, Enum):
    DUE = "DUE"
    OVERDUE = "OVERDUE"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    DEFICIENT = "DEFICIENT"


class CostShareStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PARTIALLY_DISBURSED = "PARTIALLY_DISBURSED"
    FULLY_DISBURSED = "FULLY_DISBURSED"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    ADJUDICATED = "ADJUDICATED"
    DISMISSED = "DISMISSED"
    PAID = "PAID"
    PAYMENT_REVERSED = "PAYMENT_REVERSED"
    CLOSED = "CLOSED"


class BurnAssociation(TypedDict, total=False):
    id: str
    name: str
    airshed_daily_acres_cap: int
    single_claim_cap_cents: int
    landowner_liability_cap_cents: int
    fund_balance_cents: int
    fund_posture: str
    created_at: str
    updated_at: str
    version: int


class Landowner(TypedDict, total=False):
    id: str
    name: str
    contact_email: str
    liability_waiver_signed: bool
    standing: str
    outstanding_liability_cents: int
    created_at: str
    updated_at: str
    version: int


class Parcel(TypedDict, total=False):
    id: str
    landowner_id: str
    name: str
    acreage: int
    fuel_model: str
    slope_class: str
    wui_adjacent: bool
    airshed_id: str
    drought_index: int
    hazard_score: int
    created_at: str
    updated_at: str
    version: int


class BurnBoss(TypedDict, total=False):
    id: str
    name: str
    certification_tier: str
    created_at: str
    updated_at: str
    version: int


class Contractor(TypedDict, total=False):
    id: str
    name: str
    resource_type: str
    capacity_units: int
    personnel_per_unit: int
    day_rate_cents_per_unit: int
    no_show_count: int
    standing: str
    available_units: int
    created_at: str
    updated_at: str
    version: int


class TreatmentLine(TypedDict):
    category: str
    rate_class: str
    acres: int


class BurnPlan(TypedDict, total=False):
    id: str
    parcel_id: str
    author_boss_id: str
    supersedes_plan_id: Optional[str]
    planned_acres: int
    planned_window_start: str
    planned_window_end: str
    max_wind_mph: int
    min_fuel_moisture_pct: int
    max_fuel_moisture_pct: int
    min_rh_pct: int
    min_temp_f: int
    max_temp_f: int
    min_mixing_height_ft: int
    treatment_lines: List[Dict[str, Any]]
    approved_by_boss_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BurnPermit(TypedDict, total=False):
    id: str
    burn_plan_id: str
    notifications_required: int
    notifications_completed: int
    notified_completed_at: Optional[str]
    issued_by_boss_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PermitNotification(TypedDict, total=False):
    id: str
    burn_permit_id: str
    recipient_name: str
    channel: str
    confirmed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SmokeApproval(TypedDict, total=False):
    id: str
    burn_plan_id: str
    airshed_id: str
    requested_burn_date: str
    requested_acres: int
    decision_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ContingencyPlan(TypedDict, total=False):
    id: str
    burn_plan_id: str
    escape_trigger_points: str
    min_holding_personnel: int
    water_supply_description: str
    evacuation_route_description: str
    status: str
    created_at: str
    updated_at: str
    version: int


class IgnitionStep(TypedDict):
    step_index: int
    zone_label: str
    technique: str


class IgnitionPlan(TypedDict, total=False):
    id: str
    burn_plan_id: str
    ignition_method: str
    test_fire_required: bool
    steps: List[Dict[str, Any]]
    status: str
    created_at: str
    updated_at: str
    version: int


class ResourceOrder(TypedDict, total=False):
    id: str
    burn_plan_id: str
    required_engines: int
    required_hand_crews: int
    required_dozers: int
    required_water_tenders: int
    confirmed_engines: int
    confirmed_hand_crews: int
    confirmed_dozers: int
    confirmed_water_tenders: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CrewAssignment(TypedDict, total=False):
    id: str
    resource_order_id: str
    contractor_id: str
    units: int
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BurnExecution(TypedDict, total=False):
    id: str
    burn_plan_id: str
    scheduled_date: str
    plan_version_at_schedule: int
    acres_blackened: Optional[int]
    actual_treatment_lines: Optional[List[Dict[str, Any]]]
    closed_at: Optional[str]
    phase: str
    created_at: str
    updated_at: str
    version: int


# Audit-record resource (PRD §2.4): carries ONLY id + created_at.
class WeatherObservation(TypedDict, total=False):
    id: str
    burn_execution_id: str
    observed_at: str
    wind_mph: int
    fuel_moisture_pct: int
    rh_pct: int
    temp_f: int
    mixing_height_ft: int
    in_prescription: bool
    created_at: str


# Audit-record resource (PRD §2.4): carries ONLY id + created_at.
class GoNoGoChecklist(TypedDict, total=False):
    id: str
    burn_execution_id: str
    weather_observation_id: str
    answers: List[Dict[str, str]]
    verdict: str
    evaluated_at: str
    created_at: str


class Incident(TypedDict, total=False):
    id: str
    burn_execution_id: str
    incident_type: str
    response_status: str
    billing_status: str
    suppression_cost_cents: Optional[int]
    escaped_acres: Optional[int]
    created_at: str
    updated_at: str
    version: int


class MonitoringReport(TypedDict, total=False):
    id: str
    burn_execution_id: str
    report_type: str
    due_at: str
    actual_treatment_lines: Optional[List[Dict[str, Any]]]
    effectiveness_score: Optional[int]
    deficiency_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CostShareAgreement(TypedDict, total=False):
    id: str
    landowner_id: str
    burn_plan_id: str
    funding_tier: str
    treatment_lines: List[Dict[str, Any]]
    provisional_estimate_cents: int
    final_reimbursement_cents: Optional[int]
    disbursed_cents: int
    approved_at: Optional[str]
    expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LiabilityClaim(TypedDict, total=False):
    id: str
    incident_id: str
    total_suppression_cost_cents: int
    negligence_found: Optional[bool]
    landowner_share_cents: Optional[int]
    association_share_cents: Optional[int]
    fund_payout_cents: Optional[int]
    outcome: str
    adjudicated_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
