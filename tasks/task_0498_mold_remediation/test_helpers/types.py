"""Domain types: entity TypedDicts, status enums, role enum (Mold Remediation API)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum (PRD §2.1) ─────────────────────────────────────────────────
class UserRole(str, Enum):
    PROJECT_MANAGER = "ProjectManager"
    ABATEMENT_SUPERVISOR = "AbatementSupervisor"
    LAB_TECH = "LabTech"
    HYGIENIST = "Hygienist"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# ─── Status / enum value sets ─────────────────────────────────────────────
class ProjectStatus(str, Enum):
    OPEN = "OPEN"
    SIGNED_OFF = "SIGNED_OFF"
    ABANDONED = "ABANDONED"


class ProjectPosture(str, Enum):
    ASSESSMENT = "ASSESSMENT"
    CONTAINED = "CONTAINED"
    ABATING = "ABATING"
    CLEARANCE_PENDING = "CLEARANCE_PENDING"
    VERIFIED = "VERIFIED"
    FROZEN = "FROZEN"


class HazardClass(str, Enum):
    ASBESTOS = "ASBESTOS"
    LEAD = "LEAD"
    MOLD = "MOLD"


class CertType(str, Enum):
    ASBESTOS = "ASBESTOS"
    LEAD = "LEAD"
    MOLD = "MOLD"
    HYGIENIST = "HYGIENIST"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SAMPLED = "SAMPLED"
    ANALYZED = "ANALYZED"
    CLEARED = "CLEARED"


class FindingLevel(str, Enum):
    CLEAN = "CLEAN"
    ELEVATED = "ELEVATED"
    HAZARDOUS = "HAZARDOUS"


class SampleType(str, Enum):
    AIR = "AIR"
    SURFACE = "SURFACE"


class SampleStatus(str, Enum):
    PENDING = "PENDING"
    ANALYZED = "ANALYZED"
    VOIDED = "VOIDED"


class ResultGrade(str, Enum):
    CLEAN = "CLEAN"
    ELEVATED = "ELEVATED"
    HAZARDOUS = "HAZARDOUS"


class ZoneStatus(str, Enum):
    SETUP = "SETUP"
    ACTIVE = "ACTIVE"
    BREACHED = "BREACHED"
    DISMANTLED = "DISMANTLED"


class AbatementType(str, Enum):
    ASBESTOS = "ASBESTOS"
    LEAD = "LEAD"
    MOLD = "MOLD"


class AbatementOrderStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    REOPENED = "REOPENED"
    CANCELLED = "CANCELLED"


class ManifestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    VOIDED = "VOIDED"


class ClearanceStatus(str, Enum):
    DRAFT = "DRAFT"
    ANALYZED = "ANALYZED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    SIGNED_OFF = "SIGNED_OFF"


class ClearanceOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class PermitType(str, Enum):
    NESHAP_NOTIFICATION = "NESHAP_NOTIFICATION"
    DEMOLITION = "DEMOLITION"
    TRANSPORT = "TRANSPORT"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    EXPIRED = "EXPIRED"


class ClaimStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    SETTLED = "SETTLED"
    DENIED = "DENIED"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


# ─── Entity TypedDicts ────────────────────────────────────────────────────
# Entities with common_fields:true carry id + created_at + updated_at + version.

class Project(TypedDict):
    id: str
    site_name: str
    hazard_class: str
    structure_sqft: int
    jurisdiction_code: str
    posture: str
    neshap_required: bool
    status: str
    open_finding_count: int
    created_at: str
    updated_at: str
    version: int


class Worker(TypedDict):
    id: str
    full_name: str
    cert_type: str
    cert_expires_at: str
    ppe_fit_test_at: str
    is_cert_current: bool
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict):
    id: str
    project_id: str
    assessor_worker_id: str
    area_label: str
    finding_level: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Sample(TypedDict):
    id: str
    assessment_id: str
    project_id: str
    sample_type: str
    collected_at: str
    volume_liters: Optional[float]
    raw_count: Optional[int]
    concentration: Optional[float]
    result_grade: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ContainmentZone(TypedDict):
    id: str
    project_id: str
    zone_label: str
    required_pressure_pa: float
    latest_pressure_pa: float
    is_compliant: bool
    status: str
    created_at: str
    updated_at: str
    version: int


# PressureLog has common_fields:false — append-only event: id + created_at ONLY.
class PressureLog(TypedDict):
    id: str
    zone_id: str
    reading_pa: float
    reading_at: str
    created_at: str


class AbatementOrder(TypedDict):
    id: str
    project_id: str
    zone_id: str
    lead_worker_id: str
    abatement_type: str
    planned_weight_kg: float
    removed_weight_kg: Optional[float]
    supersedes_order_id: Optional[str]
    revision_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DisposalManifest(TypedDict):
    id: str
    abatement_order_id: str
    project_id: str
    hauler_name: str
    manifest_weight_kg: float
    disposal_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ClearanceTest(TypedDict):
    id: str
    project_id: str
    zone_id: str
    abatement_order_id: str
    sampler_worker_id: str
    signoff_worker_id: Optional[str]
    clearance_air_count: int
    clearance_volume_liters: float
    clearance_concentration: Optional[float]
    outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    project_id: str
    permit_type: str
    postmarked_at: str
    work_start_at: str
    notice_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InsuranceClaim(TypedDict):
    id: str
    project_id: str
    policy_number: str
    deductible_cents: int
    coverage_limit_cents: int
    estimated_amount_cents: int
    settled_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkerAssignment(TypedDict):
    id: str
    abatement_order_id: str
    worker_id: str
    shift_start_at: str
    shift_end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
