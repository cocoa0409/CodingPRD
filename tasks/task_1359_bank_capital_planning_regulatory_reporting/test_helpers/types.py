"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §2.7, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


# ─── Enums ─────────────────────────────────────────────

class UserRole(str, Enum):
    SYSTEM_OPERATOR = "SystemOperator"
    CAPITAL_ANALYST = "CapitalAnalyst"
    REGULATOR_REVIEWER = "RegulatorReviewer"
    BOARD_APPROVER = "BoardApprover"
    EXTERNAL_AUDITOR = "ExternalAuditor"


class RwaMethodology(str, Enum):
    STANDARDIZED = "STANDARDIZED"
    ADVANCED = "ADVANCED"


class PcaBucket(str, Enum):
    WELL_CAPITALIZED = "WELL_CAPITALIZED"
    ADEQUATELY_CAPITALIZED = "ADEQUATELY_CAPITALIZED"
    UNDERCAPITALIZED = "UNDERCAPITALIZED"
    SIGNIFICANTLY_UNDERCAPITALIZED = "SIGNIFICANTLY_UNDERCAPITALIZED"
    CRITICALLY_UNDERCAPITALIZED = "CRITICALLY_UNDERCAPITALIZED"


class SupervisoryStatus(str, Enum):
    NORMAL = "NORMAL"
    UNDER_LETTER = "UNDER_LETTER"
    UNDER_MOU = "UNDER_MOU"


class ReportingPeriodStatus(str, Enum):
    OPEN = "OPEN"
    FILING_DUE = "FILING_DUE"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    AMENDMENT_OPEN = "AMENDMENT_OPEN"
    RE_SUBMITTED = "RE_SUBMITTED"
    RE_ACCEPTED = "RE_ACCEPTED"
    CLOSED = "CLOSED"


class PeriodQuarter(str, Enum):
    Q1 = "Q1"
    Q2 = "Q2"
    Q3 = "Q3"
    Q4 = "Q4"


class InstrumentClass(str, Enum):
    CET1 = "CET1"
    AT1 = "AT1"
    T2 = "T2"


class InstrumentSubtype(str, Enum):
    COMMON_STOCK = "COMMON_STOCK"
    PREFERRED = "PREFERRED"
    TRUST_PREFERRED = "TRUST_PREFERRED"
    SUBORDINATED_DEBT = "SUBORDINATED_DEBT"
    OTHER = "OTHER"


class InstrumentStatus(str, Enum):
    OUTSTANDING = "OUTSTANDING"
    CALLED = "CALLED"
    MATURED = "MATURED"
    REDEEMED = "REDEEMED"


class ExposureClass(str, Enum):
    SOVEREIGN = "SOVEREIGN"
    CORPORATE = "CORPORATE"
    RETAIL_MORTGAGE = "RETAIL_MORTGAGE"
    RETAIL_OTHER = "RETAIL_OTHER"
    CRE = "CRE"
    HVCRE = "HVCRE"
    EQUITY = "EQUITY"
    SECURITIZATION = "SECURITIZATION"
    OPERATIONAL_RISK = "OPERATIONAL_RISK"
    MARKET_RISK = "MARKET_RISK"


class ObligorGrade(str, Enum):
    INVESTMENT_GRADE = "INVESTMENT_GRADE"
    NON_INVESTMENT_GRADE = "NON_INVESTMENT_GRADE"
    DEFAULT = "DEFAULT"


class CallReportStatus(str, Enum):
    DRAFT = "DRAFT"
    PREPARED = "PREPARED"
    EDITS_OUTSTANDING = "EDITS_OUTSTANDING"
    VALIDATED = "VALIDATED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    AMENDED_SUPERSEDED = "AMENDED_SUPERSEDED"


class EditSeverity(str, Enum):
    FATAL = "FATAL"
    QUALITY = "QUALITY"
    INFORMATIONAL = "INFORMATIONAL"


class EditExceptionStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    EXPLAINED = "EXPLAINED"


class CapitalPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    BOARD_REVIEW = "BOARD_REVIEW"
    SUBMITTED = "SUBMITTED"
    SUPERVISORY_REVIEW = "SUPERVISORY_REVIEW"
    APPROVED = "APPROVED"
    OBJECTED = "OBJECTED"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"


class StressScenarioStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class DistributionKind(str, Enum):
    DIVIDEND = "DIVIDEND"
    BUYBACK = "BUYBACK"


class DistributionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED_NOT_EXECUTED = "APPROVED_NOT_EXECUTED"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class SubDebtStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    PRICED = "PRICED"
    SETTLED = "SETTLED"
    WITHDRAWN = "WITHDRAWN"


class PcaMetric(str, Enum):
    CET1 = "CET1"
    TIER1 = "TIER1"
    TOTAL = "TOTAL"
    LEVERAGE = "LEVERAGE"


