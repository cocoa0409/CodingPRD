"""Domain types for the Directors and Officers Liability API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them.  Litigation events are the single entity that is write-once at
creation: they carry only ``id`` and ``created_at`` and therefore have neither
``updated_at`` nor ``version``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Role ────────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    UNDERWRITER = "Underwriter"
    RISK_MANAGER = "RiskManager"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# ─── Enumerations declared by the PRD ────────────────────────────────────────

class SectorCode(str, Enum):
    TECH = "TECH"
    BIOTECH = "BIOTECH"
    FINANCIAL = "FINANCIAL"
    ENERGY = "ENERGY"
    INDUSTRIAL = "INDUSTRIAL"
    CONSUMER = "CONSUMER"


class ExchangeListing(str, Enum):
    LISTED = "LISTED"
    PRIVATE = "PRIVATE"
    NONE = "NONE"


class ControlStatus(str, Enum):
    INDEPENDENT = "INDEPENDENT"
    CHANGE_OF_CONTROL_ANNOUNCED = "CHANGE_OF_CONTROL_ANNOUNCED"
    ACQUIRED = "ACQUIRED"


class CapacityPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    EXHAUSTED = "EXHAUSTED"


class CaseType(str, Enum):
    SECURITIES_CLASS_ACTION = "SECURITIES_CLASS_ACTION"
    DERIVATIVE = "DERIVATIVE"
    REGULATORY_ENFORCEMENT = "REGULATORY_ENFORCEMENT"
    MERGER_OBJECTION = "MERGER_OBJECTION"
    EMPLOYMENT_PRACTICES = "EMPLOYMENT_PRACTICES"
    FIDUCIARY = "FIDUCIARY"


class LitigationOutcome(str, Enum):
    DISMISSED = "DISMISSED"
    SETTLED = "SETTLED"
    JUDGMENT = "JUDGMENT"
    PENDING = "PENDING"


class SubmissionStatus(str, Enum):
    DRAFT = "DRAFT"
    SCORED = "SCORED"
    QUOTED = "QUOTED"
    BOUND = "BOUND"
    EXPIRED = "EXPIRED"


class ScoreVariant(str, Enum):
    INDICATIVE = "INDICATIVE"
    UNDERWRITTEN = "UNDERWRITTEN"


class RiskBand(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    ELEVATED = "ELEVATED"
    SEVERE = "SEVERE"


class QuoteStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"
    LAPSED = "LAPSED"


class ExclusionType(str, Enum):
    CONDUCT = "CONDUCT"
    PRIOR_ACTS = "PRIOR_ACTS"
    INSURED_VS_INSURED = "INSURED_VS_INSURED"
    BODILY_INJURY = "BODILY_INJURY"
    REGULATORY = "REGULATORY"


class WordingVariant(str, Enum):
    BROAD = "BROAD"
    FINAL_ADJUDICATION = "FINAL_ADJUDICATION"
    NON_APPEALABLE_ADJUDICATION = "NON_APPEALABLE_ADJUDICATION"
    DERIVATIVE_CARVEBACK = "DERIVATIVE_CARVEBACK"
    BANKRUPTCY_CARVEBACK = "BANKRUPTCY_CARVEBACK"
    RETRO_DATE_FULL_PRIOR_ACTS = "RETRO_DATE_FULL_PRIOR_ACTS"
    NONE = "NONE"


class ExclusionTermStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    AGREED = "AGREED"
    REJECTED = "REJECTED"
    IMPASSE = "IMPASSE"


class TermResolution(str, Enum):
    AGREE = "AGREE"
    REJECT = "REJECT"


class CoverageStatus(str, Enum):
    INCEPTED = "INCEPTED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    RUNOFF = "RUNOFF"


class PremiumStatus(str, Enum):
    INVOICED = "INVOICED"
    PAID = "PAID"
    DELINQUENT = "DELINQUENT"


class TowerPosture(str, Enum):
    INCOMPLETE = "INCOMPLETE"
    CONTIGUOUS = "CONTIGUOUS"
    SEALED = "SEALED"
    ERODED = "ERODED"
    RELEASED = "RELEASED"


class CoveragePartName(str, Enum):
    SIDE_A = "SIDE_A"
    SIDE_B = "SIDE_B"
    SIDE_C = "SIDE_C"


class CoveragePartStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    RELEASED = "RELEASED"


class LayerFormType(str, Enum):
    FOLLOWING_FORM = "FOLLOWING_FORM"
    DIFFERENCE_IN_CONDITIONS = "DIFFERENCE_IN_CONDITIONS"


class LayerStatus(str, Enum):
    ATTACHED = "ATTACHED"
    EXHAUSTED = "EXHAUSTED"
    RELEASED = "RELEASED"


class CancelledReason(str, Enum):
    INSURED_REQUEST = "INSURED_REQUEST"
    NON_PAYMENT = "NON_PAYMENT"
    MATERIAL_MISREPRESENTATION = "MATERIAL_MISREPRESENTATION"


class RunoffEndorsementStatus(str, Enum):
    ENDORSED = "ENDORSED"
    EXPIRED = "EXPIRED"


class ClaimType(str, Enum):
    SECURITIES_CLASS_ACTION = "SECURITIES_CLASS_ACTION"
    DERIVATIVE = "DERIVATIVE"
    REGULATORY_ENFORCEMENT = "REGULATORY_ENFORCEMENT"
    EMPLOYMENT_PRACTICES = "EMPLOYMENT_PRACTICES"
    INSURED_VS_INSURED = "INSURED_VS_INSURED"
    FIDUCIARY = "FIDUCIARY"


class ClaimantCapacity(str, Enum):
    THIRD_PARTY = "THIRD_PARTY"
    SHAREHOLDER_DERIVATIVE = "SHAREHOLDER_DERIVATIVE"
    FORMER_OFFICER = "FORMER_OFFICER"
    BANKRUPTCY_TRUSTEE = "BANKRUPTCY_TRUSTEE"
    COMPANY = "COMPANY"


class ClaimStatus(str, Enum):
    NOTICED = "NOTICED"
    COVERAGE_ACCEPTED = "COVERAGE_ACCEPTED"
    DEFENSE_ADVANCING = "DEFENSE_ADVANCING"
    SETTLEMENT_PENDING = "SETTLEMENT_PENDING"
    SETTLED = "SETTLED"
    DENIED = "DENIED"


class CoverageDecision(str, Enum):
    ACCEPT_WITH_ROR = "ACCEPT_WITH_ROR"
    DENY = "DENY"


class AllocationMethod(str, Enum):
    RELATIVE_EXPOSURE = "RELATIVE_EXPOSURE"
    LARGER_SETTLEMENT = "LARGER_SETTLEMENT"


class DenialReason(str, Enum):
    CONDUCT_EXCLUSION = "CONDUCT_EXCLUSION"
    PRIOR_ACTS = "PRIOR_ACTS"
    INSURED_VS_INSURED = "INSURED_VS_INSURED"
    LATE_NOTICE = "LATE_NOTICE"
    MISREPRESENTATION = "MISREPRESENTATION"


class CircumstanceReportStatus(str, Enum):
    REPORTED = "REPORTED"
    MATURED = "MATURED"
    LAPSED = "LAPSED"


class DefenseInvoiceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ADVANCED = "ADVANCED"
    CLAWED_BACK = "CLAWED_BACK"
    VOIDED = "VOIDED"


class SettlementProposalStatus(str, Enum):
    RECOMMENDED = "RECOMMENDED"
    CONSENTED = "CONSENTED"
    REFUSED = "REFUSED"
    FUNDED = "FUNDED"
    HAMMER_APPLIED = "HAMMER_APPLIED"
    SUPERSEDED = "SUPERSEDED"


class InsuredResponse(str, Enum):
    CONSENT = "CONSENT"
    REFUSE = "REFUSE"


# ─── Entities carrying id + created_at + updated_at + version ────────────────

class Insured(TypedDict):
    id: str
    legal_name: str
    sector_code: str
    exchange_listing: str
    market_cap_usd: float
    fiscal_year_end: str
    entity_capacity_cap_usd: float
    control_status: str
    change_of_control_date: Optional[str]
    aggregate_bound_side_c_usd: float
    available_side_c_capacity_usd: float
    capacity_posture: str
    open_policy_count: int
    created_at: str
    updated_at: str
    version: int


class DisclosurePackage(TypedDict):
    id: str
    insured_id: str
    fiscal_year: int
    filed_date: str
    restatement_flag: bool
    material_weakness_count: int
    going_concern_flag: bool
    negative_operating_cash_flow_flag: bool
    debt_to_equity: float
    independent_director_ratio: float
    dual_class_shares_flag: bool
    staggered_board_flag: bool
    combined_ceo_chair_flag: bool
    auditor_change_flag: bool
    financial_subscore: float
    governance_subscore: float
    created_at: str
    updated_at: str
    version: int


class Submission(TypedDict):
    id: str
    insured_id: str
    requested_limit_usd: float
    requested_retention_usd: float
    requested_side_c_sublimit_usd: float
    requested_program_target_limit_usd: float
    requested_period_start: str
    requested_period_end: str
    retroactive_date: str
    erp_days: int
    status: str
    risk_score: Optional[float]
    risk_band: Optional[str]
    score_variant: Optional[str]
    litigation_units: Optional[float]
    disclosure_packages_considered: Optional[int]
    scored_at: Optional[str]
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    submission_id: str
    offered_limit_usd: float
    offered_retention_usd: float
    offered_side_c_sublimit_usd: float
    quote_valid_until: str
    risk_band_at_quote: str
    net_premium_usd: float
    gross_premium_usd: float
    broker_commission_usd: float
    premium_tax_usd: float
    total_payable_usd: float
    status: str
    issued_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class ExclusionTerm(TypedDict):
    id: str
    quote_id: str
    exclusion_type: str
    wording_variant: str
    premium_impact_pct: float
    status: str
    round_count: int
    proposed_by_role: str
    last_actor_role: str
    agreed_variant: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict):
    id: str
    policy_number: str
    submission_id: str
    insured_id: str
    quote_id: str
    period_start: str
    period_end: str
    retroactive_date: str
    erp_days: int
    shared_aggregate_limit_usd: float
    retention_usd: float
    program_target_limit_usd: float
    gross_premium_usd: float
    premium_due_date: str
    coverage_status: str
    premium_status: str
    total_eroded_usd: float
    aggregate_remaining_usd: float
    placed_limit_usd: float
    tower_posture: str
    tower_sealed: bool
    open_claim_count: int
    return_premium_usd: float
    runoff_premium_usd: float
    runoff_start_date: Optional[str]
    runoff_end_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CoveragePart(TypedDict):
    id: str
    policy_id: str
    part: str
    limit_usd: float
    retention_usd: float
    eroded_usd: float
    remaining_limit_usd: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Layer(TypedDict):
    id: str
    policy_id: str
    carrier_name: str
    attachment_point_usd: float
    limit_usd: float
    participation_pct: float
    form_type: str
    underlying_layer_id: Optional[str]
    dic_deviation_notes: Optional[str]
    is_primary: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RunoffEndorsement(TypedDict):
    id: str
    policy_id: str
    tail_years: int
    change_of_control_date: str
    runoff_start_date: str
    runoff_end_date: str
    tail_factor_applied: float
    severity_load_applied: float
    unexpired_premium_credit_usd: float
    runoff_premium_usd: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CircumstanceReport(TypedDict):
    id: str
    policy_id: str
    description: str
    discovered_date: str
    potential_claimants: str
    estimated_exposure_usd: float
    notice_date: str
    reporting_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    policy_id: str
    circumstance_report_id: Optional[str]
    claim_type: str
    claimant_name: str
    claimant_capacity: str
    wrongful_act_date: str
    alleged_damages_usd: float
    notice_date: str
    status: str
    allocation_method: Optional[str]
    denial_reason: Optional[str]
    decided_by_user_id: Optional[str]
    retention_applied_usd: float
    retention_remaining_usd: float
    advanced_defense_usd: float
    indemnity_paid_usd: float
    insurer_share_usd: float
    insured_retained_usd: float
    unfunded_excess_usd: float
    hammer_applied: bool
    created_at: str
    updated_at: str
    version: int


class DefenseInvoice(TypedDict):
    id: str
    claim_id: str
    law_firm_name: str
    invoice_reference: str
    billed_amount_usd: float
    covered_matter_amount_usd: float
    uncovered_matter_amount_usd: float
    mixed_matter_amount_usd: float
    insured_person_defendant_count: int
    entity_defendant_count: int
    allocation_method_applied: Optional[str]
    covered_allocated_usd: float
    retention_applied_usd: float
    advanced_usd: float
    unfunded_excess_usd: float
    status: str
    created_at: str
    updated_at: str
    version: int


class SettlementProposal(TypedDict):
    id: str
    claim_id: str
    recommended_amount_usd: float
    recommended_by_user_id: str
    insured_response: Optional[str]
    refusal_reason: Optional[str]
    response_date: Optional[str]
    hammer_pct_applied: Optional[float]
    insurer_indemnity_cap_usd: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Write-once entity: only id + created_at ─────────────────────────────────

class LitigationEvent(TypedDict):
    """A litigation event is write-once at creation: it carries only ``id`` and
    ``created_at``.  It has neither ``updated_at`` nor ``version``."""
    id: str
    insured_id: str
    case_type: str
    filed_date: str
    resolved_date: Optional[str]
    indemnity_paid_usd: float
    outcome: Optional[str]
    weight_units: float
    created_at: str


__all__ = [
    "UserRole", "SectorCode", "ExchangeListing", "ControlStatus", "CapacityPosture",
    "CaseType", "LitigationOutcome", "SubmissionStatus", "ScoreVariant", "RiskBand",
    "QuoteStatus", "ExclusionType", "WordingVariant", "ExclusionTermStatus",
    "TermResolution", "CoverageStatus", "PremiumStatus", "TowerPosture",
    "CoveragePartName", "CoveragePartStatus", "LayerFormType", "LayerStatus",
    "CancelledReason", "RunoffEndorsementStatus", "ClaimType", "ClaimantCapacity",
    "ClaimStatus", "CoverageDecision", "AllocationMethod", "DenialReason",
    "CircumstanceReportStatus", "DefenseInvoiceStatus", "SettlementProposalStatus",
    "InsuredResponse",
    "Insured", "DisclosurePackage", "Submission", "Quote", "ExclusionTerm", "Policy",
    "CoveragePart", "Layer", "RunoffEndorsement", "CircumstanceReport", "Claim",
    "DefenseInvoice", "SettlementProposal", "LitigationEvent",
    "List",
]
