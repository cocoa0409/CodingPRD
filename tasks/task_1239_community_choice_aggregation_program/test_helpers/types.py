"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class AuthorityStatus(str, Enum):
    FORMING = "FORMING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DISSOLVED = "DISSOLVED"


class ServiceClass(str, Enum):
    RESIDENTIAL = "RESIDENTIAL"
    SMALL_COMMERCIAL = "SMALL_COMMERCIAL"
    LARGE_COMMERCIAL = "LARGE_COMMERCIAL"
    INDUSTRIAL = "INDUSTRIAL"
    AGRICULTURAL = "AGRICULTURAL"
    STREETLIGHT = "STREETLIGHT"


class EnrollmentState(str, Enum):
    PROSPECT = "PROSPECT"
    NOTICED = "NOTICED"
    ENROLLED = "ENROLLED"
    OPTED_OUT = "OPTED_OUT"
    OPTED_BACK_TO_BUNDLED = "OPTED_BACK_TO_BUNDLED"
    CLOSED = "CLOSED"


class ProductElection(str, Enum):
    DEFAULT = "DEFAULT"
    OPT_UP_100 = "OPT_UP_100"
    OPT_DOWN_ECONOMY = "OPT_DOWN_ECONOMY"


class NoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    CLOSED = "CLOSED"
    ENROLLING = "ENROLLING"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class ElectionType(str, Enum):
    OPT_OUT = "OPT_OUT"
    OPT_BACK_TO_BUNDLED = "OPT_BACK_TO_BUNDLED"


class OptOutChannel(str, Enum):
    WEB = "WEB"
    PHONE = "PHONE"
    MAIL = "MAIL"


class ProductStatus(str, Enum):
    DRAFT = "DRAFT"
    ADOPTED = "ADOPTED"
    RETIRED = "RETIRED"


class RateScheduleStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    ADOPTED = "ADOPTED"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


class ContractType(str, Enum):
    ENERGY_BLOCK = "ENERGY_BLOCK"
    RA_CAPACITY = "RA_CAPACITY"
    REC_ONLY = "REC_ONLY"
    PPA = "PPA"


class SupplyContractStatus(str, Enum):
    NEGOTIATING = "NEGOTIATING"
    EXECUTED = "EXECUTED"
    DELIVERING = "DELIVERING"
    CLOSED = "CLOSED"
    TERMINATED = "TERMINATED"


class ForecastVariant(str, Enum):
    ADOPTED_PLAN = "ADOPTED_PLAN"
    ACTUAL_TRUED = "ACTUAL_TRUED"


class BillingExtractStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED_BY_UTILITY = "REJECTED_BY_UTILITY"
    SETTLED = "SETTLED"


class RemittanceStatus(str, Enum):
    RECEIVED = "RECEIVED"
    RECONCILED = "RECONCILED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"


class BadDebtPoolStatus(str, Enum):
    ACCRUING = "ACCRUING"
    CLOSED = "CLOSED"
    TRUED_UP = "TRUED_UP"


class FilingType(str, Enum):
    RPS_ANNUAL = "RPS_ANNUAL"
    ERRA_FORECAST = "ERRA_FORECAST"
    PSD = "PSD"


class FilingStatus(str, Enum):
    DRAFT = "DRAFT"
    PREPARED = "PREPARED"
    REVIEWED = "REVIEWED"
    FILED = "FILED"
    ACCEPTED_BY_CPUC = "ACCEPTED_BY_CPUC"
    REJECTED_BY_CPUC = "REJECTED_BY_CPUC"
    WITHDRAWN = "WITHDRAWN"


class RateSettingPolicy(str, Enum):
    COST_PLUS = "COST_PLUS"
    DISCOUNT_TO_INCUMBENT = "DISCOUNT_TO_INCUMBENT"
    VALUE_BASED = "VALUE_BASED"


class UtilityTerritoryCode(str, Enum):
    PGE = "PGE"
    SCE = "SCE"
    SDGE = "SDGE"


class UserRole(str, Enum):
    BOARD_DIRECTOR = "BoardDirector"
    RATE_ANALYST = "RateAnalyst"
    PROGRAM_OPERATOR = "ProgramOperator"
    CUSTOMER_SERVICE = "CustomerService"
    PORTFOLIO_MANAGER = "PortfolioManager"
    BILLING_COORDINATOR = "BillingCoordinator"
    FINANCE_CONTROLLER = "FinanceController"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    UTILITY_LIAISON = "UtilityLiaison"