class IcaapStatus(str, Enum):
    DRAFT = "DRAFT"
    REVIEW = "REVIEW"
    ATTESTED = "ATTESTED"
    FILED = "FILED"
    SUPERSEDED = "SUPERSEDED"


ICAAP_REQUIRED_SECTIONS = [
    "GOVERNANCE",
    "RISK_APPETITE",
    "CAPITAL_ADEQUACY",
    "STRESS_TESTING",
    "DISTRIBUTION_POLICY",
]


# ─── Entity TypedDicts ─────────────────────────────────
# All entities except PCAThresholdEvent carry the common set
# (id, created_at, updated_at, version) per PRD §2.4.

class Bank(TypedDict, total=False):
    id: str
    legal_name: str
    charter_id: str
    rwa_methodology: str
    is_advanced_approaches_bank: bool
    pca_bucket: str
    pca_bucket_as_of_period_id: Optional[str]
    mdba_cents: int
    pending_distribution_cents: int
    stressed_capital_buffer_bps: Optional[int]
    supervisory_status: str
    created_at: str
    updated_at: str
    version: int


class ReportingPeriod(TypedDict, total=False):
    id: str
    bank_id: str
    period_end_date: str
    period_year: int
    period_quarter: str
    filing_due_at: str
    late_filing: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CapitalInstrument(TypedDict, total=False):
    id: str
    bank_id: str
    instrument_class: str
    instrument_subtype: str
    outstanding_amount_cents: int
    issuance_date: str
    maturity_date: Optional[str]
    contractual_rate_bps: int
    regulatory_capital_cents: int
    t2_haircut_pct: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RiskExposure(TypedDict, total=False):
    id: str
    bank_id: str
    reporting_period_id: str
    exposure_class: str
    exposure_at_default_cents: int
    risk_weight_bps: int
    obligor_grade: str
    collateral_haircut_bps: int
    rwa_cents_standardized: int
    rwa_cents_advanced: int
    created_at: str
    updated_at: str
    version: int


class CapitalPlan(TypedDict, total=False):
    id: str
    bank_id: str
    plan_year: int
    baseline_period_id: str
    baseline_cet1_cents: int
    baseline_t1_cents: int
    baseline_total_capital_cents: int
    baseline_rwa_cents: int
    projected_cet1_bps_9q: Optional[int]
    stressed_min_cet1_bps_9q: Optional[int]
    proposed_distributions_cents: int
    stress_scenario_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class StressScenario(TypedDict, total=False):
    id: str
    bank_id: str
    scenario_code: str
    gdp_shock_bps: int
    unemployment_peak_bps: int
    hpi_shock_bps: int
    cre_price_shock_bps: int
    market_shock_bps: int
    projected_pre_tax_loss_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CallReport(TypedDict, total=False):
    id: str
    reporting_period_id: str
    bank_id: str
    amendment_sequence: int
    supersedes_call_report_id: Optional[str]
    cet1_cents: int
    tier1_cents: int
    total_capital_cents: int
    rwa_cents: int
    rwa_standardized_cents: int
    rwa_advanced_cents: int
    cet1_ratio_bps: Optional[int]
    tier1_ratio_bps: Optional[int]
    total_ratio_bps: Optional[int]
    leverage_ratio_bps: Optional[int]
    total_exposure_cents: int
    edit_failures_open_count: int
    edit_failures_total_count: int
    submitted_at: Optional[str]
    accepted_at: Optional[str]
    prepared_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EditException(TypedDict, total=False):
    id: str
    call_report_id: str
    edit_code: str
    severity: str
    description: str
    resolution_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CapitalDistributionRequest(TypedDict, total=False):
    id: str
    bank_id: str
    capital_plan_id: str
    reporting_period_id: str
    distribution_kind: str
    distribution_amount_cents: int
    proposed_payment_date: str
    capacity_reserved_cents: int
    executed_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SubordinatedDebtIssuance(TypedDict, total=False):
    id: str
    bank_id: str
    proposed_amount_cents: int
    proposed_rate_bps: int
    maturity_years: int
    target_settlement_date: str
    t2_capacity_headroom_cents: int
    capital_instrument_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PCAThresholdEvent(TypedDict, total=False):
    # Immutable audit record: id + created_at only, no updated_at/version (PRD §2.4)
    id: str
    bank_id: str
    call_report_id: str
    metric: str
    ratio_bps_observed: int
    bucket_before: str
    bucket_after: str
    breached: bool
    created_at: str


class ICAAPDocument(TypedDict, total=False):
    id: str
    bank_id: str
    document_year: int
    governing_capital_plan_id: str
    sections: List[Any]
    board_attested_by_user_id: Optional[str]
    prepared_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
