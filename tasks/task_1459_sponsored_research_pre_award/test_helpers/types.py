"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------

class FundingOpportunityStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    INTAKE_CLOSED = "INTAKE_CLOSED"


class ProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    BUDGET_LOCKED = "BUDGET_LOCKED"
    ROUTED = "ROUTED"
    RETURNED_FOR_REVISION = "RETURNED_FOR_REVISION"
    INSTITUTIONALLY_APPROVED = "INSTITUTIONALLY_APPROVED"
    SUBMITTED = "SUBMITTED"
    JIT_REQUESTED = "JIT_REQUESTED"
    NEGOTIATING = "NEGOTIATING"
    AWARDED = "AWARDED"
    SETUP_COMPLETE = "SETUP_COMPLETE"
    WITHDRAWN = "WITHDRAWN"
    DECLINED = "DECLINED"


class BudgetSnapshotStatus(str, Enum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"


class FaRateAgreementStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class CostShareStatus(str, Enum):
    PLEDGED = "PLEDGED"
    APPROVED = "APPROVED"
    RELEASED = "RELEASED"
    WITHDRAWN = "WITHDRAWN"


class ReviewStatus(str, Enum):
    PENDING = "PENDING"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    EXPIRED = "EXPIRED"
    DISAPPROVED = "DISAPPROVED"
    CANCELLED = "CANCELLED"


class SubCommitmentStatus(str, Enum):
    DRAFT = "DRAFT"
    VERIFIED = "VERIFIED"
    STALE = "STALE"
    VOIDED = "VOIDED"


class OfferStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    VOIDED = "VOIDED"


class HandoffStatus(str, Enum):
    DRAFT = "DRAFT"
    READY = "READY"
    BLOCKED = "BLOCKED"
    HANDED_OFF = "HANDED_OFF"


class SubmissionPackageStatus(str, Enum):
    ACCEPTED_BY_PORTAL = "ACCEPTED_BY_PORTAL"


class ActivityCode(str, Enum):
    RESEARCH_ON_CAMPUS = "RESEARCH_ON_CAMPUS"
    RESEARCH_OFF_CAMPUS = "RESEARCH_OFF_CAMPUS"
    INSTRUCTION = "INSTRUCTION"
    OTHER_SPONSORED = "OTHER_SPONSORED"


class RateType(str, Enum):
    ON_CAMPUS_RESEARCH = "ON_CAMPUS_RESEARCH"
    OFF_CAMPUS_RESEARCH = "OFF_CAMPUS_RESEARCH"
    INSTRUCTION = "INSTRUCTION"
    OTHER_SPONSORED = "OTHER_SPONSORED"


class RateSource(str, Enum):
    FINAL_RATE = "FINAL_RATE"
    PROVISIONAL_RATE = "PROVISIONAL_RATE"


class FaBaseType(str, Enum):
    MTDC = "MTDC"
    TDC = "TDC"


class BudgetCategory(str, Enum):
    PERSONNEL = "PERSONNEL"
    EQUIPMENT = "EQUIPMENT"
    TRAVEL = "TRAVEL"
    PARTICIPANT_SUPPORT = "PARTICIPANT_SUPPORT"
    MATERIALS = "MATERIALS"
    PUBLICATION = "PUBLICATION"
    CONSULTANT = "CONSULTANT"
    SUBAWARD = "SUBAWARD"
    TUITION = "TUITION"
    OTHER_DIRECT = "OTHER_DIRECT"


class CostShareSourceType(str, Enum):
    DEPARTMENT = "DEPARTMENT"
    COLLEGE = "COLLEGE"
    CENTRAL_OFFICE = "CENTRAL_OFFICE"
    THIRD_PARTY_IN_KIND = "THIRD_PARTY_IN_KIND"


class ReviewType(str, Enum):
    IRB = "IRB"
    IACUC = "IACUC"
    EXPORT_CONTROL = "EXPORT_CONTROL"
    CONFLICT_OF_INTEREST = "CONFLICT_OF_INTEREST"


class SingleAuditStatus(str, Enum):
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"
    NOT_REQUIRED = "NOT_REQUIRED"
    MISSING = "MISSING"


class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class MonitoringLevel(str, Enum):
    STANDARD = "STANDARD"
    ENHANCED = "ENHANCED"


class OfferOrigin(str, Enum):
    SPONSOR = "SPONSOR"
    INSTITUTION = "INSTITUTION"


class CompliancePosture(str, Enum):
    CLEAR = "CLEAR"
    REVIEW_PENDING = "REVIEW_PENDING"
    BLOCKED = "BLOCKED"


class Rank(str, Enum):
    ASSISTANT = "ASSISTANT"
    ASSOCIATE = "ASSOCIATE"
    FULL = "FULL"
    RESEARCH_SCIENTIST = "RESEARCH_SCIENTIST"


class UserRole(str, Enum):
    PI = "PI"
    PRE_AWARD_ANALYST = "PreAwardAnalyst"
    DEPARTMENT_CHAIR = "DepartmentChair"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    SUBRECIPIENT_MANAGER = "SubrecipientManager"
    OSP_DIRECTOR = "OSPDirector"
    OSP_SYSTEM_ADMIN = "OSPSystemAdmin"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.5 common fields; SubmissionPackage excepted)
