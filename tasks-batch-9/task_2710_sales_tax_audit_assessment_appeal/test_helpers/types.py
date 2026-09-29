"""Domain types: status enums, role enum and entity TypedDicts."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    SELECTION_ANALYST = "SelectionAnalyst"
    FIELD_AUDITOR = "FieldAuditor"
    AUDIT_SUPERVISOR = "AuditSupervisor"
    TAXPAYER = "Taxpayer"
    APPEALS_OFFICER = "AppealsOfficer"
    TAX_TRIBUNAL_JUDGE = "TaxTribunalJudge"
    COLLECTIONS_AGENT = "CollectionsAgent"


class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    DELINQUENT = "DELINQUENT"
    REVOKED = "REVOKED"


class FilingFrequency(str, Enum):
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    ANNUAL = "ANNUAL"


class SourceType(str, Enum):
    FEDERAL_1099K = "FEDERAL_1099K"
    WHOLESALER_REPORT = "WHOLESALER_REPORT"
    MARKETPLACE_REPORT = "MARKETPLACE_REPORT"


class MatchStatus(str, Enum):
    MATCHED = "MATCHED"
    UNDER_REPORTED = "UNDER_REPORTED"
    OVER_REPORTED = "OVER_REPORTED"


class SelectionMode(str, Enum):
    THRESHOLD = "THRESHOLD"
    QUOTA = "QUOTA"
    HYBRID = "HYBRID"


class LeadStatus(str, Enum):
    SCORED = "SCORED"
    SELECTED = "SELECTED"
    NOT_SELECTED = "NOT_SELECTED"
    CONVERTED = "CONVERTED"
    DECLINED = "DECLINED"


class ScoreVariant(str, Enum):
    SCREENING = "SCREENING"
    FULL = "FULL"


class AuditStatus(str, Enum):
    PLANNED = "PLANNED"
    SCOPED = "SCOPED"
    FIELDWORK = "FIELDWORK"
    REVIEW_COMPLETE = "REVIEW_COMPLETE"
    ASSESSED = "ASSESSED"
    CLOSED = "CLOSED"
    ABANDONED = "ABANDONED"


class AuditType(str, Enum):
    FIELD = "FIELD"
    DESK = "DESK"
    MANAGED = "MANAGED"


class ProjectionMethod(str, Enum):
    NONE = "NONE"
    MEAN_PER_UNIT = "MEAN_PER_UNIT"
    RATIO_ESTIMATION = "RATIO_ESTIMATION"


class ProjectionStatus(str, Enum):
    NOT_RUN = "NOT_RUN"
    CURRENT = "CURRENT"
    STALE = "STALE"


class StatuteStatus(str, Enum):
    UNSET = "UNSET"
    PROTECTED = "PROTECTED"
    EXPIRING_SOON = "EXPIRING_SOON"
    EXPIRED = "EXPIRED"


class WaiverStatus(str, Enum):
    DRAFTED = "DRAFTED"
    EXECUTED = "EXECUTED"
    VOIDED = "VOIDED"


class AgreementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    AGREED = "AGREED"
    SUPERSEDED = "SUPERSEDED"


class Methodology(str, Enum):
    MEAN_PER_UNIT = "MEAN_PER_UNIT"
    RATIO_ESTIMATION = "RATIO_ESTIMATION"


class ErrorClass(str, Enum):
    PENDING = "PENDING"
    NO_ERROR = "NO_ERROR"
    UNREPORTED_TAXABLE_SALE = "UNREPORTED_TAXABLE_SALE"
    CERTIFICATE_DEFECT = "CERTIFICATE_DEFECT"
    RATE_ERROR = "RATE_ERROR"


class CertificateStatus(str, Enum):
    ON_FILE = "ON_FILE"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    CURED = "CURED"


class ExemptionType(str, Enum):
    RESALE = "RESALE"
    MANUFACTURING = "MANUFACTURING"
    AGRICULTURAL = "AGRICULTURAL"
    NONPROFIT = "NONPROFIT"
    GOVERNMENT = "GOVERNMENT"


class CertificateDetermination(str, Enum):
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class AssetClass(str, Enum):
    CONSUMABLE = "CONSUMABLE"
    CAPITAL_ASSET = "CAPITAL_ASSET"
    EXEMPT_MANUFACTURING = "EXEMPT_MANUFACTURING"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    DRAFT_STALE = "DRAFT_STALE"
    ISSUED = "ISSUED"
    FINAL = "FINAL"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"


class CollectionStatus(str, Enum):
    NOT_DUE = "NOT_DUE"
    DUE = "DUE"
    ARRANGED = "ARRANGED"
    REFERRED = "REFERRED"
    SATISFIED = "SATISFIED"


class AdjustmentKind(str, Enum):
    PAYMENT = "PAYMENT"
    PENALTY_ABATEMENT = "PENALTY_ABATEMENT"
    APPEAL_REDUCTION = "APPEAL_REDUCTION"
    ASSESSMENT_VACATED = "ASSESSMENT_VACATED"
    COLLECTION_FEE = "COLLECTION_FEE"
    OIC_WRITEOFF = "OIC_WRITEOFF"


SYSTEM_ONLY_ADJUSTMENT_KINDS = (
    AdjustmentKind.PENALTY_ABATEMENT.value,
    AdjustmentKind.APPEAL_REDUCTION.value,
    AdjustmentKind.COLLECTION_FEE.value,
    AdjustmentKind.OIC_WRITEOFF.value,
    AdjustmentKind.ASSESSMENT_VACATED.value,
)


class AdjustmentSource(str, Enum):
    MANUAL = "MANUAL"
    SYSTEM = "SYSTEM"


class AdjustmentStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class AbatementFactor(str, Enum):
    FIRST_TIME_COMPLIANT = "FIRST_TIME_COMPLIANT"
    RELIANCE_ON_WRITTEN_ADVICE = "RELIANCE_ON_WRITTEN_ADVICE"
    RECORDS_LOST_IN_DISASTER = "RECORDS_LOST_IN_DISASTER"
    SUBSTANTIAL_COOPERATION = "SUBSTANTIAL_COOPERATION"


class Forum(str, Enum):
    INFORMAL_CONFERENCE = "INFORMAL_CONFERENCE"
    ADMINISTRATIVE_APPEAL = "ADMINISTRATIVE_APPEAL"
    TAX_TRIBUNAL = "TAX_TRIBUNAL"


class ProceedingStatus(str, Enum):
    OPEN = "OPEN"
    DECIDED = "DECIDED"


class ProceedingOutcome(str, Enum):
    NONE = "NONE"
    SUSTAINED = "SUSTAINED"
    REDUCED = "REDUCED"
    REMANDED = "REMANDED"


class ArrangementType(str, Enum):
    INSTALLMENT_PLAN = "INSTALLMENT_PLAN"
    OFFER_IN_COMPROMISE = "OFFER_IN_COMPROMISE"


class ArrangementStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"
    DEFAULTED = "DEFAULTED"
    CANCELLED = "CANCELLED"


# --- Entity shapes ---------------------------------------------------------
# Thirteen of the fourteen resource families carry id, created_at, updated_at
# and version. The information return is the single exception: it is immutable
# once loaded and carries only id and created_at.


class Taxpayer(TypedDict):
    id: str
    legal_name: str
    permit_number: str
    industry_naics_code: str
    filing_frequency: str
    gross_receipts_annual_cents: int
    delinquent_period_count: int
    prior_audit_error_rate_bp: Optional[int]
    compliance_status: str
    reported_total_cents: int
    matched_total_cents: int
    open_audit_count: int
    info_variance_bp: int
    delinquency_bp: int
    magnitude_bp: int
    prior_audit_bp: int
    screening_score: int
    created_at: str
    updated_at: str
    version: int


class InformationReturn(TypedDict):
    id: str
    taxpayer_id: str
    source_type: str
    period_start: str
    period_end: str
    reported_amount_cents: int
    matched_return_amount_cents: int
    variance_cents: int
    match_status: str
    in_scoring_window: bool
    created_at: str


class IndustryProject(TypedDict):
    id: str
    project_name: str
    industry_naics_code: str
    industry_error_rate_bp: int
    selection_mode: str
    selection_threshold_score: int
    selection_quota: int
    selections_used: int
    selections_remaining: int
    scored_lead_count: int
    last_run_at: Optional[str]
    last_cutoff_score: Optional[int]
    created_at: str
    updated_at: str
    version: int


class AuditLead(TypedDict):
    id: str
    industry_project_id: str
    taxpayer_id: str
    status: str
    risk_score: int
    score_variant: str
    score_breakdown: dict
    rank_position: int
    scored_at: str
    promoted_from_scored: bool
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Audit(TypedDict):
    id: str
    taxpayer_id: str
    audit_lead_id: str
    lead_auditor_user_id: str
    status: str
    audit_type: Optional[str]
    scope_period_start: Optional[str]
    scope_period_end: Optional[str]
    base_statute_expiry_date: Optional[str]
    statute_expiry_date: Optional[str]
    statute_status: str
    waiver_days_added: int
    tolled_days: int
    agreed_agreement_id: Optional[str]
    projection_method: str
    projection_status: str
    sample_error_rate_bp: int
    examined_unit_count: int
    projected_deficiency_cents: int
    certificate_deficiency_cents: int
    use_tax_deficiency_cents: int
    fraud_indicator: bool
    reopen_count: int
    created_at: str
    updated_at: str
    version: int


class StatuteWaiver(TypedDict):
    id: str
    audit_id: str
    status: str
    covers_period_end: str
    extended_to_date: str
    signed_by_name: str
    signed_date: Optional[str]
    prior_expiry_date: Optional[str]
    days_added: int
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SamplingAgreement(TypedDict):
    id: str
    audit_id: str
    status: str
    methodology: str
    confidence_level_bp: int
    minimum_sample_size: int
    strata: List[dict]
    population_base_amount_cents: int
    population_unit_count: int
    round_number: int
    examined_unit_count: int
    supersedes_agreement_id: Optional[str]
    counter_note: Optional[str]
    requested_minimum_sample_size: Optional[int]
    agreed_by_name: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SampleUnit(TypedDict):
    id: str
    sampling_agreement_id: str
    stratum_index: int
    invoice_reference: str
    invoice_date: str
    invoice_amount_cents: int
    exempt_sale_amount_cents: int
    error_class: str
    declared_error_amount_cents: Optional[int]
    error_amount_cents: int
    redetermination_count: int
    created_at: str
    updated_at: str
    version: int


class ExemptionCertificate(TypedDict):
    id: str
    audit_id: str
    sample_unit_id: Optional[str]
    status: str
    purchaser_name: str
    purchaser_permit_number: Optional[str]
    claimed_exemption_type: str
    covered_sale_amount_cents: int
    received_before_sale: bool
    form_complete: bool
    claimed_exemption_matches_purchaser_business: bool
    good_faith_accepted: bool
    missing_certificate_tax_cents: int
    review_note: Optional[str]
    cure_count: int
    created_at: str
    updated_at: str
    version: int


class UseTaxPurchase(TypedDict):
    id: str
    audit_id: str
    vendor_name: str
    invoice_date: str
    purchase_price_cents: int
    asset_class: str
    in_state_usage_pct_bp: int
    first_use_outside_state: bool
    months_used_outside_state: int
    fair_market_value_at_entry_cents: Optional[int]
    tax_paid_other_state_cents: int
    taxable_basis_cents: int
    gross_use_tax_cents: int
    credit_applied_cents: int
    use_tax_due_cents: int
    reclassification_count: int
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict):
    id: str
    audit_id: str
    status: str
    collection_status: str
    collection_hold: bool
    supersedes_assessment_id: Optional[str]
    tax_deficiency_cents: int
    penalty_rate_bp: int
    penalty_cents: int
    interest_days: int
    interest_cents: int
    provisional_total_due_cents: int
    penalty_waived_small_balance: bool
    total_due_cents: int
    total_adjustments_cents: int
    total_abated_cents: int
    amount_paid_cents: int
    balance_due_cents: int
    notice_mailed_date: Optional[str]
    protest_deadline_date: Optional[str]
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AssessmentAdjustment(TypedDict):
    id: str
    assessment_id: str
    appeal_proceeding_id: Optional[str]
    kind: str
    source: str
    status: str
    amount_cents: int
    abatement_pct: Optional[int]
    abatement_factors: Optional[List[str]]
    posted_at: str
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AppealProceeding(TypedDict):
    id: str
    assessment_id: str
    predecessor_proceeding_id: Optional[str]
    forum: str
    status: str
    outcome: str
    protest_basis: str
    filed_date: str
    decided_date: Optional[str]
    tolled_days: int
    presiding_officer_user_id: Optional[str]
    decision_rationale: Optional[str]
    reduction_amount_cents: Optional[int]
    escalation_deadline_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PaymentArrangement(TypedDict):
    id: str
    assessment_id: str
    arrangement_type: str
    status: str
    monthly_installment_cents: Optional[int]
    term_months: Optional[int]
    offer_amount_cents: Optional[int]
    scheduled_total_cents: int
    hardship_documented: bool
    payments_made_count: int
    amount_paid_cents: int
    approved_at: Optional[str]
    default_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
