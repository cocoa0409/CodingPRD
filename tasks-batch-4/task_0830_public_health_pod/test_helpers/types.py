"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Public-Health-Pod-Preparedness PRD's entity definitions
and state machines.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Enums: computed lifecycle/status fields
# --------------------------------------------------------------------------

class HazardPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVATED = "ACTIVATED"
    STOOD_DOWN = "STOOD_DOWN"


class PODOperationalStatus(str, Enum):
    STAGING = "STAGING"
    OPERATIONAL = "OPERATIONAL"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class PODRiskTier(str, Enum):
    STANDARD = "STANDARD"
    ELEVATED = "ELEVATED"
    CRITICAL = "CRITICAL"


class StaffMemberCredentialStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REVOKED = "REVOKED"


class ShiftAssignmentStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AllocationRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RESERVED = "RESERVED"
    FULFILLED = "FULFILLED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class DispensingEventStatus(str, Enum):
    REGISTERED = "REGISTERED"
    SCREENED = "SCREENED"
    DEFERRED = "DEFERRED"
    REFUSED = "REFUSED"
    DISPENSED = "DISPENSED"


class DrillStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DrillCorrectiveActionStatus(str, Enum):
    NONE = "NONE"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class SituationReportReadinessStatus(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


# --------------------------------------------------------------------------
# Enums: input-field controlled vocabularies
# --------------------------------------------------------------------------

class HazardType(str, Enum):
    PANDEMIC_INFLUENZA = "PANDEMIC_INFLUENZA"
    BIOTERRORISM_ANTHRAX = "BIOTERRORISM_ANTHRAX"
    RADIOLOGICAL_INCIDENT = "RADIOLOGICAL_INCIDENT"
    CHEMICAL_RELEASE = "CHEMICAL_RELEASE"
    NATURAL_DISASTER = "NATURAL_DISASTER"
    OUTBREAK_OTHER = "OUTBREAK_OTHER"


class PODSiteType(str, Enum):
    FIXED_POD = "FIXED_POD"
    MOBILE_POD = "MOBILE_POD"
    DRIVE_THROUGH = "DRIVE_THROUGH"
    CLOSED_POD = "CLOSED_POD"


class StaffFunctionalRole(str, Enum):
    CLINICAL_LEAD = "CLINICAL_LEAD"
    SCREENER = "SCREENER"
    VACCINATOR = "VACCINATOR"
    RUNNER = "RUNNER"
    TRAFFIC_CONTROL = "TRAFFIC_CONTROL"
    GREETER = "GREETER"


class CredentialType(str, Enum):
    RN_LICENSE = "RN_LICENSE"
    MD_LICENSE = "MD_LICENSE"
    EMT_CERT = "EMT_CERT"
    NIMS_IS100_700 = "NIMS_IS100_700"
    BACKGROUND_CHECK = "BACKGROUND_CHECK"
    PODS_TRAINING = "PODS_TRAINING"


class CountermeasureType(str, Enum):
    VACCINE = "VACCINE"
    ANTIVIRAL = "ANTIVIRAL"
    ANTIBIOTIC_PEP = "ANTIBIOTIC_PEP"


class AllocationSourceType(str, Enum):
    SNS_CACHE = "SNS_CACHE"
    MUTUAL_AID = "MUTUAL_AID"


class RegistrantRiskGroup(str, Enum):
    GENERAL_PUBLIC = "GENERAL_PUBLIC"
    HEALTHCARE_WORKER = "HEALTHCARE_WORKER"
    FIRST_RESPONDER = "FIRST_RESPONDER"
    HIGH_RISK_MEDICAL = "HIGH_RISK_MEDICAL"


class DrillType(str, Enum):
    TABLETOP = "TABLETOP"
    FUNCTIONAL = "FUNCTIONAL"
    FULL_SCALE = "FULL_SCALE"


class UserRole(str, Enum):
    PUBLIC_HEALTH_ADMIN = "PublicHealthAdmin"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    MUTUAL_AID_PARTNER = "MutualAidPartner"
    CLINICAL_LEAD = "ClinicalLead"
    VOLUNTEER = "Volunteer"


# --------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true -> id, created_at, updated_at, version)
# --------------------------------------------------------------------------

class HazardPlan(TypedDict):
    id: str
    hazard_type: str
    title: str
    jurisdiction_code: str
    target_population: int
    status: str
    activated_at: Optional[str]
    stood_down_at: Optional[str]
    readiness_score: float
    created_at: str
    updated_at: str
    version: int


class POD(TypedDict):
    id: str
    hazard_plan_id: str
    site_name: str
    site_type: str
    address: str
    staffing_capacity_lanes: int
    lane_throughput_rate_per_hour: int
    operational_status: str
    risk_tier: str
    queue_backlog_count: int
    open_allocation_request_count: int
    committed_staff_hours: float
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict):
    id: str
    full_name: str
    email: str
    primary_role: str
    mrc_unit: str
    credential_type: str
    credential_expires_at: str
    credential_status: str
    created_at: str
    updated_at: str
    version: int


class ShiftAssignment(TypedDict):
    id: str
    pod_id: str
    staff_member_id: str
    assigned_role: str
    start_time: str
    end_time: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Countermeasure(TypedDict):
    id: str
    name: str
    countermeasure_type: str
    doses_required: int
    dose_interval_days: int
    unit_cost_cents: int
    reorder_point_quantity: int
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict):
    id: str
    countermeasure_id: str
    pod_id: Optional[str]
    lot_number: str
    on_hand_quantity: int
    reserved_quantity: int
    available_quantity: int
    expiration_date: str
    created_at: str
    updated_at: str
    version: int


class AllocationRequest(TypedDict):
    id: str
    pod_id: str
    countermeasure_id: str
    source_type: str
    partner_pod_id: Optional[str]
    requested_quantity: int
    status: str
    reserved_quantity: int
    fulfilled_quantity: int
    source_inventory_lot_id: Optional[str]
    priority_score: float
    reimbursement_cost_usd: float
    created_at: str
    updated_at: str
    version: int


class DispensingEvent(TypedDict):
    id: str
    pod_id: str
    countermeasure_id: str
    inventory_lot_id: Optional[str]
    registrant_full_name: str
    registrant_risk_group: str
    dose_count: int
    status: str
    screened_by_staff_member_id: Optional[str]
    dispensed_by_staff_member_id: Optional[str]
    deferral_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Drill(TypedDict):
    id: str
    hazard_plan_id: str
    drill_type: str
    scheduled_at: str
    status: str
    finding: Optional[str]
    corrective_action: Optional[str]
    corrective_action_status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only snapshot, carries ONLY id + created_at
class SituationReport(TypedDict):
    id: str
    hazard_plan_id: str
    report_period_label: str
    pods_operational_count: int
    pods_restricted_count: int
    total_doses_dispensed: int
    total_on_hand_inventory: int
    staffing_fill_rate_pct: float
    total_mutual_aid_reimbursement_usd: float
    readiness_status: str
    narrative: Optional[str]
    created_at: str
