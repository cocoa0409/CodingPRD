"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    FILING_COORDINATOR = "FilingCoordinator"
    FILING_AGENT = "FilingAgent"
    EQUITY_PLAN_ADMIN = "EquityPlanAdmin"
    REPORTING_INSIDER = "ReportingInsider"


class PersonStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    EXITED = "EXITED"


class TransactionCode(str, Enum):
    P = "P"
    S = "S"
    A = "A"
    M = "M"
    F = "F"
    G = "G"
    V = "V"


class SecurityType(str, Enum):
    COMMON_STOCK = "COMMON_STOCK"
    OPTION = "OPTION"
    RSU = "RSU"
    DERIVATIVE_OTHER = "DERIVATIVE_OTHER"


class TransactionSource(str, Enum):
    EQUITY_PLAN_FEED = "EQUITY_PLAN_FEED"
    MANUAL = "MANUAL"


class Direction(str, Enum):
    ACQUIRED = "ACQUIRED"
    DISPOSED = "DISPOSED"


class TransactionStatus(str, Enum):
    INGESTED = "INGESTED"
    CONFIRMED = "CONFIRMED"
    REPORTED = "REPORTED"
    VOID = "VOID"


class FormType(str, Enum):
    FORM_3 = "FORM_3"
    FORM_4 = "FORM_4"
    FORM_5 = "FORM_5"


class FilingStatus(str, Enum):
    DRAFT = "DRAFT"
    READY = "READY"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    DISCARDED = "DISCARDED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ADOPTED = "ADOPTED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REJECTED = "REJECTED"
    TERMINATED = "TERMINATED"


class HolderStatus(str, Enum):
    MONITORING = "MONITORING"
    FILING_REQUIRED = "FILING_REQUIRED"
    FILED = "FILED"
    AMENDMENT_REQUIRED = "AMENDMENT_REQUIRED"


class ScheduleType(str, Enum):
    SCHEDULE_13D = "SCHEDULE_13D"
    SCHEDULE_13G = "SCHEDULE_13G"


class SweepStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"


class AuthorizationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


# --- Entity TypedDicts (PRD §2.4: id, created_at, updated_at, version) ---


class Issuer(TypedDict, total=False):
    id: str
    name: str
    ticker: str
    cik: str
    edgar_ccc: str
    shares_outstanding: int
    fiscal_year_end_month: int
    holiday_dates: List[str]
    next_earnings_filing_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReportingPerson(TypedDict, total=False):
    id: str
    issuer_id: str
    full_name: str
    person_cik: str
    is_director: bool
    is_officer: bool
    is_ten_pct_owner: bool
    status: str
    designation_date: Optional[str]
    exit_date: Optional[str]
    late_filing_count: int
    delinquent_flag: bool
    open_obligation_count: int
    created_at: str
    updated_at: str
    version: int


class SecurityTransaction(TypedDict, total=False):
    id: str
    reporting_person_id: str
    issuer_id: str
    filing_id: Optional[str]
    plan_id: Optional[str]
    transaction_date: str
    transaction_code: str
    security_type: str
    shares: int
    price_per_share: Optional[float]
    source: str
    direction: str
    shares_owned_after: Optional[int]
    ingested_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SecuritiesFiling(TypedDict, total=False):
    id: str
    issuer_id: str
    reporting_person_id: str
    form_type: str
    amends_filing_id: Optional[str]
    filing_deadline: str
    is_late: bool
    status: str
    prepared_by_user_id: Optional[str]
    submitted_by_user_id: Optional[str]
    submitted_at: Optional[str]
    accepted_at: Optional[str]
    accession_number: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TradingPlan10b5_1(TypedDict, total=False):
    id: str
    reporting_person_id: str
    issuer_id: str
    plan_name: str
    first_trade_date: str
    expiration_date: str
    status: str
    adoption_date: Optional[str]
    cooling_off_end_date: Optional[str]
    termination_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BlackoutWindow(TypedDict, total=False):
    id: str
    issuer_id: str
    start_date: str
    end_date: str
    reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BeneficialHolder(TypedDict, total=False):
    id: str
    issuer_id: str
    holder_name: str
    holder_cik: Optional[str]
    shares_beneficially_owned: int
    exercisable_derivative_shares: int
    current_pct: float
    fully_diluted_pct: float
    last_reported_pct: Optional[float]
    schedule_type: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# PRD §2.4: the PositionChange event is immutable — id + created_at only,
# no updated_at, no version.
class PositionChange(TypedDict, total=False):
    id: str
    holder_id: str
    shares_delta: int
    derivative_shares_delta: int
    effective_date: str
    note: Optional[str]
    created_at: str


class AnnualSweep(TypedDict, total=False):
    id: str
    issuer_id: str
    fiscal_year: int
    fy_start_date: str
    fy_end_date: str
    status: str
    run_at: Optional[str]
    results: list
    created_at: str
    updated_at: str
    version: int


class FilingAgentAuthorization(TypedDict, total=False):
    id: str
    issuer_id: str
    agent_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int
