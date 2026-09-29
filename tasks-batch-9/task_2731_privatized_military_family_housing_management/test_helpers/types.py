"""Domain types: status enums, role enum, and entity TypedDicts.

Field names mirror the PRD exactly. Two entities are immutable once written —
a BahRate row and an AllotmentTransaction row carry only ``id`` and
``created_at`` (PRD §2.4) — so their TypedDicts deliberately omit
``updated_at`` and ``version``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PROPERTY_MANAGER = "PropertyManager"
    SERVICE_MEMBER = "ServiceMember"
    MAINTENANCE_TECH = "MaintenanceTech"
    ENVIRONMENTAL_SPECIALIST = "EnvironmentalSpecialist"
    INSTALLATION_HOUSING_OFFICE = "InstallationHousingOffice"


class Branch(str, Enum):
    ARMY = "ARMY"
    NAVY = "NAVY"
    AIR_FORCE = "AIR_FORCE"
    MARINE_CORPS = "MARINE_CORPS"


class RankCategory(str, Enum):
    JUNIOR_ENLISTED = "JUNIOR_ENLISTED"
    SENIOR_ENLISTED = "SENIOR_ENLISTED"
    WARRANT_OFFICER = "WARRANT_OFFICER"
    JUNIOR_OFFICER = "JUNIOR_OFFICER"
    SENIOR_OFFICER = "SENIOR_OFFICER"


class UnitType(str, Enum):
    SFH = "SFH"
    DUPLEX = "DUPLEX"
    TOWNHOME = "TOWNHOME"
    APARTMENT = "APARTMENT"


class HousingUnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    OCCUPIED = "OCCUPIED"
    OFFLINE_MAINTENANCE = "OFFLINE_MAINTENANCE"
    HAZARD_HOLD = "HAZARD_HOLD"


class AccessibilityFeature(str, Enum):
    ROLL_IN_SHOWER = "ROLL_IN_SHOWER"
    ZERO_STEP_ENTRY = "ZERO_STEP_ENTRY"
    WIDENED_DOORWAYS = "WIDENED_DOORWAYS"


class DeploymentStatus(str, Enum):
    NOT_DEPLOYED = "NOT_DEPLOYED"
    DEPLOYED = "DEPLOYED"
    RETURNED = "RETURNED"


class DependentRelationship(str, Enum):
    SPOUSE = "SPOUSE"
    CHILD = "CHILD"
    OTHER_AUTHORIZED = "OTHER_AUTHORIZED"


class Gender(str, Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"


class WaitlistApplicationStatus(str, Enum):
    PENDING = "PENDING"
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    EXPIRED = "EXPIRED"
    HOUSED = "HOUSED"


class LeaseOccupancyStatus(str, Enum):
    PENDING_MOVE_IN = "PENDING_MOVE_IN"
    OCCUPIED = "OCCUPIED"
    NOTICE_GIVEN = "NOTICE_GIVEN"
    TERMINATED = "TERMINATED"


class LeaseAllotmentStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class RentBasis(str, Enum):
    OFFER_PROVISIONAL = "OFFER_PROVISIONAL"
    MOVE_IN_FINAL = "MOVE_IN_FINAL"


class TerminationReason(str, Enum):
    PCS = "PCS"
    DEPLOYMENT = "DEPLOYMENT"
    SEPARATION = "SEPARATION"
    CONVENIENCE = "CONVENIENCE"
    LANDLORD = "LANDLORD"


class MoveInInspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DEFICIENCIES_LOGGED = "DEFICIENCIES_LOGGED"
    TENANT_ACKNOWLEDGED = "TENANT_ACKNOWLEDGED"
    COMPLETED = "COMPLETED"


class DeficiencySeverity(str, Enum):
    COSMETIC = "COSMETIC"
    FUNCTIONAL = "FUNCTIONAL"
    HABITABILITY_CRITICAL = "HABITABILITY_CRITICAL"


class DeficiencyEntryStatus(str, Enum):
    OPEN = "OPEN"
    WORK_ORDER_CREATED = "WORK_ORDER_CREATED"
    RESOLVED = "RESOLVED"


class WorkOrderCategory(str, Enum):
    NO_HEAT = "NO_HEAT"
    NO_WATER = "NO_WATER"
    GAS_LEAK = "GAS_LEAK"
    SEWAGE_BACKUP = "SEWAGE_BACKUP"
    ELECTRICAL = "ELECTRICAL"
    PLUMBING_LEAK = "PLUMBING_LEAK"
    HVAC = "HVAC"
    APPLIANCE = "APPLIANCE"
    COSMETIC = "COSMETIC"
    GROUNDS = "GROUNDS"
    MOLD_SUSPECTED = "MOLD_SUSPECTED"
    LEAD_SUSPECTED = "LEAD_SUSPECTED"


class WorkOrderPriorityClass(str, Enum):
    EMERGENCY = "EMERGENCY"
    URGENT = "URGENT"
    ROUTINE = "ROUTINE"


class WorkOrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    REOPENED = "REOPENED"
    CLOSED = "CLOSED"


class HazardType(str, Enum):
    MOLD = "MOLD"
    LEAD_PAINT = "LEAD_PAINT"
    LEAD_WATER = "LEAD_WATER"


class HazardSeverity(str, Enum):
    SEVERITY_1 = "SEVERITY_1"
    SEVERITY_2 = "SEVERITY_2"
    SEVERITY_3 = "SEVERITY_3"


class HazardCaseStatus(str, Enum):
    REPORTED = "REPORTED"
    ASSESSED = "ASSESSED"
    REMEDIATION_IN_PROGRESS = "REMEDIATION_IN_PROGRESS"
    DISPLACEMENT_ACTIVE = "DISPLACEMENT_ACTIVE"
    CLEARANCE_PENDING = "CLEARANCE_PENDING"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"


class DisplacementLodgingStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    CLOSED = "CLOSED"


class DisputeCategory(str, Enum):
    RENT_CHARGE = "RENT_CHARGE"
    MAINTENANCE_QUALITY = "MAINTENANCE_QUALITY"
    HABITABILITY = "HABITABILITY"
    DAMAGE_CLAIM = "DAMAGE_CLAIM"
    UTILITY_BILLING = "UTILITY_BILLING"


class DisputeCaseStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    PROPOSED_RESOLUTION = "PROPOSED_RESOLUTION"
    RESIDENT_REJECTED = "RESIDENT_REJECTED"
    ESCALATED_INSTALLATION = "ESCALATED_INSTALLATION"
    CLOSED_RESOLVED = "CLOSED_RESOLVED"


class AllotmentTransactionType(str, Enum):
    CHARGE = "CHARGE"
    ABATEMENT = "ABATEMENT"
    REFUND = "REFUND"
    ARREARS_ADJUSTMENT = "ARREARS_ADJUSTMENT"
    EARLY_TERMINATION_FEE = "EARLY_TERMINATION_FEE"


class OccupancyBasis(str, Enum):
    UNIT_DAY_WEIGHTED = "UNIT_DAY_WEIGHTED"
    MONTH_END_SNAPSHOT = "MONTH_END_SNAPSHOT"


# --- Entity shapes -----------------------------------------------------------


class Installation(TypedDict):
    id: str
    name: str
    branch: str
    mha_code: str
    bill_of_rights_version: str
    turn_buffer_days: int
    offer_response_hours: int
    decline_limit: int
    decline_penalty_days: int
    incentive_base_pct: float
    total_unit_count: int
    available_unit_count: int
    assigned_unit_count: int
    occupied_unit_count: int
    offline_unit_count: int
    hazard_hold_unit_count: int
    pending_application_count: int
    offer_run_epoch: int
    last_offer_run_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BahRate(TypedDict):
    """Immutable configuration row — no ``updated_at``, no ``version``."""

    id: str
    installation_id: str
    pay_grade: str
    with_dependents: bool
    effective_year: int
    monthly_rate_cents: int
    utility_allowance_cents: int
    created_at: str


class HousingUnit(TypedDict):
    id: str
    installation_id: str
    unit_code: str
    bedroom_count: int
    unit_type: str
    designated_rank_category: str
    historic_flag: bool
    accessibility_features: List[str]
    status: str
    hazard_hold_reason: Optional[str]
    last_lease_end_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceMember(TypedDict):
    id: str
    dodid: str
    last_name: str
    first_name: str
    branch: str
    pay_grade: str
    rank_category: str
    deployment_status: str
    deployment_orders_ref: Optional[str]
    expected_return_date: Optional[str]
    pcs_orders_ref: Optional[str]
    pcs_report_date: Optional[str]
    dependent_count: int
    created_at: str
    updated_at: str
    version: int


class Dependent(TypedDict):
    id: str
    service_member_id: str
    relationship: str
    date_of_birth: str
    gender: str
    is_full_time_custody: bool
    created_at: str
    updated_at: str
    version: int


class WaitlistApplication(TypedDict):
    id: str
    installation_id: str
    service_member_id: str
    pcs_orders_date: str
    expected_arrival_date: str
    accessibility_required: bool
    rank_category: str
    dependent_count_at_application: int
    bedroom_eligibility: int
    effective_control_date: str
    status: str
    decline_count: int
    offer_count: int
    offered_unit_id: Optional[str]
    offer_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict):
    id: str
    application_id: str
    housing_unit_id: str
    service_member_id: str
    start_date: str
    term_months: int
    occupancy_status: str
    allotment_status: str
    rent_basis: str
    rent_effective_year: int
    gross_rent_cents: int
    utility_allowance_cents: int
    net_rent_cents: int
    daily_rent_cents: int
    bill_of_rights_version_ack: Optional[str]
    bill_of_rights_ack_at: Optional[str]
    termination_reason: Optional[str]
    termination_notice_date: Optional[str]
    termination_effective_date: Optional[str]
    early_termination_fee_cents: int
    settlement_total_cents: int
    allotment_balance_cents: int
    abatement_total_cents: int
    created_at: str
    updated_at: str
    version: int


class MoveInInspection(TypedDict):
    id: str
    lease_id: str
    scheduled_date: str
    conducted_by_user_id: str
    status: str
    deficiencies: List[dict]
    deficiency_count: int
    critical_open_count: int
    tenant_signature_name: Optional[str]
    tenant_signature_at: Optional[str]
    bill_of_rights_version_ack: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    housing_unit_id: str
    lease_id: Optional[str]
    parent_work_order_id: Optional[str]
    inspection_deficiency_code: Optional[str]
    category: str
    description: str
    habitability_impact: bool
    priority_class: str
    reported_at: str
    response_due_at: str
    completion_due_at: str
    first_response_at: Optional[str]
    completed_at: Optional[str]
    sla_breached: bool
    escalation_level: int
    escalated_at: Optional[str]
    reopen_count: int
    assigned_tech_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class HazardCase(TypedDict):
    id: str
    housing_unit_id: str
    lease_id: Optional[str]
    source_work_order_id: Optional[str]
    remediation_work_order_id: Optional[str]
    hazard_type: str
    reported_symptoms: str
    affected_area_sqft: Optional[float]
    lead_level_ppm: Optional[float]
    assessment_severity: Optional[str]
    child_under_six_present: bool
    displacement_required: bool
    assessed_by_user_id: Optional[str]
    assessed_at: Optional[str]
    cleared_by_user_id: Optional[str]
    clearance_test_passed: Optional[bool]
    status: str
    created_at: str
    updated_at: str
    version: int


class DisplacementLodging(TypedDict):
    id: str
    hazard_case_id: str
    lease_id: str
    start_date: str
    end_date: str
    nightly_rate_cents: int
    occupants_count: int
    actual_end_date: Optional[str]
    nights_displaced: int
    per_night_authorized_cents: int
    lodging_authorized_cents: int
    rent_abatement_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DisputeCase(TypedDict):
    id: str
    lease_id: str
    service_member_id: str
    category: str
    description: str
    status: str
    round_count: int
    proposed_remedy: Optional[str]
    credit_offer_cents: int
    proposed_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    credit_award_cents: int
    opened_at: str
    resolution_due_at: str
    escalated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AllotmentTransaction(TypedDict):
    """Append-only ledger row — no ``updated_at``, no ``version``."""

    id: str
    lease_id: str
    period_month: str
    type: str
    amount_cents: int
    source_ref: str
    posted_at: str
    running_balance_cents: int
    created_at: str


class ReinvestmentAccount(TypedDict):
    id: str
    installation_id: str
    fiscal_year: int
    opening_balance_cents: int
    contributions_cents: int
    expenditures_cents: int
    closing_balance_cents: int
    occupancy_basis: str
    occupancy_rate_pct: Optional[float]
    net_collected_cents: int
    habitability_penalty_pct: float
    performance_incentive_fee_cents: int
    metrics_run_epoch: int
    last_metrics_run_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
