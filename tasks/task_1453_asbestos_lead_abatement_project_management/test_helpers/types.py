"""Domain types: entity TypedDicts, status enums, role enum.

All twelve resource families carry the common system-managed properties
(id, created_at, updated_at, version) described in PRD section 2.5.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    CONTRACTOR_ADMIN = "ContractorAdmin"
    SUPERVISOR = "Supervisor"
    INDUSTRIAL_HYGIENIST = "IndustrialHygienist"
    REGULATOR_CLERK = "RegulatorClerk"
    FACILITY_OPERATOR = "FacilityOperator"


class WorkType(str, Enum):
    RENOVATION = "RENOVATION"
    DEMOLITION = "DEMOLITION"


class HazardClass(str, Enum):
    ASBESTOS = "ASBESTOS"
    LEAD = "LEAD"
    MIXED = "MIXED"


class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    ASSESSED = "ASSESSED"
    IN_PROGRESS = "IN_PROGRESS"
    SUSPENDED = "SUSPENDED"
    AWAITING_CLEARANCE = "AWAITING_CLEARANCE"
    RECLEANING = "RECLEANING"
    CLOSED = "CLOSED"


class ReoccupancyStatus(str, Enum):
    BLOCKED = "BLOCKED"
    OPEN = "OPEN"


class SurveyStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_LAB = "IN_LAB"
    FINALIZED = "FINALIZED"


class LabResult(str, Enum):
    PENDING = "PENDING"
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"


class SampleStatus(str, Enum):
    PENDING = "PENDING"
    REPORTED = "REPORTED"


class CertificationLevel(str, Enum):
    SUPERVISOR = "SUPERVISOR"
    HANDLER = "HANDLER"


class WorkerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"


class RoleOnSite(str, Enum):
    SUPERVISOR = "SUPERVISOR"
    HANDLER = "HANDLER"


class AssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class NotificationType(str, Enum):
    INITIAL = "INITIAL"
    REVISION = "REVISION"
    EMERGENCY = "EMERGENCY"


class NotificationStatus(str, Enum):
    FILED = "FILED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    SUPERSEDED = "SUPERSEDED"


class ContainmentClass(str, Enum):
    FULL = "FULL"
    MINI_ENCLOSURE = "MINI_ENCLOSURE"
    GLOVE_BAG = "GLOVE_BAG"


class ContainmentStatus(str, Enum):
    DESIGNED = "DESIGNED"
    INSTALLED = "INSTALLED"
    VERIFIED = "VERIFIED"
    RECLEAN_REQUIRED = "RECLEAN_REQUIRED"


class AirTestPhase(str, Enum):
    BASELINE = "BASELINE"
    DAILY = "DAILY"
    CLEARANCE = "CLEARANCE"


class AirTestOutcome(str, Enum):
    NA = "NA"
    PASS = "PASS"
    FAIL = "FAIL"


class AirTestStatus(str, Enum):
    COLLECTED = "COLLECTED"
    REPORTED = "REPORTED"


class ManifestStatus(str, Enum):
    DRAFT = "DRAFT"
    SEALED = "SEALED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class FacilityStatus(str, Enum):
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"


class UnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"
    CLEANING = "CLEANING"


class RelocationStatus(str, Enum):
    HOUSED = "HOUSED"
    EXTENDED = "EXTENDED"
    RETURNED = "RETURNED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all carry id / created_at / updated_at / version)
# ---------------------------------------------------------------------------

class Project(TypedDict, total=False):
    id: str
    name: str
    site_address: str
    work_type: str
    hazard_class: str
    planned_start: str
    base_abatement_cost_cents: int
    status: str
    total_acm_sq_ft: float
    estimated_disposal_cost_cents: int
    manifested_weight_lbs: float
    final_disposal_cost_cents: int
    insurance_surcharge_cents: int
    total_project_cost_cents: int
    reoccupancy_status: str
    created_at: str
    updated_at: str
    version: int


class Survey(TypedDict, total=False):
    id: str
    project_id: str
    surveyor_name: str
    survey_date: str
    status: str
    acm_sq_ft_provisional: float
    acm_sq_ft_final: float
    friable_acm_sq_ft_final: float
    created_at: str
    updated_at: str
    version: int


class Sample(TypedDict, total=False):
    id: str
    survey_id: str
    material: str
    location_desc: str
    quantity_sq_ft: float
    friable: bool
    lab_result: str
    asbestos_pct: Optional[float]
    lead_ppm: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Worker(TypedDict, total=False):
    id: str
    full_name: str
    certification_level: str
    cert_expires_at: str
    medical_clearance_expires_at: str
    respirator_fit_expires_at: str
    status: str
    assigned_scheduled_hours: float
    created_at: str
    updated_at: str
    version: int


class CrewAssignment(TypedDict, total=False):
    id: str
    project_id: str
    worker_id: str
    role_on_site: str
    start_at: str
    end_at: str
    scheduled_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class RegulatoryNotification(TypedDict, total=False):
    id: str
    project_id: str
    notification_type: str
    declared_acm_sq_ft: float
    filed_at: str
    waiting_days: int
    earliest_start_at: str
    status: str
    acknowledged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Containment(TypedDict, total=False):
    id: str
    project_id: str
    work_area_volume_cuft: float
    containment_class: str
    air_changes_per_hour: float
    machines_required: int
    last_pressure_reading_inwg: Optional[float]
    verified_by_user_id: Optional[str]
    last_verified_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AirTest(TypedDict, total=False):
    id: str
    project_id: str
    phase: str
    collected_at: str
    result_f_cc: Optional[float]
    outcome: str
    result_recorded_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WasteManifest(TypedDict, total=False):
    id: str
    project_id: str
    facility_id: str
    bags_count: int
    gross_weight_lbs: float
    net_weight_lbs: float
    net_tons: float
    fee_cents: Optional[int]
    sealed_by_user_id: Optional[str]
    delivered_at: Optional[str]
    reject_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DisposalFacility(TypedDict, total=False):
    id: str
    name: str
    epa_id: str
    accepted_hazards: List[str]
    monthly_capacity_tons: float
    delivered_tons_current_month: float
    status: str
    created_at: str
    updated_at: str
    version: int


class RelocationUnit(TypedDict, total=False):
    id: str
    unit_label: str
    capacity_persons: int
    status: str
    cleaning_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RelocationRecord(TypedDict, total=False):
    id: str
    project_id: str
    unit_id: str
    household_name: str
    persons: int
    move_out_at: str
    returned_at: Optional[str]
    extension_count: int
    status: str
    created_at: str
    updated_at: str
    version: int
