"""Domain types for the Broadband Grant Challenge API.

Entity TypedDicts, state enums and the role enum, all named exactly as the
PRD names them. Grant programs, eligible locations, challenges, subgrantees,
applications, location claims, score sheets, awards, environmental reviews,
milestones and compliance audits carry ``id``, ``created_at``, ``updated_at``
and ``version``; challenge evidence items and ledger entries are append-only
records that carry only ``id`` and ``created_at``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    ELIGIBILITY_ANALYST = "EligibilityAnalyst"
    CAPABILITY_REVIEWER = "CapabilityReviewer"
    SCORING_OFFICER = "ScoringOfficer"
    ENVIRONMENTAL_REVIEWER = "EnvironmentalReviewer"
    AUDIT_OFFICER = "AuditOfficer"
    SUBGRANTEE = "Subgrantee"
    CHALLENGER = "Challenger"
    PROVIDER = "Provider"


# --------------------------------------------------------------------------
# State / enum vocabularies
# --------------------------------------------------------------------------


class ProgramState(str, Enum):
    DRAFT = "DRAFT"
    CHALLENGE_OPEN = "CHALLENGE_OPEN"
    CHALLENGE_CLOSED = "CHALLENGE_CLOSED"
    SCORING = "SCORING"
    ALLOCATION_CLOSED = "ALLOCATION_CLOSED"


class ScoringPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class ClassificationStatus(str, Enum):
    SERVED = "SERVED"
    UNDERSERVED = "UNDERSERVED"
    UNSERVED = "UNSERVED"


class ClassificationSource(str, Enum):
    NATIONAL_MAP = "NATIONAL_MAP"
    CHALLENGE_DETERMINATION = "CHALLENGE_DETERMINATION"


class EligibilityState(str, Enum):
    MAPPED = "MAPPED"
    CHALLENGED = "CHALLENGED"
    AFFIRMED = "AFFIRMED"
    RECLASSIFIED = "RECLASSIFIED"
    AWARD_BOUND = "AWARD_BOUND"
    DEFERRED_HIGH_COST = "DEFERRED_HIGH_COST"


class ServiceState(str, Enum):
    NOT_BUILT = "NOT_BUILT"
    UNDER_CONSTRUCTION = "UNDER_CONSTRUCTION"
    SERVICE_AVAILABLE = "SERVICE_AVAILABLE"
    CERTIFIED = "CERTIFIED"
    AUDIT_FAILED = "AUDIT_FAILED"


class ReportedTechnology(str, Enum):
    FIBER = "FIBER"
    CABLE = "CABLE"
    DSL = "DSL"
    LICENSED_FIXED_WIRELESS = "LICENSED_FIXED_WIRELESS"
    UNLICENSED_FIXED_WIRELESS = "UNLICENSED_FIXED_WIRELESS"
    GEOSTATIONARY_SATELLITE = "GEOSTATIONARY_SATELLITE"
    LEO_SATELLITE = "LEO_SATELLITE"


class ChallengeState(str, Enum):
    SUBMITTED = "SUBMITTED"
    REBUTTAL_OPEN = "REBUTTAL_OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    DEFICIENT = "DEFICIENT"
    SUSTAINED = "SUSTAINED"
    REJECTED = "REJECTED"


class ChallengerType(str, Enum):
    PROVIDER = "PROVIDER"
    COMMUNITY = "COMMUNITY"
    LOCAL_GOVERNMENT = "LOCAL_GOVERNMENT"
    NONPROFIT = "NONPROFIT"


class ChallengeOutcome(str, Enum):
    SUSTAINED = "SUSTAINED"
    REJECTED = "REJECTED"
    DEFICIENT = "DEFICIENT"


class EvidenceType(str, Enum):
    SPEED_TEST = "SPEED_TEST"
    SUBSCRIBER_BILL = "SUBSCRIBER_BILL"
    SERVICE_DENIAL_LETTER = "SERVICE_DENIAL_LETTER"
    FIELD_SURVEY = "FIELD_SURVEY"
    PROVIDER_ATTESTATION = "PROVIDER_ATTESTATION"
    MAP_DATA_EXPORT = "MAP_DATA_EXPORT"
    CONSTRUCTION_PERMIT_RECORD = "CONSTRUCTION_PERMIT_RECORD"


class EvidenceState(str, Enum):
    ACCEPTED = "ACCEPTED"
    STALE_EXCLUDED = "STALE_EXCLUDED"


class SubmitterSide(str, Enum):
    CHALLENGE = "CHALLENGE"
    REBUTTAL = "REBUTTAL"


class CapabilityState(str, Enum):
    REGISTERED = "REGISTERED"
    UNDER_CAPABILITY_REVIEW = "UNDER_CAPABILITY_REVIEW"
    QUALIFIED = "QUALIFIED"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"
    SUSPENDED = "SUSPENDED"
    DISQUALIFIED = "DISQUALIFIED"


class ReviewVariant(str, Enum):
    INITIAL = "INITIAL"
    REMEDIATION = "REMEDIATION"


class ApplicationState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED_FOR_CURE = "RETURNED_FOR_CURE"
    SCORED = "SCORED"
    RESCORE_REQUIRED = "RESCORE_REQUIRED"
    SELECTED = "SELECTED"
    AWARDED = "AWARDED"
    NOT_SELECTED = "NOT_SELECTED"


class RescoreRequiredReason(str, Enum):
    CHALLENGE_RECLASSIFICATION = "CHALLENGE_RECLASSIFICATION"


class ClaimState(str, Enum):
    CLAIMED_ELIGIBLE = "CLAIMED_ELIGIBLE"
    CLAIMED_INELIGIBLE = "CLAIMED_INELIGIBLE"
    AWARD_BOUND = "AWARD_BOUND"
    EHCL_DEFERRED = "EHCL_DEFERRED"
    RELEASED = "RELEASED"


class ScoreState(str, Enum):
    FINAL = "FINAL"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"


class AwardState(str, Enum):
    OBLIGATED = "OBLIGATED"
    CONSTRUCTION_AUTHORIZED = "CONSTRUCTION_AUTHORIZED"
    IN_CONSTRUCTION = "IN_CONSTRUCTION"
    CLOSED = "CLOSED"
    TERMINATED = "TERMINATED"


class ComplianceState(str, Enum):
    COMPLIANT = "COMPLIANT"
    NONCOMPLIANT = "NONCOMPLIANT"
    CURED = "CURED"


class EhpState(str, Enum):
    SCREENING = "SCREENING"
    CATEGORICAL_EXCLUSION = "CATEGORICAL_EXCLUSION"
    EA_REQUIRED = "EA_REQUIRED"
    MITIGATION_REQUIRED = "MITIGATION_REQUIRED"
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"


class EhpPathway(str, Enum):
    CATEGORICAL_EXCLUSION = "CATEGORICAL_EXCLUSION"
    EA_REQUIRED = "EA_REQUIRED"
    MITIGATION_PLAN_ACCEPTED = "MITIGATION_PLAN_ACCEPTED"
    ADVERSE_EFFECT = "ADVERSE_EFFECT"


class MilestoneState(str, Enum):
    PLANNED = "PLANNED"
    EVIDENCE_SUBMITTED = "EVIDENCE_SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    HELD = "HELD"
    DISBURSED = "DISBURSED"
    VOIDED = "VOIDED"


class EvidenceBasis(str, Enum):
    BUILD_PROGRESS = "BUILD_PROGRESS"
    INVOICED_COST = "INVOICED_COST"


class MilestoneVerificationOutcome(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AuditState(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    REMEDIATED = "REMEDIATED"
    CLAWBACK_NOTICE_ISSUED = "CLAWBACK_NOTICE_ISSUED"
    APPEALED = "APPEALED"
    CLAWBACK_SETTLED = "CLAWBACK_SETTLED"
    CLAWBACK_WAIVED = "CLAWBACK_WAIVED"


class AuditType(str, Enum):
    SPEED_TEST = "SPEED_TEST"
    SERVICE_AVAILABILITY = "SERVICE_AVAILABILITY"
    COMBINED = "COMBINED"


class AuditResult(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class ClawbackResolution(str, Enum):
    SETTLED = "SETTLED"
    WAIVED = "WAIVED"


class LedgerEntryType(str, Enum):
    OBLIGATION = "OBLIGATION"
    DISBURSEMENT = "DISBURSEMENT"
    DEOBLIGATION = "DEOBLIGATION"
    CLAWBACK_RECOVERY = "CLAWBACK_RECOVERY"


# --------------------------------------------------------------------------
# Entities carrying id + created_at + updated_at + version
# --------------------------------------------------------------------------


class GrantProgram(TypedDict, total=False):
    id: str
    name: str
    fiscal_year: int
    total_appropriation_cents: int
    challenge_window_start: str
    challenge_window_end: str
    application_window_start: str
    application_window_end: str
    min_match_pct: float
    holdback_pct: float
    unserved_down_mbps_threshold: float
    unserved_up_mbps_threshold: float
    served_down_mbps_threshold: float
    served_up_mbps_threshold: float
    max_latency_ms: int
    ehcl_threshold_cents: int
    ehcl_waiver_enabled: bool
    program_state: str
    scoring_posture: str
    stale_score_sheet_count: int
    location_count_total: int
    uncommitted_balance_cents: int
    obligated_balance_cents: int
    disbursed_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class EligibleLocation(TypedDict, total=False):
    id: str
    program_id: str
    address_id: str
    reported_down_mbps: float
    reported_up_mbps: float
    reported_latency_ms: int
    reported_technology: str
    reporting_provider_user_id: str
    classification_status: str
    classification_source: str
    eligibility_state: str
    service_state: str
    challenge_count: int
    awarded_award_id: Optional[str]
    certified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Challenge(TypedDict, total=False):
    id: str
    program_id: str
    location_id: str
    challenger_type: str
    asserted_classification: str
    rationale: str
    challenge_state: str
    submitter_user_id: str
    triaged_by_user_id: Optional[str]
    determined_by_user_id: Optional[str]
    outcome: Optional[str]
    determination_note: Optional[str]
    rebuttal_round: int
    rebuttal_deadline: Optional[str]
    resubmission_count: int
    required_sufficiency_threshold: float
    evidence_sufficiency_score: float
    rebuttal_strength_score: float
    distinct_evidence_type_count: int
    evidence_count: int
    created_at: str
    updated_at: str
    version: int


class Subgrantee(TypedDict, total=False):
    id: str
    program_id: str
    legal_name: str
    ein: str
    net_assets_cents: int
    requested_amount_cents: int
    key_personnel_count: int
    has_prior_federal_award: bool
    capability_state: str
    review_variant: Optional[str]
    capability_reviewer_user_id: Optional[str]
    technical_raw_score: Optional[float]
    technical_component: Optional[float]
    financial_component: Optional[float]
    managerial_component: Optional[float]
    capability_index: Optional[float]
    audited_net_assets_cents: Optional[int]
    withdrawn_personnel_count: int
    remediation_count: int
    open_noncompliance_count: int
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    program_id: str
    subgrantee_id: str
    match_offer_pct: float
    committed_down_mbps: float
    committed_up_mbps: float
    committed_latency_ms: int
    low_cost_plan_price_cents: int
    participates_in_state_affordability_program: bool
    has_dbe_plan: bool
    has_union_agreement: bool
    local_hire_pct: float
    proposed_construction_start: str
    proposed_construction_end: str
    application_state: str
    claim_count: int
    confirmed_location_count: int
    total_project_cost_cents: int
    eligible_project_cost_cents: int
    preliminary_cost_per_location_cents: Optional[int]
    final_cost_per_location_cents: Optional[int]
    current_total_score: Optional[float]
    rescore_required_reason: Optional[str]
    returned_for_cure_count: int
    created_at: str
    updated_at: str
    version: int


class LocationClaim(TypedDict, total=False):
    id: str
    application_id: str
    location_id: str
    claimed_cost_cents: int
    claim_state: str
    is_ehcl: Optional[bool]
    match_share_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ScoreSheet(TypedDict, total=False):
    id: str
    application_id: str
    scored_by_user_id: str
    score_state: str
    cost_points: float
    speed_points: float
    affordability_points: float
    workforce_points: float
    capability_multiplier: float
    total_score: float
    basis_final_cost_per_location_cents: int
    basis_confirmed_location_count: int
    created_at: str
    updated_at: str
    version: int


class Award(TypedDict, total=False):
    id: str
    application_id: str
    award_state: str
    compliance_state: str
    total_eligible_cost_cents: int
    final_per_location_cost_cents: int
    match_requirement_cents: int
    obligation_amount_cents: int
    holdback_cap_cents: int
    confirmed_location_count: int
    ehcl_deferred_count: int
    disbursed_to_date_cents: int
    certified_location_count: int
    failed_location_count: int
    last_verifier_user_id: Optional[str]
    terminated_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EnvironmentalReview(TypedDict, total=False):
    id: str
    award_id: str
    tribal_consultation_required: bool
    shpo_consultation_required: bool
    ehp_state: str
    pathway: Optional[str]
    mitigation_summary: Optional[str]
    cleared_by_user_id: Optional[str]
    cleared_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Milestone(TypedDict, total=False):
    id: str
    award_id: str
    sequence_no: int
    description: str
    evidence_basis: str
    planned_location_ids: List[str]
    is_final: bool
    milestone_state: str
    built_location_ids: Optional[List[str]]
    invoiced_cost_cents: Optional[int]
    verified_location_count: Optional[int]
    payable_amount_cents: Optional[int]
    verified_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    resubmission_count: int
    created_at: str
    updated_at: str
    version: int


class ComplianceAudit(TypedDict, total=False):
    id: str
    award_id: str
    audit_type: str
    window_start: str
    window_end: str
    audit_state: str
    auditor_user_id: str
    tested_location_ids: Optional[List[str]]
    tested_location_count: Optional[int]
    failed_location_ids: Optional[List[str]]
    failed_location_count: Optional[int]
    noncompliant_share: Optional[float]
    penalty_multiplier: Optional[float]
    recovery_amount_cents: Optional[int]
    notice_issued_by_user_id: Optional[str]
    settled_amount_cents: Optional[int]
    appeal_count: int
    appeal_basis: Optional[str]
    remediation_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Append-only records: id + created_at only, never updated_at, never version
# --------------------------------------------------------------------------


class ChallengeEvidence(TypedDict, total=False):
    id: str
    challenge_id: str
    evidence_type: str
    collected_at: str
    description: str
    submitter_user_id: str
    submitter_side: str
    base_weight: float
    recency_multiplier: float
    weighted_value: float
    evidence_state: str
    created_at: str


class LedgerEntry(TypedDict, total=False):
    id: str
    award_id: str
    entry_type: str
    amount_cents: int
    source_reference: str
    memo: str
    program_uncommitted_after_cents: int
    created_at: str
