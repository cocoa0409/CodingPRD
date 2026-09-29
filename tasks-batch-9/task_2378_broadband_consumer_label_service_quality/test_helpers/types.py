"""Domain types for the Broadband Consumer Label Compliance API.

Entity TypedDicts, state/status enums and the role enum, all named exactly as
the PRD names them.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    NETWORK_ENGINEER = "NetworkEngineer"
    LOCALIZATION_SPECIALIST = "LocalizationSpecialist"
    COMPLAINT_ANALYST = "ComplaintAnalyst"
    REGULATORY_LIAISON = "RegulatoryLiaison"
    RETAIL_AGENT = "RetailAgent"
    SUBSCRIBER = "Subscriber"


# ---------------------------------------------------------------------------
# Enumerated attribute values
# ---------------------------------------------------------------------------


class Technology(str, Enum):
    FIBER = "FIBER"
    CABLE = "CABLE"
    DSL = "DSL"
    FIXED_WIRELESS = "FIXED_WIRELESS"
    SATELLITE = "SATELLITE"


class EtfProrationPolicy(str, Enum):
    FULL = "FULL"
    PRORATED_MONTHLY = "PRORATED_MONTHLY"
    NONE = "NONE"


class LabelPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class FeeLabelCategory(str, Enum):
    MONTHLY_RECURRING = "MONTHLY_RECURRING"
    ONE_TIME = "ONE_TIME"
    EARLY_TERMINATION = "EARLY_TERMINATION"
    DATA_OVERAGE = "DATA_OVERAGE"
    GOVERNMENT_TAX = "GOVERNMENT_TAX"


class FeeBasis(str, Enum):
    FIXED = "FIXED"
    PCT_OF_MONTHLY_CHARGE = "PCT_OF_MONTHLY_CHARGE"


class FeeAppliesDuring(str, Enum):
    ALWAYS = "ALWAYS"
    INTRO_ONLY = "INTRO_ONLY"
    POST_PROMO_ONLY = "POST_PROMO_ONLY"


class ItemizationPhase(str, Enum):
    INTRO = "INTRO"
    POST_PROMO = "POST_PROMO"
    ONE_TIME = "ONE_TIME"


class MethodologyDocumentStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class TestRunStatus(str, Enum):
    __test__ = False  # a domain enum, never a pytest collection target

    INCLUDED = "INCLUDED"
    INVALIDATED = "INVALIDATED"


class MetricVariant(str, Enum):
    PEAK_HOUR_MEDIAN = "PEAK_HOUR_MEDIAN"
    ALL_HOUR_P20 = "ALL_HOUR_P20"


class AttestationStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class PublicationState(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"
    WITHDRAWN = "WITHDRAWN"


class SubstantiationStatus(str, Enum):
    PENDING_EVIDENCE = "PENDING_EVIDENCE"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"


class AccessibilityConformance(str, Enum):
    NONE = "NONE"
    WCAG_AA = "WCAG_AA"


class TranslationStatus(str, Enum):
    DRAFT = "DRAFT"
    VERIFIED = "VERIFIED"


class AccessibilityNeed(str, Enum):
    NONE = "NONE"
    SCREEN_READER = "SCREEN_READER"
    LARGE_PRINT = "LARGE_PRINT"


class SubscriptionState(str, Enum):
    ACTIVE = "ACTIVE"
    PENDING_CHANGE = "PENDING_CHANGE"


class PricingPhase(str, Enum):
    INTRO = "INTRO"
    POST_PROMO = "POST_PROMO"


class DisclosureChannel(str, Enum):
    POINT_OF_SALE = "POINT_OF_SALE"
    ACCOUNT_PORTAL = "ACCOUNT_PORTAL"


class AccessibleFormat(str, Enum):
    STANDARD_WEB = "STANDARD_WEB"
    SCREEN_READER = "SCREEN_READER"
    LARGE_PRINT = "LARGE_PRINT"


class AllegationType(str, Enum):
    SPEED_SHORTFALL = "SPEED_SHORTFALL"
    LATENCY_SHORTFALL = "LATENCY_SHORTFALL"
    RELIABILITY_OUTAGE = "RELIABILITY_OUTAGE"
    FEE_MISMATCH = "FEE_MISMATCH"


class ComplaintState(str, Enum):
    INTAKE = "INTAKE"
    TRIAGED = "TRIAGED"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    INFO_REQUESTED = "INFO_REQUESTED"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"
    WITHDRAWN = "WITHDRAWN"


class ComplaintSeverity(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class CreditBasis(str, Enum):
    PRORATA_DAYS = "PRORATA_DAYS"
    FLAT_SEVERITY_TIER = "FLAT_SEVERITY_TIER"


class ComplaintResolution(str, Enum):
    NONE = "NONE"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"
    WITHDRAWN = "WITHDRAWN"


class RemediationCreditStatus(str, Enum):
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class RegulatorInquiryState(str, Enum):
    RECEIVED = "RECEIVED"
    EVIDENCE_ASSEMBLY = "EVIDENCE_ASSEMBLY"
    RESPONSE_COMPLETE = "RESPONSE_COMPLETE"
    CLOSED = "CLOSED"


class FilingType(str, Enum):
    TECHNICAL_PACKET = "TECHNICAL_PACKET"
    RESOLUTION_REPORT = "RESOLUTION_REPORT"


class NoticeType(str, Enum):
    PLAN_CHANGE = "PLAN_CHANGE"
    PRICE_INCREASE = "PRICE_INCREASE"


class NoticeState(str, Enum):
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    EFFECTED = "EFFECTED"


# Terminal / grouping helpers used by assertions and tests.
COMPLAINT_TERMINAL_STATES = (
    ComplaintState.UPHELD.value,
    ComplaintState.WITHDRAWN.value,
)
COMPLAINT_FILING_ACCEPTED_STATES = (
    ComplaintState.UPHELD.value,
    ComplaintState.DISMISSED.value,
    ComplaintState.WITHDRAWN.value,
)
COMPLAINT_NON_TERMINAL_STATES = (
    ComplaintState.INTAKE.value,
    ComplaintState.TRIAGED.value,
    ComplaintState.UNDER_INVESTIGATION.value,
    ComplaintState.INFO_REQUESTED.value,
)


# ---------------------------------------------------------------------------
# Entity shapes
#
# Every resource carries a UUID `id` and a `created_at`. All resources except a
# LabelDisclosure additionally carry `updated_at` and `version` (PRD §2.5);
# LabelDisclosure is an immutable audit event and carries neither.
# ---------------------------------------------------------------------------


class ServicePlan(TypedDict):
    id: str
    plan_code: str
    display_name: str
    technology: str
    advertised_download_mbps: float
    advertised_upload_mbps: float
    monthly_price_cents: int
    intro_price_cents: Optional[int]
    intro_term_months: int
    data_allowance_gb: Optional[int]
    overage_rate_cents_per_gb: int
    early_termination_fee_cents: int
    etf_proration_policy: str
    discount_program_eligible: bool
    required_locales: List[str]
    label_posture: str
    evidence_sample_total: int
    upheld_complaint_count: int
    price_disclosure_drift: bool
    active_label_version_id: Optional[str]
    last_price_change_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeeLineItem(TypedDict):
    id: str
    plan_id: str
    fee_code: str
    description: str
    label_category: str
    basis: str
    amount_cents: Optional[int]
    rate_pct: Optional[float]
    applies_during: str
    is_regulatory_recovery: bool
    created_at: str
    updated_at: str
    version: int


class MethodologyDocument(TypedDict):
    id: str
    doc_code: str
    version_label: str
    methodology_url: str
    peak_hours_start_utc_hour: int
    peak_hours_end_utc_hour: int
    min_samples_required: int
    max_run_duration_days: int
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MeasurementProbe(TypedDict):
    id: str
    probe_code: str
    market_code: str
    panel_size: int
    max_concurrent_windows: int
    created_at: str
    updated_at: str
    version: int


class TestRun(TypedDict):
    id: str
    probe_id: str
    plan_id: str
    methodology_doc_id: str
    window_start: str
    window_end: str
    samples: List[Dict[str, Any]]
    sample_count: int
    status: str
    invalidated_at: Optional[str]
    invalidation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PerformanceAttestation(TypedDict):
    id: str
    plan_id: str
    methodology_doc_id: str
    metric_variant: str
    included_run_ids: List[str]
    pooled_sample_count: int
    typical_download_mbps: float
    typical_upload_mbps: float
    typical_latency_ms: int
    download_margin_pct: float
    upload_margin_pct: float
    status: str
    certified_at: Optional[str]
    revoked_reason: Optional[str]
    methodology_snapshot: Dict[str, Any]
    created_at: str
    updated_at: str
    version: int


class LabelVersion(TypedDict):
    id: str
    plan_id: str
    version_seq: int
    publication_state: str
    substantiation_status: str
    effective_from: str
    effective_until: Optional[str]
    accessibility_conformance: str
    discount_program_applied: bool
    attestation_id: Optional[str]
    typical_download_mbps: Optional[float]
    typical_upload_mbps: Optional[float]
    typical_latency_ms: Optional[int]
    methodology_url_snapshot: Optional[str]
    fee_itemization: List[Dict[str, Any]]
    monthly_total_intro_cents: Optional[int]
    monthly_total_post_promo_cents: int
    discount_program_benefit_intro_cents: Optional[int]
    discount_program_benefit_post_promo_cents: int
    net_monthly_intro_cents: Optional[int]
    net_monthly_post_promo_cents: int
    one_time_fee_total_cents: int
    first_year_total_promo_weighted_cents: int
    first_year_total_post_promo_cents: int
    etf_disclosure_cents: int
    data_allowance_gb_snapshot: Optional[int]
    overage_rate_cents_per_gb_snapshot: int
    price_disclosure_drift: bool
    verified_locale_count: int
    created_by_user_id: str
    published_by_user_id: Optional[str]
    published_at: Optional[str]
    archived_at: Optional[str]
    withdrawn_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LabelTranslation(TypedDict):
    id: str
    label_version_id: str
    locale: str
    translated_summary: str
    machine_translated: bool
    status: str
    created_by_user_id: str
    verified_by_user_id: Optional[str]
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubscriberAccount(TypedDict):
    id: str
    account_code: str
    plan_id: str
    preferred_locale: str
    accessibility_need: str
    discount_program_enrolled: bool
    service_start_date: str
    subscription_state: str
    credit_balance_cents: int
    remediation_count: int
    audit_flag: bool
    pricing_phase: str
    last_disclosed_label_version_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LabelDisclosure(TypedDict):
    """Immutable audit event: carries only `id` and `created_at` besides its own
    fields — no `updated_at` and no `version` (PRD §2.5)."""

    id: str
    account_id: str
    label_version_id: str
    channel: str
    locale: str
    accessible_format: str
    disclosed_label_version_seq: int
    disclosed_net_monthly_cents: int
    disclosed_by_user_id: str
    created_at: str


class Complaint(TypedDict):
    id: str
    account_id: str
    disputed_label_version_id: str
    allegation_type: str
    service_observed_date: str
    affected_days: int
    measured_download_mbps: Optional[float]
    measured_upload_mbps: Optional[float]
    measured_latency_ms: Optional[int]
    narrative: str
    state: str
    triaged_at: Optional[str]
    sla_due_at: Optional[str]
    resolved_at: Optional[str]
    reopened_count: int
    investigation_cycles: int
    shortfall_ratio: Optional[float]
    severity: str
    evidence_gap: bool
    credit_basis: Optional[str]
    remediation_credit_cents: int
    resolution: str
    resolution_note: Optional[str]
    info_request_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemediationCredit(TypedDict):
    id: str
    complaint_id: str
    account_id: str
    basis: str
    amount_cents: int
    status: str
    issued_by_user_id: str
    voided_by_user_id: Optional[str]
    voided_at: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RegulatorInquiry(TypedDict):
    id: str
    complaint_id: str
    docket_number: str
    regulator_code: str
    response_due_at: str
    state: str
    technical_packet_filed_at: Optional[str]
    resolution_report_filed_at: Optional[str]
    technical_evidence_ref: Optional[str]
    resolution_report_ref: Optional[str]
    filed_late: bool
    closure_note: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PlanChangeNotice(TypedDict):
    id: str
    account_id: str
    target_plan_id: str
    notice_type: str
    effective_date: str
    reason: str
    notice_days: int
    etf_disclosed_cents: int
    disclosed_net_monthly_cents: Optional[int]
    source_plan_id: str
    state: str
    acknowledged_at: Optional[str]
    effected_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
