"""Typed shapes for the utility relocation and betterment domain.

Every field name below is taken from the PRD's entity descriptions.  The types
exist to document the response payloads the tests assert on; they are not used
for runtime validation.
"""
from typing import Any, Literal, TypedDict

# ---------------------------------------------------------------------------
# Enumerations declared by the PRD
# ---------------------------------------------------------------------------

ProjectStatus = Literal[
    "PLANNING",
    "CLEARANCE_ACTIVE",
    "LETTING_READY",
    "UNDER_CONSTRUCTION",
    "CLOSED",
]

ClearancePosture = Literal[
    "CLEARANCE_PENDING",
    "AT_RISK",
    "CLEAR",
    "FUNDING_BLOCKED",
]

UtilityType = Literal["ELECTRIC", "GAS", "WATER", "SEWER", "TELECOM", "FIBER"]

FacilityType = Literal[
    "BURIED_ELECTRIC",
    "OVERHEAD_ELECTRIC",
    "GAS_MAIN",
    "WATER_MAIN",
    "SANITARY_SEWER",
    "FIBER_CONDUIT",
]

OccupancyBasis = Literal[
    "FEE_SIMPLE",
    "PRIVATE_EASEMENT",
    "FRANCHISE",
    "PERMIT",
    "UNDOCUMENTED",
]

RecordSource = Literal["AS_BUILT", "FIELD_SURVEY", "OWNER_ATLAS", "VERBAL"]

QualityLevel = Literal["QL_A", "QL_B", "QL_C", "QL_D"]

InvestigationMethod = Literal[
    "VACUUM_TEST_HOLE",
    "GEOPHYSICAL",
    "SURFACE_MARKING",
    "RECORD_RESEARCH",
]

ConflictStatus = Literal[
    "IDENTIFIED",
    "RESOLUTION_SELECTED",
    "RESPONSIBILITY_SET",
    "RELOCATION_PLANNED",
    "RELOCATION_SCHEDULED",
    "CLEARED",
]

ResolutionType = Literal["RELOCATE", "PROTECT_IN_PLACE", "ABANDON", "NO_CONFLICT"]

DeterminationStatus = Literal[
    "DRAFT",
    "UNDER_REVIEW",
    "RETURNED_FOR_REVISION",
    "ISSUED",
    "APPEALED",
    "FINAL",
]

EvidenceVariant = Literal["RECORD_BASIS", "FIELD_BASIS"]

PlanStatus = Literal[
    "SUBMITTED",
    "UNDER_REVIEW",
    "REVISION_REQUESTED",
    "APPROVED",
    "SUPERSEDED",
]

PermitType = Literal[
    "ENCROACHMENT_PERMIT",
    "RAILROAD_CROSSING",
    "ENVIRONMENTAL_CLEARANCE",
    "EASEMENT_ACQUISITION",
]

PermitStatus = Literal["APPLIED", "GRANTED", "DENIED"]

SlotStatus = Literal["OPEN", "FULL"]

CommitmentStatus = Literal[
    "COMMITTED",
    "IN_PROGRESS",
    "COMPLETE",
    "BREACHED",
    "CANCELLED",
]

PhaseDependency = Literal["BEFORE_GRADING", "AFTER_GRADING", "BEFORE_PAVING", "ANY_PHASE"]

ExecutionStatus = Literal[
    "DRAFT",
    "PENDING_OWNER_SIGNATURE",
    "EXECUTED",
    "VOIDED",
]

SettlementStatus = Literal[
    "NOT_STARTED",
    "PENDING_FINAL_INVOICE",
    "AUDIT_IN_PROGRESS",
    "HELD",
    "SETTLED",
    "VOIDED_OUT",
]

CostBasis = Literal["ESTIMATE_BASIS", "ACTUAL_BASIS"]

DocType = Literal[
    "LABOR",
    "MATERIAL",
    "EQUIPMENT",
    "CONTRACT",
    "INDIRECT",
    "CREDIT_SALVAGE",
]

ReviewStatus = Literal["SUBMITTED", "ACCEPTED", "DISALLOWED", "HELD"]

