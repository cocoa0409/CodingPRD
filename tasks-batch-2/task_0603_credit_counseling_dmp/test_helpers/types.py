"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    AGENCY_ADMIN = "AgencyAdmin"
    COUNSELOR = "Counselor"
    CREDITOR_REP = "CreditorRep"


class ClientStatus(str, Enum):
    INTAKE = "INTAKE"
    ACTIVE = "ACTIVE"
    DEFAULTED = "DEFAULTED"
    GRADUATED = "GRADUATED"
    WITHDRAWN = "WITHDRAWN"


class SessionType(str, Enum):
    BUDGET_INTAKE = "BUDGET_INTAKE"
    BANKRUPTCY_PREFILING = "BANKRUPTCY_PREFILING"
    BANKRUPTCY_PREDISCHARGE = "BANKRUPTCY_PREDISCHARGE"
    HUD_HOUSING = "HUD_HOUSING"


class SessionStatus(str, Enum):
    OPEN = "OPEN"
    NEEDS_REVISION = "NEEDS_REVISION"
    COMPLETED = "COMPLETED"
    CERTIFIED = "CERTIFIED"


class DebtAccountStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    ENROLLED = "ENROLLED"
    DROPPED = "DROPPED"
    SETTLED = "SETTLED"


class ProposalStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


# common_fields: true -> id + created_at + updated_at + version
class Agency(TypedDict):
    id: str
    name: str
    setup_fee_cents: int
    monthly_fee_cents: int
    current_cycle_index: int
    created_at: str
    updated_at: str
    version: int


class Counselor(TypedDict):
    id: str
    agency_id: str
    full_name: str
    hud_certified: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Creditor(TypedDict):
    id: str
    agency_id: str
    name: str
    default_concession_apr: float
    waives_late_fees: bool
    min_proposed_payment_pct: float
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    agency_id: str
    counselor_id: str
    full_name: str
    gross_monthly_income_cents: int
    housing_payment_cents: int
    monthly_deposit_cents: int
    front_end_dti: float
    back_end_dti: float
    total_enrolled_balance_cents: int
    projected_payoff_months: int
    missed_deposit_streak: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CounselingSession(TypedDict):
    id: str
    client_id: str
    counselor_id: str
    session_type: str
    status: str
    certificate_number: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DebtAccount(TypedDict):
    id: str
    client_id: str
    creditor_id: str
    account_ref: str
    original_balance_cents: int
    current_balance_cents: int
    original_apr: float
    concession_apr: Optional[float]
    min_payment_cents: int
    proposed_monthly_payment_cents: int
    proposal_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CreditorProposal(TypedDict):
    id: str
    debt_account_id: str
    creditor_id: str
    round_index: int
    requested_concession_apr: float
    requested_waive_late_fees: bool
    countered_concession_apr: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class DisbursementRun(TypedDict):
    id: str
    agency_id: str
    cycle_index: int
    clients_processed: int
    clients_defaulted: int
    total_disbursed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> append-only, ONLY id + created_at
class DepositRecord(TypedDict):
    id: str
    client_id: str
    cycle_index: int
    amount_cents: int
    posted: bool
    created_at: str


class DisbursementLine(TypedDict):
    id: str
    disbursement_run_id: str
    client_id: str
    debt_account_id: str
    amount_cents: int
    balance_after_cents: int
    created_at: str
