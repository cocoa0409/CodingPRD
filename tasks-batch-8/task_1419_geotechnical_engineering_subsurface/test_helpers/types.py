"""Domain types: entity TypedDicts, status enums, role enum.

Every resource carries the four system-managed properties id, created_at,
updated_at, version (PRD section 2.4).
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    FIRM_ADMIN = "FirmAdmin"
    CLIENT_REP = "ClientRep"
    PROJECT_MANAGER = "ProjectManager"
    STAFF_ENGINEER = "StaffEngineer"
    FIELD_GEOLOGIST = "FieldGeologist"
    DRILLING_SUB = "DrillingSub"
    LAB_MANAGER = "LabManager"
    LAB_TECHNICIAN = "LabTechnician"
    SENIOR_ENGINEER = "SeniorEngineer"
    PRINCIPAL_ENGINEER = "PrincipalEngineer"


class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    SCOPED = "SCOPED"
    FIELD_AUTHORIZED = "FIELD_AUTHORIZED"
    FIELDWORK = "FIELDWORK"
    LAB_ANALYSIS = "LAB_ANALYSIS"
    REPORT_REVIEW = "REPORT_REVIEW"
    ISSUED = "ISSUED"
    CONSTRUCTION_SUPPORT = "CONSTRUCTION_SUPPORT"
    CLOSED = "CLOSED"


class ProjectPosture(str, Enum):
    OPEN = "OPEN"
    FROZEN = "FROZEN"
    CLAIM_REVIEW = "CLAIM_REVIEW"


class BoringPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    LOCKED = "LOCKED"
    SUPERSEDED = "SUPERSEDED"


class SubcontractorStanding(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    SUSPENDED = "SUSPENDED"


class RigAssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    MOBILIZED = "MOBILIZED"
    DEMOBILIZED = "DEMOBILIZED"
    CANCELLED = "CANCELLED"


class ClearanceStatus(str, Enum):
    FILED = "FILED"
    CLEARED = "CLEARED"
    CONFLICT_MARKED = "CONFLICT_MARKED"
    EXPIRED = "EXPIRED"


class BoringStatus(str, Enum):
    PLANNED = "PLANNED"
    SCHEDULED = "SCHEDULED"
    CLEARED = "CLEARED"
    DRILLED = "DRILLED"
    LOGGED = "LOGGED"
    CLOSED = "CLOSED"
    REFUSED = "REFUSED"
    ABANDONED = "ABANDONED"


class SampleCustody(str, Enum):
    COLLECTED = "COLLECTED"
    IN_TRANSIT = "IN_TRANSIT"
    LAB_RECEIVED = "LAB_RECEIVED"
    CONSUMED = "CONSUMED"
    ARCHIVED = "ARCHIVED"
    LOST = "LOST"


class SamplerType(str, Enum):
    SPT = "SPT"
    SHELBY = "SHELBY"
    BULK = "BULK"
    ROCK_CORE = "ROCK_CORE"


class LabTestType(str, Enum):
    MOISTURE_CONTENT = "MOISTURE_CONTENT"
    ATTERBERG = "ATTERBERG"
    SIEVE_ANALYSIS = "SIEVE_ANALYSIS"
    UNCONFINED_COMPRESSION = "UNCONFINED_COMPRESSION"
    DIRECT_SHEAR = "DIRECT_SHEAR"
    CONSOLIDATION = "CONSOLIDATION"
    PROCTOR = "PROCTOR"


class LabOrderPriority(str, Enum):
    STANDARD = "STANDARD"
    RUSH = "RUSH"


class LabTestOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    AUTHORIZED = "AUTHORIZED"
    IN_TEST = "IN_TEST"
    RESULT_SUBMITTED = "RESULT_SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class AnalysisMethod(str, Enum):
    ALLOWABLE_STRESS = "ALLOWABLE_STRESS"
    LRFD = "LRFD"


class AnalysisStatus(str, Enum):
    PRELIMINARY = "PRELIMINARY"
    VERIFIED = "VERIFIED"
    SUPERSEDED = "SUPERSEDED"


class DataStatus(str, Enum):
    CURRENT = "CURRENT"
    STALE = "STALE"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    TECH_REVIEW = "TECH_REVIEW"
    PE_REVIEW = "PE_REVIEW"
    ISSUED = "ISSUED"
    SUPERSEDED = "SUPERSEDED"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PERFORMED = "PERFORMED"
    FINDINGS_FILED = "FINDINGS_FILED"
    CLOSED = "CLOSED"


class VisitFindings(str, Enum):
    CONSISTENT = "CONSISTENT"
    MARGINAL = "MARGINAL"
    DIFFERING = "DIFFERING"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUBSTANTIATED = "SUBSTANTIATED"
    REBUTTED = "REBUTTED"
    SETTLED = "SETTLED"


class AuthorizationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REVOKED = "REVOKED"
    EXHAUSTED = "EXHAUSTED"


class Client(TypedDict, total=False):
    id: str
    name: str
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict, total=False):
    id: str
    client_id: str
    name: str
    site_address: str
    target_report_date: str
    base_fee_cents: int
    additional_auth_cap_cents: int
    assumed_gwt_depth_ft: float
    status: str
    posture: str
    additional_committed_cents: int
    claims_exposure_cents: int
    testing_invoice_cents: int
    total_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class BoringPlan(TypedDict, total=False):
    id: str
    project_id: str
    revision_no: int
    status: str
    planned_boring_count: int
    planned_total_footage_ft: float
    supersedes_plan_id: Optional[str]
    mobilization_charged: bool
    created_at: str
    updated_at: str
    version: int


class Subcontractor(TypedDict, total=False):
    id: str
    name: str
    license_no: str
    day_rate_cents: int
    max_concurrent_rigs: int
    standing: str
    committed_rig_hours: float
    created_at: str
    updated_at: str
    version: int


class RigAssignment(TypedDict, total=False):
    id: str
    boring_id: str
    subcontractor_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class UtilityClearance(TypedDict, total=False):
    id: str
    boring_id: str
    ticket_number: str
    issued_on: str
    valid_days: int
    expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Boring(TypedDict, total=False):
    id: str
    boring_plan_id: str
    offset_of_boring_id: Optional[str]
    boring_no: str
    planned_depth_ft: float
    access_difficult: bool
    status: str
    actual_depth_ft: Optional[float]
    rock_depth_ft: Optional[float]
    groundwater_depth_ft: Optional[float]
    avg_n60: Optional[float]
    refusal_depth_ft: Optional[float]
    drilling_cost_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Sample(TypedDict, total=False):
    id: str
    boring_id: str
    depth_top_ft: float
    depth_bottom_ft: float
    sampler_type: str
    recovery_pct: float
    custody_status: str
    uscs_class: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LabTestOrder(TypedDict, total=False):
    id: str
    project_id: str
    sample_id: str
    test_type: str
    priority: str
    fee_cents: int
    status: str
    rerun_count: int
    created_at: str
    updated_at: str
    version: int


class LabTestResult(TypedDict, total=False):
    id: str
    lab_test_order_id: str
    submitted_by_user_id: str
    percent_passing_200: Optional[float]
    liquid_limit: Optional[float]
    plasticity_index: Optional[float]
    qu_psf: Optional[float]
    moisture_content_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class FoundationAnalysis(TypedDict, total=False):
    id: str
    project_id: str
    method: str
    fs_required: float
    footing_width_ft: float
    applied_bearing_psf: float
    bearing_capacity_provisional_psf: Optional[float]
    bearing_capacity_final_psf: Optional[float]
    settlement_est_in: Optional[float]
    deep_foundation_required: Optional[bool]
    data_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Report(TypedDict, total=False):
    id: str
    project_id: str
    revision_no: int
    prepared_by_user_id: str
    sealed_by_pe_user_id: Optional[str]
    sealed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ObservationVisit(TypedDict, total=False):
    id: str
    project_id: str
    visit_date: str
    findings: Optional[str]
    observed_bearing_psf: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class ChangedConditionClaim(TypedDict, total=False):
    id: str
    project_id: str
    observation_visit_id: Optional[str]
    claimed_amount_cents: int
    basis_text: str
    baseline_bearing_psf: Optional[float]
    quantum_report_baseline_cents: Optional[int]
    quantum_site_observed_cents: Optional[int]
    awarded_amount_cents: Optional[int]
    appeal_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExplorationAuthorization(TypedDict, total=False):
    id: str
    project_id: str
    authorized_amount_cents: int
    extra_boring_count: int
    consumed_boring_count: int
    status: str
    created_at: str
    updated_at: str
    version: int
