"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    CARRIER_ADMIN = "CarrierAdmin"
    PRODUCER = "Producer"
    SUITABILITY_REVIEWER = "SuitabilityReviewer"
    PRINCIPAL = "Principal"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    OPERATIONS_DESK = "OperationsDesk"


class ProducerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FLAGGED = "FLAGGED"
    SUSPENDED = "SUSPENDED"


class ContractStatus(str, Enum):
    IN_FORCE = "IN_FORCE"
    SURRENDER_PENDING = "SURRENDER_PENDING"
    EXCHANGED = "EXCHANGED"


class CaseStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SUITABILITY_REVIEW = "SUITABILITY_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    PENDING_PRINCIPAL = "PENDING_PRINCIPAL"
    APPROVED = "APPROVED"
    FUNDS_REQUESTED = "FUNDS_REQUESTED"
    FUNDS_RECEIVED = "FUNDS_RECEIVED"
    IN_FREE_LOOK = "IN_FREE_LOOK"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    RESCINDED = "RESCINDED"


TERMINAL_CASE_STATES = {
    CaseStatus.COMPLETED.value,
    CaseStatus.REJECTED.value,
    CaseStatus.WITHDRAWN.value,
    CaseStatus.RESCINDED.value,
}


class ExchangeType(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"


class DocType(str, Enum):
    REPLACEMENT_DISCLOSURE = "REPLACEMENT_DISCLOSURE"
    SUITABILITY_FORM = "SUITABILITY_FORM"
    IN_FORCE_ILLUSTRATION = "IN_FORCE_ILLUSTRATION"


REQUIRED_DOC_TYPES = [d.value for d in DocType]


class DocumentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class AnalysisStatus(str, Enum):
    FINAL = "FINAL"
    SUPERSEDED = "SUPERSEDED"


class TransferStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RECEIVED = "RECEIVED"
    FAILED = "FAILED"
    RETURNED = "RETURNED"


class DecisionStage(str, Enum):
    SUITABILITY = "SUITABILITY"
    PRINCIPAL = "PRINCIPAL"


class Decision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_INFO = "REQUEST_INFO"


class EventType(str, Enum):
    CASE_SUBMITTED = "CASE_SUBMITTED"
    CASE_WITHDRAWN = "CASE_WITHDRAWN"
    CASE_REJECTED = "CASE_REJECTED"
    EXCHANGE_COMPLETED = "EXCHANGE_COMPLETED"
    EXCHANGE_RESCINDED = "EXCHANGE_RESCINDED"
    PRODUCER_FLAGGED = "PRODUCER_FLAGGED"
    PRODUCER_UNFLAGGED = "PRODUCER_UNFLAGGED"
    PRODUCER_SUSPENDED = "PRODUCER_SUSPENDED"
    PRODUCER_REINSTATED = "PRODUCER_REINSTATED"


class SurrenderScheduleEntry(TypedDict):
    contract_year: int
    pct_bps: int


# --- Entities carrying id + created_at + updated_at + version (PRD §2.5) ---


class Producer(TypedDict, total=False):
    id: str
    license_number: str
    full_name: str
    home_state_code: str
    status: str
    submitted_case_count_12m: int
    completed_exchange_count_12m: int
    rescinded_exchange_count_12m: int
    rescission_rate_completed_bps: int
    rescission_rate_submitted_bps: int
    last_churn_eval_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    state_code: str
    age_years: int
    is_senior: bool
    last_rescinded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExistingContract(TypedDict, total=False):
    id: str
    client_id: str
    carrier_name: str
    contract_number: str
    issue_date: str
    account_value_cents: int
    tax_basis_cents: int
    surrender_schedule: List[SurrenderScheduleEntry]
    living_benefit_rider: bool
    rider_benefit_base_cents: int
    rider_annual_fee_bps: int
    last_exchange_completed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ExchangeCase(TypedDict, total=False):
    id: str
    producer_id: str
    client_id: str
    existing_contract_id: str
    exchange_type: str
    exchange_amount_cents: int
    new_product_code: str
    new_product_surrender_years: int
    new_product_bonus_bps: int
    new_product_annual_fee_bps: int
    status: str
    submitted_at: Optional[str]
    reviewed_by_id: Optional[str]
    approved_by_id: Optional[str]
    free_look_started_at: Optional[str]
    free_look_deadline_date: Optional[str]
    completed_at: Optional[str]
    rescinded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CaseDocument(TypedDict, total=False):
    id: str
    case_id: str
    doc_type: str
    status: str
    revision: int
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComparisonAnalysis(TypedDict, total=False):
    id: str
    case_id: str
    assumed_old_growth_bps: int
    assumed_new_growth_bps: int
    analysis_date: str
    exchange_base_cents: int
    surrender_pct_bps_today: int
    surrender_charge_today_cents: int
    surrender_pct_bps_at_settlement: int
    surrender_charge_at_settlement_cents: int
    amount_received_cents: int
    bonus_credit_cents: int
    benefit_loss_cents: int
    net_replacement_cost_cents: int
    break_even_years: int
    basis_transferred_cents: int
    basis_remaining_cents: int
    status: str
    supersedes_analysis_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FundsTransfer(TypedDict, total=False):
    id: str
    case_id: str
    amount_cents: int
    surrender_charge_cents: int
    basis_transferred_cents: int
    pre_exchange_value_cents: int
    pre_exchange_basis_cents: int
    status: str
    requested_at: str
    received_at: Optional[str]
    returned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Append-only audit records: only id + created_at (PRD §2.5) ---


class ReviewDecision(TypedDict, total=False):
    id: str
    created_at: str
    case_id: str
    stage: str
    reviewer_id: str
    decision: str
    rationale: str


class ActivityEvent(TypedDict, total=False):
    id: str
    created_at: str
    producer_id: str
    case_id: Optional[str]
    event_type: str
    event_at: str
