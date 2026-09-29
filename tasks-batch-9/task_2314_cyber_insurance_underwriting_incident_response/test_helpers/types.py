"""Domain types for the Cyber Insurance Underwriting & Incident Response API.

Entity TypedDicts, status enums and the role enum, as described in PRD §2.4 and §3.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1) — spelling is exact.
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    UNDERWRITER = "Underwriter"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    PORTFOLIO_ACTUARY = "PortfolioActuary"
    PANEL_ADMIN = "PanelAdmin"
    INSURED = "Insured"


# --------------------------------------------------------------------------
# Vocabularies
# --------------------------------------------------------------------------
class ControlKey(str, Enum):
    MFA_PRIVILEGED = "MFA_PRIVILEGED"
    OFFLINE_BACKUPS = "OFFLINE_BACKUPS"
    EDR_COVERAGE = "EDR_COVERAGE"
    EMAIL_FILTERING = "EMAIL_FILTERING"
    INCIDENT_RESPONSE_PLAN = "INCIDENT_RESPONSE_PLAN"


class MaturityLevel(str, Enum):
    NONE = "NONE"
    PARTIAL = "PARTIAL"
    FULL = "FULL"


class IndustryCode(str, Enum):
    HEALTHCARE = "HEALTHCARE"
    FINANCIAL = "FINANCIAL"
    RETAIL = "RETAIL"
    MANUFACTURING = "MANUFACTURING"
    PUBLIC_SECTOR = "PUBLIC_SECTOR"
    TECHNOLOGY = "TECHNOLOGY"


class DependencyKey(str, Enum):
    CSP_ALPHA = "CSP_ALPHA"
    CSP_BETA = "CSP_BETA"
    MSSP_DELTA = "MSSP_DELTA"
    NONE = "NONE"


class DependentBiDefinition(str, Enum):
    NAMED_ONLY = "NAMED_ONLY"
    NAMED_PLUS_SUPPLY_CHAIN = "NAMED_PLUS_SUPPLY_CHAIN"
    BROAD_SYSTEM_FAILURE = "BROAD_SYSTEM_FAILURE"


class SectionKey(str, Enum):
    FIRST_PARTY_RESPONSE = "FIRST_PARTY_RESPONSE"
    BUSINESS_INTERRUPTION = "BUSINESS_INTERRUPTION"
    DEPENDENT_BI = "DEPENDENT_BI"
    THIRD_PARTY_LIABILITY = "THIRD_PARTY_LIABILITY"
    CYBER_EXTORTION = "CYBER_EXTORTION"


class VendorType(str, Enum):
    FORENSICS = "FORENSICS"
    LEGAL_COUNSEL = "LEGAL_COUNSEL"
    NOTIFICATION = "NOTIFICATION"
    PR_CRISIS = "PR_CRISIS"
    RANSOM_NEGOTIATION = "RANSOM_NEGOTIATION"


class IncidentType(str, Enum):
    RANSOMWARE = "RANSOMWARE"
    SYSTEM_FAILURE = "SYSTEM_FAILURE"
    DEPENDENT_OUTAGE = "DEPENDENT_OUTAGE"
    BEC = "BEC"
    DATA_THEFT = "DATA_THEFT"


class BiBaselineMethod(str, Enum):
    TRAILING_12M = "TRAILING_12M"
    SAME_PERIOD_PRIOR_YEAR = "SAME_PERIOD_PRIOR_YEAR"


class LossSource(str, Enum):
    PROOF_OF_LOSS = "PROOF_OF_LOSS"
    VENDOR_ENGAGEMENT = "VENDOR_ENGAGEMENT"


class SelectionMode(str, Enum):
    DIRECTED = "DIRECTED"
    PANEL_SELECTED = "PANEL_SELECTED"


class FindingSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ScanOutcome(str, Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# --------------------------------------------------------------------------
# State machines (PRD §3)
# --------------------------------------------------------------------------
class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDERWRITING = "UNDERWRITING"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"
    QUOTED = "QUOTED"
    BOUND = "BOUND"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class ExternalScanStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class PolicyLifecycleStatus(str, Enum):
    INFORCE = "INFORCE"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    NON_RENEWED = "NON_RENEWED"


class PolicyLimitStatus(str, Enum):
    INTACT = "INTACT"
    PARTIALLY_ERODED = "PARTIALLY_ERODED"
    EXHAUSTED = "EXHAUSTED"


class WarrantyStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    LAPSED = "LAPSED"


class PanelVendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class IncidentClaimStatus(str, Enum):
    NOTIFIED = "NOTIFIED"
    TRIAGE = "TRIAGE"
    COVERAGE_CONFIRMED = "COVERAGE_CONFIRMED"
    RESPONSE_ACTIVE = "RESPONSE_ACTIVE"
    PROOF_REVIEW = "PROOF_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED_FOR_PAYMENT = "APPROVED_FOR_PAYMENT"
    SETTLED = "SETTLED"
    DENIED = "DENIED"
    CLOSED_NO_COVERAGE = "CLOSED_NO_COVERAGE"


class VendorEngagementStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class ProofOfLossStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


class ClaimPaymentStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class RenewalAssessmentStatus(str, Enum):
    CONDITIONS_ISSUED = "CONDITIONS_ISSUED"
    REMEDIATION_SUBMITTED = "REMEDIATION_SUBMITTED"
    CONDITIONS_MET = "CONDITIONS_MET"
    RENEWAL_QUOTED = "RENEWAL_QUOTED"
    NON_RENEWED = "NON_RENEWED"


class SystemicScenarioStatus(str, Enum):
    DRAFT = "DRAFT"
    MODELED = "MODELED"


# --------------------------------------------------------------------------
# Entities
# --------------------------------------------------------------------------
# The underwriting control catalog is immutable (PRD §2.4): a control
# requirement row carries only `id` and `created_at`; `updated_at` and
# `version` are absent entirely.
class ControlRequirement(TypedDict):
    id: str
    control_key: str
    is_mandatory: bool
    min_level_required: str
    weight: int
    remediation_grace_days: int
    created_at: str


class InsuredAccount(TypedDict):
    id: str
    legal_name: str
    industry_code: str
    annual_revenue_usd: float
    record_count: int
    primary_dependency_key: str
    open_remediation_count: int
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    insured_account_id: str
    requested_aggregate_limit_usd: float
    requested_retention_usd: float
    dependent_bi_definition: str
    status: str
    attested_control_score: Optional[float]
    verified_control_score: Optional[float]
    mandatory_gap_count: int
    mandatory_gap_control_keys: List[str]
    indicative_premium_usd: Optional[float]
    premium_usd: Optional[float]
    quoted_by_user_id: Optional[str]
    quote_expires_at: Optional[str]
    declined_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ControlAttestation(TypedDict):
    id: str
    application_id: str
    control_key: str
    attested_level: str
    verified_level: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExternalScan(TypedDict):
    id: str
    application_id: str
    scan_vendor_name: str
    status: str
    scan_score: Optional[float]
    findings: List[dict]
    critical_finding_count: int
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict):
    id: str
    application_id: str
    insured_account_id: str
    aggregate_limit_usd: float
    aggregate_limit_remaining_usd: float
    retention_usd: float
    premium_usd: float
    period_start: str
    period_end: str
    bi_baseline_method: str
    dependent_bi_definition: str
    named_dependency_keys: List[str]
    warranty_control_keys: List[str]
    lapsed_warranty_control_keys: List[str]
    warranty_status: str
    lifecycle_status: str
    limit_status: str
    aggregation_flagged: bool
    cancelled_at: Optional[str]
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CoverageSection(TypedDict):
    id: str
    policy_id: str
    section_key: str
    sublimit_usd: float
    sublimit_remaining_usd: float
    waiting_period_hours: Optional[float]
    coinsurance_pct: float
    erosion_priority: int
    created_at: str
    updated_at: str
    version: int


class PanelVendor(TypedDict):
    id: str
    vendor_name: str
    vendor_type: str
    pre_approved_hourly_rate_usd: float
    per_record_notification_rate_usd: float
    specialty_sectors: List[str]
    tier: int
    capacity_concurrent_engagements: int
    status: str
    active_engagement_count: int
    created_at: str
    updated_at: str
    version: int


class IncidentClaim(TypedDict):
    id: str
    policy_id: str
    systemic_event_scenario_id: Optional[str]
    incident_type: str
    incident_discovered_at: str
    notified_at: str
    outage_start_at: Optional[str]
    outage_end_at: Optional[str]
    dependency_key: str
    affected_record_count: int
    status: str
    covered_section_keys: List[str]
    reservation_of_rights: bool
    reserved_amount_usd: float
    retention_absorbed_usd: float
    paid_total_usd: float
    unallocated_loss_usd: float
    proof_review_round: int
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VendorEngagement(TypedDict):
    id: str
    incident_claim_id: str
    panel_vendor_id: str
    vendor_type: str
    selection_mode: str
    deployment_start_at: str
    deployment_end_at: str
    authorized_hours_cap: float
    approved_rate_usd: float
    approved_per_record_rate_usd: float
    authorized_by_user_id: str
    incurred_hours: float
    records_notified: int
    incurred_amount_usd: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ProofOfLoss(TypedDict):
    id: str
    incident_claim_id: str
    claimed_bi_loss_usd: float
    trailing_12m_revenue_usd: float
    prior_year_same_period_revenue_usd: float
    prior_year_same_period_hours: float
    gross_profit_margin_pct: float
    extra_expense_usd: float
    mitigation_savings_usd: float
    status: str
    baseline_method_applied: Optional[str]
    outage_hours: Optional[float]
    compensable_hours: Optional[float]
    bi_component_usd: Optional[float]
    mitigation_component_usd: Optional[float]
    extra_expense_component_usd: Optional[float]
    assessed_indemnity_usd: Optional[float]
    info_request_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClaimPayment(TypedDict):
    id: str
    incident_claim_id: str
    coverage_section_id: str
    loss_source: str
    gross_amount_usd: float
    retention_applied_usd: float
    coinsurance_deduction_usd: float
    net_paid_usd: float
    payment_status: str
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RenewalAssessment(TypedDict):
    id: str
    policy_id: str
    required_control_keys: List[str]
    remediation_due_at: Optional[str]
    submitted_control_keys: List[str]
    verified_control_keys: List[str]
    verification_round: int
    status: str
    loss_ratio: Optional[float]
    premium_adjustment_pct: Optional[float]
    renewal_premium_usd: Optional[float]
    non_renewal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SystemicEventScenario(TypedDict):
    id: str
    dependency_key: str
    assumed_outage_hours: float
    footprint_pct: float
    portfolio_capacity_usd: float
    qualifying_definitions: List[str]
    status: str
    modeled_policy_count: int
    modeled_gross_exposure_usd: Optional[float]
    capacity_breached: bool
    modeled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