ExclusionReason = Literal[
    "NOT_SUPPORTED",
    "SUSTAINED_AUDIT_FINDING",
    "EXCEEDS_NOT_TO_EXCEED_CAP",
]

FindingType = Literal[
    "UNSUPPORTED_COST",
    "INELIGIBLE_BETTERMENT",
    "INDIRECT_RATE_ERROR",
    "DUPLICATE_BILLING",
]

FindingStatus = Literal["OPEN", "RESOLVED"]

FindingDisposition = Literal["SUSTAINED", "WITHDRAWN"]

ClaimStatus = Literal["SUBMITTED", "UNDER_ANALYSIS", "ALLOCATED", "DENIED"]

DelayCause = Literal[
    "UTILITY_OWNER",
    "UTILITY_OWNER_PERMIT_WAIT",
    "THIRD_PARTY",
    "STATE_PERMIT_DELAY",
]

Role = Literal[
    "ProgramAdmin",
    "UtilityCoordinator",
    "RightOfWayAdjudicator",
    "AgreementOfficer",
    "ExternalAuditor",
    "ConstructionEngineer",
    "UtilityOwnerRep",
]


# ---------------------------------------------------------------------------
# Common field envelope
# ---------------------------------------------------------------------------


class CommonFields(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


class Project(CommonFields, total=False):
    name: str
    route_designation: str
    letting_date: str
    construction_start_date: str
    construction_end_date: str
    row_acquisition_year: int
    reimbursement_authority_cents: int
    contract_daily_overhead_cents: int
    status: ProjectStatus
    clearance_posture: ClearancePosture
    open_conflict_count: int
    estimated_state_liability_cents: int
    total_committed_reimbursement_cents: int
    aggregate_compensable_delay_days: int


class UtilityOwner(CommonFields, total=False):
    legal_name: str
    utility_type: UtilityType
    is_public_agency: bool
    indirect_cost_rate_pct: float
    delinquency_strikes: int
    reimbursement_hold: bool
    open_commitment_days: int
    assessed_delay_liability_cents: int


class UtilityFacility(CommonFields, total=False):
    owner_id: str
    facility_type: FacilityType
    station_begin: float
    station_end: float
    offset_ft: float
    depth_in: int
    material: str
    installed_year: int
    occupancy_basis: OccupancyBasis
    record_source: RecordSource


class SubsurfaceInvestigation(TypedDict, total=False):
    """Immutable record.  Carries only ``id`` and ``created_at``: the PRD states
    that ``updated_at`` and ``version`` are absent from it."""

    id: str
    created_at: str
    project_id: str
    facility_id: str
    quality_level: QualityLevel
    method: InvestigationMethod
    measured_depth_in: int
    station_at_investigation: float
    performed_at: str
    contradicts_record: bool


class UtilityConflict(CommonFields, total=False):
    project_id: str
    facility_id: str
    conflict_station: float
    clearance_deficiency_in: int
    depends_on_conflict_id: str | None
    status: ConflictStatus
    resolution_type: ResolutionType | None
    state_share_pct: int | None


class PriorRightsDetermination(CommonFields, total=False):
    conflict_id: str
    claimed_basis: OccupancyBasis
    narrative: str
    status: DeterminationStatus
    evidence_variant: EvidenceVariant
    provisional_state_share_pct: int
    final_state_share_pct: int | None
    appeal_round: int
    first_issued_by_user_id: str | None


class RelocationPlan(CommonFields, total=False):
    conflict_id: str
    project_id: str
    owner_id: str
    estimated_cost_cents: int
    replacement_in_kind_cost_cents: int
    proposed_capacity_ratio: float
    work_days: int
    joint_trench_requested: bool
    status: PlanStatus
    revision_round: int
    betterment_ratio: float
    betterment_amount_cents: int


class PermitRecord(CommonFields, total=False):
    conflict_id: str
    permit_type: PermitType
    status: PermitStatus
    applied_on: str
    granted_on: str | None
    expires_on: str


class JointTrenchSlot(CommonFields, total=False):
    project_id: str
    segment_code: str
    trench_open_start: str
    trench_open_end: str
    max_occupants: int
    occupant_count: int
    status: SlotStatus


class ScheduleCommitment(CommonFields, total=False):
    plan_id: str
    project_id: str
    facility_id: str
    owner_id: str
    joint_trench_slot_id: str | None
    window_start: str
    window_end: str
    committed_work_days: int
    phase_dependency: PhaseDependency
    status: CommitmentStatus
    actual_complete_at: str | None
    late_days: int


class ReimbursementAgreement(CommonFields, total=False):
    plan_id: str
    project_id: str
    owner_id: str
    not_to_exceed_cents: int
    execution_status: ExecutionStatus
    settlement_status: SettlementStatus
    cost_basis: CostBasis
    executed_by_user_id: str | None
    as_built_reference: str | None
    eligible_cost_cents: int
    indirect_cost_cents: int
    betterment_credit_cents: int
    net_allowable_cents: int
    participation_tier_pct: int
    state_share_cents: int
    owner_share_cents: int


class CostDocument(CommonFields, total=False):
    agreement_id: str
    doc_type: DocType
    amount_cents: int
    incurred_on: str
    support_reference: str
    review_status: ReviewStatus
    disallowed_amount_cents: int
    exclusion_reason: ExclusionReason | None


class AuditFinding(CommonFields, total=False):
    agreement_id: str
    finding_type: FindingType
    questioned_cost_cents: int
    narrative: str
    status: FindingStatus
    disposition: FindingDisposition | None
    auditor_user_id: str


class DelayClaim(CommonFields, total=False):
    commitment_id: str
    project_id: str
    owner_id: str
    contractor_name: str
    claimed_days: int
    claimed_amount_cents: int
    status: ClaimStatus
    delay_cause: DelayCause | None
    compensable_days: int
    daily_rate_cents: int
    allocated_to_owner_cents: int
    allocated_to_state_cents: int


class ClearanceSummary(TypedDict, total=False):
    clearance_posture: ClearancePosture
    open_conflict_count: int
    untriaged_conflict_count: int
    overdue_commitment_count: int
    at_risk_commitment_count: int
    estimated_state_liability_cents: int
    total_committed_reimbursement_cents: int
    reimbursement_authority_cents: int
    remaining_authority_cents: int


class SettlementPreview(TypedDict, total=False):
    cost_basis: CostBasis
    eligible_cost_cents: int
    indirect_cost_cents: int
    betterment_credit_cents: int
    net_allowable_cents: int
    participation_tier_pct: int
    state_share_cents: int
    owner_share_cents: int
    not_to_exceed_cents: int
    included_document_count: int
    excluded_document_count: int


World = dict[str, Any]

__all__ = [
    "ProjectStatus",
    "ClearancePosture",
    "UtilityType",
    "FacilityType",
    "OccupancyBasis",
    "RecordSource",
    "QualityLevel",
    "InvestigationMethod",
    "ConflictStatus",
    "ResolutionType",
    "DeterminationStatus",
    "EvidenceVariant",
    "PlanStatus",
    "PermitType",
    "PermitStatus",
    "SlotStatus",
    "CommitmentStatus",
    "PhaseDependency",
    "ExecutionStatus",
    "SettlementStatus",
    "CostBasis",
    "DocType",
    "ReviewStatus",
    "ExclusionReason",
    "FindingType",
    "FindingStatus",
    "FindingDisposition",
    "ClaimStatus",
    "DelayCause",
    "Role",
    "CommonFields",
    "Project",
    "UtilityOwner",
    "UtilityFacility",
    "SubsurfaceInvestigation",
    "UtilityConflict",
    "PriorRightsDetermination",
    "RelocationPlan",
    "PermitRecord",
    "JointTrenchSlot",
    "ScheduleCommitment",
    "ReimbursementAgreement",
    "CostDocument",
    "AuditFinding",
    "DelayClaim",
    "ClearanceSummary",
    "SettlementPreview",
    "World",
]