# ---------------------------------------------------------------------------

class FundingOpportunity(TypedDict, total=False):
    id: str
    sponsor_code: str
    title: str
    activity_codes_allowed: List[str]
    sponsor_deadline_at: str
    internal_lead_days: int
    internal_deadline_at: str
    fa_rate_cap_pct: Optional[float]
    requires_cost_share: bool
    min_cost_share_pct_of_request: float
    max_request_cents: Optional[int]
    max_proposals_per_pi: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class PrincipalInvestigator(TypedDict, total=False):
    id: str
    full_name: str
    department_code: str
    rank: str
    delinquent_report_count: int
    is_eligible: bool
    committed_effort_pct: float
    created_at: str
    updated_at: str
    version: int


class Proposal(TypedDict, total=False):
    id: str
    opportunity_id: str
    pi_id: str
    title: str
    activity_code: str
    project_start_on: str
    project_end_on: str
    pi_effort_pct: float
    fa_base_type: str
    current_snapshot_id: Optional[str]
    pinned_budget_snapshot_id: Optional[str]
    total_direct_cents: int
    total_indirect_cents: int
    total_request_cents: int
    fa_rate_pct_applied: Optional[float]
    applied_rate_source: Optional[str]
    total_approved_cost_share_cents: int
    total_effective_cost_share_cents: int
    is_cost_share_adequate: bool
    compliance_posture: str
    routed_by_user_id: Optional[str]
    budget_amended_since_approval: bool
    revision_count: int
    submitted_at: Optional[str]
    jit_due_at: Optional[str]
    awarded_total_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class BudgetLine(TypedDict, total=False):
    id: str
    proposal_id: str
    category: str
    description: str
    fiscal_year: int
    amount_cents: int
    is_cost_share: bool
    subrecipient_commitment_id: Optional[str]
    counts_toward_mtdc: bool
    created_at: str
    updated_at: str
    version: int


class PerLineIndirect(TypedDict, total=False):
    budget_line_id: str
    base_portion_cents: int
    indirect_cents: int


class BudgetSnapshot(TypedDict, total=False):
    id: str
    proposal_id: str
    snapshot_index: int
    fa_base_type: str
    rate_type: str
    selected_rate_pct: float
    applied_rate_pct: float
    rate_source: str
    mtdc_base_cents: int
    total_direct_cents: int
    total_indirect_cents: int
    total_request_cents: int
    per_line_indirect: List[PerLineIndirect]
    status: str
    created_at: str
    updated_at: str
    version: int


class FaRateAgreement(TypedDict, total=False):
    id: str
    rate_type: str
    rate_pct: float
    effective_start_on: str
    effective_end_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CostShareCommitment(TypedDict, total=False):
    id: str
    proposal_id: str
    source_type: str
    amount_cents: int
    committed_by_user_id: str
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceReview(TypedDict, total=False):
    id: str
    proposal_id: str
    review_type: str
    disclosure_complete: bool
    approved_until_at: Optional[str]
    validity_days: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class SubrecipientOrg(TypedDict, total=False):
    id: str
    legal_name: str
    uei: str
    is_foreign: bool
    single_audit_status: str
    audit_finding_count: int
    first_time_subrecipient: bool
    risk_score: int
    risk_tier: str
    created_at: str
    updated_at: str
    version: int


class SubrecipientCommitment(TypedDict, total=False):
    id: str
    proposal_id: str
    subrecipient_org_id: str
    subaward_amount_cents: int
    statement_of_work_received: bool
    budget_received: bool
    enhanced_monitoring_acknowledged: bool
    verified_risk_snapshot_score: Optional[int]
    monitoring_level: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class NegotiationOffer(TypedDict, total=False):
    id: str
    proposal_id: str
    round_index: int
    origin: str
    offered_total_cents: int
    offered_fa_rate_pct: Optional[float]
    note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only record (PRD §2.5): carries ONLY id + created_at among the
# system-managed fields — no updated_at, no version.
class SubmissionPackage(TypedDict, total=False):
    id: str
    proposal_id: str
    idempotency_key: str
    portal_confirmation_code: str
    submitted_at: str
    status: str
    created_at: str


class AwardHandoff(TypedDict, total=False):
    id: str
    proposal_id: str
    budget_verified: bool
    compliance_verified: bool
    subrecipient_verified: bool
    final_indirect_cents: Optional[int]
    final_total_cents: Optional[int]
    handoff_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
