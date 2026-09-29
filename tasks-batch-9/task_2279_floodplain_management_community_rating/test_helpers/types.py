"""Domain types for the Floodplain Management & Community Rating API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    STATE_NFIP_COORDINATOR = "StateNfipCoordinator"
    FLOODPLAIN_ADMINISTRATOR = "FloodplainAdministrator"
    PROPERTY_OWNER = "PropertyOwner"
    APPEALS_BOARD_MEMBER = "AppealsBoardMember"


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------

class CompliancePosture(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    ON_PROBATION = "ON_PROBATION"
    SUSPENDED = "SUSPENDED"


class FloodZone(str, Enum):
    A = "A"
    AE = "AE"
    AO = "AO"
    VE = "VE"
    X = "X"


class FirmPanelStatus(str, Enum):
    PENDING_REVISION = "PENDING_REVISION"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"


class RepetitiveLossStatus(str, Enum):
    NONE = "NONE"
    REPETITIVE_LOSS = "REPETITIVE_LOSS"
    SEVERE_REPETITIVE_LOSS = "SEVERE_REPETITIVE_LOSS"


class StructureUse(str, Enum):
    RESIDENTIAL = "RESIDENTIAL"
    NON_RESIDENTIAL = "NON_RESIDENTIAL"
    ACCESSORY = "ACCESSORY"


class ComplianceStatus(str, Enum):
    PRE_FIRM_EXISTING = "PRE_FIRM_EXISTING"
    PENDING_CERTIFICATE = "PENDING_CERTIFICATE"
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"


class SubstantialStatus(str, Enum):
    NONE = "NONE"
    SUBSTANTIAL_IMPROVEMENT = "SUBSTANTIAL_IMPROVEMENT"
    SUBSTANTIAL_DAMAGE = "SUBSTANTIAL_DAMAGE"


class ProjectType(str, Enum):
    NEW_CONSTRUCTION = "NEW_CONSTRUCTION"
    IMPROVEMENT = "IMPROVEMENT"
    REPAIR = "REPAIR"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    APPROVED = "APPROVED"
    ISSUED = "ISSUED"
    CLOSED_COMPLIANT = "CLOSED_COMPLIANT"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class PermitDecision(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_REVISION = "REQUEST_REVISION"
    DENY = "DENY"


class CertificateType(str, Enum):
    CONSTRUCTION_DRAWINGS = "CONSTRUCTION_DRAWINGS"
    BUILDING_UNDER_CONSTRUCTION = "BUILDING_UNDER_CONSTRUCTION"
    FINISHED_CONSTRUCTION = "FINISHED_CONSTRUCTION"


class Datum(str, Enum):
    NAVD88 = "NAVD88"
    NGVD29 = "NGVD29"


class CertificateStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    DEFICIENT = "DEFICIENT"
    SUPERSEDED = "SUPERSEDED"


class CertificateDecision(str, Enum):
    ACCEPT = "ACCEPT"
    DEFICIENT = "DEFICIENT"


class RecordType(str, Enum):
    IMPROVEMENT = "IMPROVEMENT"
    DAMAGE = "DAMAGE"
    REVERSAL = "REVERSAL"


class RecordSource(str, Enum):
    PERMIT_CLOSEOUT = "PERMIT_CLOSEOUT"
    DISASTER_INSPECTION = "DISASTER_INSPECTION"
    ADMIN_ADJUSTMENT = "ADMIN_ADJUSTMENT"
    REVERSAL_ADJUSTMENT = "REVERSAL_ADJUSTMENT"


class DeterminationMethod(str, Enum):
    SINGLE_EVENT = "SINGLE_EVENT"
    CUMULATIVE = "CUMULATIVE"


class DeterminationTriggerSource(str, Enum):
    ADMIN = "ADMIN"
    PERMIT_REVIEW = "PERMIT_REVIEW"
    DISASTER_INSPECTION = "DISASTER_INSPECTION"


class DeterminationType(str, Enum):
    SUBSTANTIAL_IMPROVEMENT = "SUBSTANTIAL_IMPROVEMENT"
    SUBSTANTIAL_DAMAGE = "SUBSTANTIAL_DAMAGE"


class DeterminationOutcome(str, Enum):
    SUBSTANTIAL = "SUBSTANTIAL"
    NOT_SUBSTANTIAL = "NOT_SUBSTANTIAL"


class DeterminationCaseStatus(str, Enum):
    OPEN = "OPEN"
    DETERMINED = "DETERMINED"
    APPEALED = "APPEALED"
    APPEAL_SUSTAINED = "APPEAL_SUSTAINED"
    APPEAL_DENIED = "APPEAL_DENIED"
    WITHDRAWN = "WITHDRAWN"


class AppealDecision(str, Enum):
    SUSTAIN = "SUSTAIN"
    DENY = "DENY"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ASSESSED = "ASSESSED"
    FINALIZED = "FINALIZED"


class ViolationType(str, Enum):
    NO_PERMIT = "NO_PERMIT"
    ELEVATION_DEFICIENT = "ELEVATION_DEFICIENT"
    MISSING_CERTIFICATE = "MISSING_CERTIFICATE"
    UNPERMITTED_FILL = "UNPERMITTED_FILL"


class Severity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class ViolationStatus(str, Enum):
    OPEN = "OPEN"
    ORDER_ISSUED = "ORDER_ISSUED"
    ESCALATED = "ESCALATED"
    REMEDIATED = "REMEDIATED"
    CLOSED_UNRESOLVED = "CLOSED_UNRESOLVED"


class ViolationResolution(str, Enum):
    REMEDIATED = "REMEDIATED"
    CLOSED_UNRESOLVED = "CLOSED_UNRESOLVED"


class OrderStatus(str, Enum):
    ISSUED = "ISSUED"
    EXTENDED = "EXTENDED"
    SATISFIED = "SATISFIED"
    DEFAULTED = "DEFAULTED"


class OrderResolution(str, Enum):
    SATISFIED = "SATISFIED"
    DEFAULTED = "DEFAULTED"


class LossAreaStatus(str, Enum):
    DRAFT = "DRAFT"
    DESIGNATED = "DESIGNATED"


class AnalysisStatus(str, Enum):
    PENDING_ANALYSIS = "PENDING_ANALYSIS"
    ANALYZED = "ANALYZED"
    STALE = "STALE"


class OutreachStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    INSUFFICIENT = "INSUFFICIENT"


class ActivityCode(str, Enum):
    A430_FREEBOARD = "A430_FREEBOARD"
    A430_CUMULATIVE_SI = "A430_CUMULATIVE_SI"
    A420_OPEN_SPACE = "A420_OPEN_SPACE"
    A510_HIGHER_STD_ENFORCEMENT = "A510_HIGHER_STD_ENFORCEMENT"
    A330_OUTREACH = "A330_OUTREACH"


class DocumentationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class StandardDecision(str, Enum):
    VERIFY = "VERIFY"
    REJECT = "REJECT"


class CrsCycleStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    UNDER_VERIFICATION = "UNDER_VERIFICATION"
    CERTIFIED = "CERTIFIED"
    LAPSED = "LAPSED"
    RETROGRADED = "RETROGRADED"


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------

class Community(TypedDict):
    id: str
    name: str
    state_code: str
    cid_number: str
    freeboard_ft: float
    cumulative_period_years: int
    standards_adopted_at: str
    sanction_risk_points: int
    compliance_posture: str
    crs_credit_points_claimed: int
    crs_credit_points_verified: int
    crs_class: int
    created_at: str
    updated_at: str
    version: int


class FirmPanel(TypedDict):
    id: str
    community_id: str
    panel_number: str
    suffix: str
    flood_zone: str
    base_flood_elevation_ft: Optional[float]
    effective_date: str
    status: str
    supersedes_panel_id: Optional[str]
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    community_id: str
    firm_panel_id: str
    parcel_id: str
    mapped_area_code: str
    owner_name: str
    owner_email: str
    repetitive_loss_area_id: Optional[str]
    qualifying_claim_count: int
    max_window_claim_count: int
    cumulative_claim_paid_usd: float
    repetitive_loss_status: str
    created_at: str
    updated_at: str
    version: int


class Structure(TypedDict):
    id: str
    property_id: str
    structure_use: str
    pre_firm: bool
    construction_year: int
    market_value_usd: float
    highest_adjacent_grade_ft: float
    lowest_floor_elevation_ft: Optional[float]
    compliance_status: str
    substantial_status: str
    anchor_record_id: Optional[str]
    cumulative_counted_cost_usd: float
    cumulative_improvement_pct: float
    single_event_improvement_pct: float
    created_at: str
    updated_at: str
    version: int


class DevelopmentPermit(TypedDict):
    id: str
    property_id: str
    structure_id: str
    project_type: str
    declared_project_cost_usd: float
    proposed_lowest_floor_elevation_ft: float
    floodproofing_requested: bool
    determined_zone: Optional[str]
    determined_bfe_ft: Optional[float]
    freeboard_applied_ft: Optional[float]
    required_lowest_floor_elevation_ft: Optional[float]
    si_determination_case_id: Optional[str]
    status: str
    revision_round: int
    issued_at: Optional[str]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ElevationCertificate(TypedDict):
    id: str
    permit_id: str
    structure_id: str
    certificate_type: str
    surveyor_license_no: Optional[str]
    datum: str
    measured_lowest_floor_ft: float
    measured_bfe_ft: float
    normalized_lowest_floor_ft: float
    freeboard_margin_ft: float
    status: str
    deficiency_codes: List[str]
    accepted_at: Optional[str]
    retention_review_due_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ImprovementRecord(TypedDict):
    """Append-only ledger row: carries id and created_at only, with no
    updated_at and no version field at all."""
    id: str
    structure_id: str
    record_type: str
    source: str
    permit_id: Optional[str]
    inspection_id: Optional[str]
    reverses_record_id: Optional[str]
    event_date: str
    cost_usd: float
    market_value_at_event_usd: float
    claim_paid_amount_usd: float
    is_code_compliance_only: bool
    counted_in_cumulative: bool
    reversed: bool
    created_at: str


class DeterminationCase(TypedDict):
    id: str
    structure_id: str
    anchor_record_id: Optional[str]
    method: str
    trigger_source: str
    determination_type: str
    computed_ratio_pct: Optional[float]
    threshold_pct: float
    outcome: Optional[str]
    status: str
    determined_by_user_id: Optional[str]
    determined_at: Optional[str]
    appeal_deadline_at: Optional[str]
    appealed_at: Optional[str]
    appeal_decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PostDisasterInspection(TypedDict):
    id: str
    structure_id: str
    declaration_code: str
    disaster_event_date: str
    deadline_at: str
    status: str
    damage_cost_usd: Optional[float]
    claim_paid_amount_usd: Optional[float]
    market_value_at_inspection_usd: Optional[float]
    damage_ratio_pct: Optional[float]
    assessed_at: Optional[str]
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict):
    id: str
    property_id: str
    structure_id: Optional[str]
    permit_id: Optional[str]
    violation_type: str
    severity: str
    status: str
    sanction_points_contributed: int
    opened_at: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemediationOrder(TypedDict):
    id: str
    violation_id: str
    required_action: str
    deadline_at: str
    extension_count: int
    status: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RepetitiveLossArea(TypedDict):
    id: str
    community_id: str
    area_code: str
    boundary_description: str
    status: str
    analysis_status: str
    analyzed_at: Optional[str]
    property_count: int
    rl_property_count: int
    outreach_status: str
    outreach_cycle_year: Optional[int]
    outreach_crs_cycle_id: Optional[str]
    target_property_count: int
    delivered_count: int
    coverage_pct: float
    created_at: str
    updated_at: str
    version: int


class HigherStandard(TypedDict):
    id: str
    community_id: str
    activity_code: str
    documentation_cycle_year: int
    claimed_points: int
    max_points_allowed: int
    verified_points: int
    documentation_status: str
    submitted_at: Optional[str]
    verified_at: Optional[str]
    doc_expires_at: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CrsCycle(TypedDict):
    id: str
    community_id: str
    cycle_year: int
    cycle_start_date: str
    cycle_end_date: str
    due_at: str
    status: str
    verification_visit_required: bool
    verification_visit_completed_at: Optional[str]
    total_claimed_points: int
    total_verified_points: int
    provisional_class: Optional[int]
    resulting_class: Optional[int]
    prior_class: Optional[int]
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