# --- Entity shapes (documentation-grade; nullable computed fields Optional) ---

class Authority(TypedDict, total=False):
    id: str
    display_name: str
    utility_territory_code: str
    er_balancing_authority: str
    rate_setting_policy: str
    discount_floor_bps: int
    rps_target_pct: float
    bad_debt_trueup_cap_pct: float
    climate_reserve_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceAccount(TypedDict, total=False):
    id: str
    utility_account_number: str
    service_class: str
    annual_kwh_estimate: int
    annual_peak_kw: float
    da_eligible: bool
    enrollment_state: str
    product_election: str
    current_enrollment_notice_id: Optional[str]
    vintage_year: Optional[int]
    cumulative_billed_cents: int
    cumulative_remitted_cents: int
    uncollectible_flag: bool
    created_at: str
    updated_at: str
    version: int


class EnrollmentNotice(TypedDict, total=False):
    id: str
    wave_label: str
    notice_mailed_on: str
    opt_out_deadline: str
    enrollment_effective_on: str
    status: str
    target_service_classes: List[str]
    account_count_noticed: int
    account_count_opted_out: int
    account_count_enrolled: int
    created_at: str
    updated_at: str
    version: int


# Append-only (PRD §2.5): id + created_at only, NO updated_at / version
class OptOutRequest(TypedDict, total=False):
    id: str
    service_account_id: str
    enrollment_notice_id: str
    election_type: str
    received_at: str
    channel: str
    reversal_of_request_id: Optional[str]
    created_at: str


class Product(TypedDict, total=False):
    id: str
    product_code: str
    election_key: str
    renewable_pct: float
    status: str
    is_default: bool
    created_at: str
    updated_at: str
    version: int


class RateSchedule(TypedDict, total=False):
    id: str
    product_id: str
    period_start: str
    period_end: str
    energy_rate_cents_per_kwh: float
    pcia_rate_cents_per_kwh: float
    incumbent_benchmark_rate_cents_per_kwh: float
    comparison_margin_bps: int
    status: str
    adopted_by: Optional[str]
    proposed_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupplyContract(TypedDict, total=False):
    id: str
    counterparty: str
    contract_type: str
    delivery_start: str
    delivery_end: str
    capacity_mw: float
    total_mwh: float
    price_dollars_per_mwh: float
    rps_eligible_pct: float
    vintage_year: int
    status: str
    termination_fee_cents: int
    created_at: str
    updated_at: str
    version: int


# Append-only (PRD §2.5): id + created_at only
class LoadForecast(TypedDict, total=False):
    id: str
    snapshot_label: str
    forecast_variant: str
    as_of: str
    period_year: int
    total_energy_mwh: float
    coincident_peak_mw: float
    ra_requirement_mw: float
    coverage_gap_mwh: int
    created_at: str


class BillingExtract(TypedDict, total=False):
    id: str
    billing_month: str
    status: str
    submitted_on: Optional[str]
    line_count: int
    total_billed_cents: int
    total_pcia_collected_cents: int
    created_at: str
    updated_at: str
    version: int


# Append-only (PRD §2.5): id + created_at only
class BillingLine(TypedDict, total=False):
    id: str
    billing_extract_id: str
    service_account_id: str
    usage_kwh: int
    generation_charge_cents: int
    pcia_charge_cents: int
    product_election_at_billing: str
    created_at: str


class RemittanceFile(TypedDict, total=False):
    id: str
    remittance_period: str
    gross_remittance_cents: int
    utility_fee_bps: int
    net_remittance_cents: int
    applied_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BadDebtPool(TypedDict, total=False):
    id: str
    pool_period: str
    status: str
    written_off_cents: int
    billed_generation_cents: int
    cca_share_cents: int
    utility_share_cents: int
    reserve_draw_cents: int
    expensed_cents: int
    created_at: str
    updated_at: str
    version: int


class ComplianceFiling(TypedDict, total=False):
    id: str
    filing_type: str
    compliance_year: int
    rps_actual_pct: Optional[float]
    rps_shortfall_mwh: Optional[int]
    status: str
    prepared_by: Optional[str]
    reviewed_by: Optional[str]
    revision_count: int
    created_at: str
    updated_at: str
    version: int


# Append-only (PRD §2.5): id + created_at only
class RECRetirement(TypedDict, total=False):
    id: str
    compliance_filing_id: str
    supply_contract_id: str
    retired_mwh: float
    retirement_serial: str
    retired_on: str
    created_at: str
