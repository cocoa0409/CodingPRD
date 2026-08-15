"""Domain types: entity shapes, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List, Dict


class UserRole(str, Enum):
    REVENUE_ACCOUNTANT = "RevenueAccountant"
    REVENUE_MANAGER = "RevenueManager"
    CONTRACT_REVIEWER = "ContractReviewer"
    CONTROLLER = "Controller"
    SYSTEM_ADMIN = "SystemAdmin"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    ABSORBED = "ABSORBED"


class PobStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    SATISFIED = "SATISFIED"
    CANCELLED = "CANCELLED"


class RecognitionPattern(str, Enum):
    POINT_IN_TIME = "POINT_IN_TIME"
    OVER_TIME_INPUT_COST = "OVER_TIME_INPUT_COST"
    OVER_TIME_STRAIGHT_LINE = "OVER_TIME_STRAIGHT_LINE"


class RiskTier(str, Enum):
    STANDARD = "STANDARD"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"


class SspStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class EstimateStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class EstimateMethod(str, Enum):
    EXPECTED_VALUE = "EXPECTED_VALUE"
    MOST_LIKELY = "MOST_LIKELY"


class ModificationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ModType(str, Enum):
    CUMULATIVE_CATCH_UP = "CUMULATIVE_CATCH_UP"
    PROSPECTIVE = "PROSPECTIVE"
    SEPARATE_CONTRACT = "SEPARATE_CONTRACT"


class ClauseStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ClauseType(str, Enum):
    TERMINATION_FOR_CONVENIENCE = "TERMINATION_FOR_CONVENIENCE"
    EXTENDED_PAYMENT_TERMS = "EXTENDED_PAYMENT_TERMS"
    PENALTY = "PENALTY"
    RIGHT_OF_RETURN = "RIGHT_OF_RETURN"
    ACCEPTANCE_CLAUSE = "ACCEPTANCE_CLAUSE"
    MOST_FAVORED_CUSTOMER = "MOST_FAVORED_CUSTOMER"


class ReviewTaskStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    IN_REVIEW = "IN_REVIEW"
    RECOMMENDED = "RECOMMENDED"
    DECIDED = "DECIDED"


class Recommendation(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class Decision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RETURN = "RETURN"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class PeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class EntryType(str, Enum):
    RECOGNITION = "RECOGNITION"
    CATCH_UP_ADJUSTMENT = "CATCH_UP_ADJUSTMENT"
    REVERSAL = "REVERSAL"


class EntryOrigin(str, Enum):
    COST_ENTRY = "COST_ENTRY"
    RECOGNIZE = "RECOGNIZE"
    SATISFY = "SATISFY"
    MODIFICATION = "MODIFICATION"
    ESTIMATE = "ESTIMATE"
    REVERSAL = "REVERSAL"


class EntryStatus(str, Enum):
    POSTED = "POSTED"
    LOCKED = "LOCKED"


class PackStatus(str, Enum):
    DRAFT = "DRAFT"
    ASSEMBLED = "ASSEMBLED"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


# --- Entity TypedDicts ---
# Standard entities (PRD §2.4) carry id + created_at + updated_at + version.
# RevenueEntry and CostEntry are append-only (PRD §2.4): id + created_at only.

class Customer(TypedDict, total=False):
    id: str
    legal_name: str
    external_ref: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict, total=False):
    id: str
    customer_id: str
    contract_ref: str
    signed_date: str
    risk_tier: str
    package_negotiated_flag: bool
    combined_into_contract_id: Optional[str]
    fixed_consideration_cents: int
    vc_estimate_cents: int
    transaction_price_cents: int
    active_vc_estimate_id: Optional[str]
    allocated_total_cents: int
    billed_to_date_cents: int
    recognized_to_date_cents: int
    deferred_revenue_balance_cents: int
    contract_asset_balance_cents: int
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PerformanceObligation(TypedDict, total=False):
    id: str
    contract_id: str
    pob_ref: str
    description: Optional[str]
    product_code: str
    region: str
    recognition_pattern: str
    service_start_date: Optional[str]
    service_end_date: Optional[str]
    estimated_total_cost_cents: Optional[int]
    ssp_cents: int
    allocated_amount_cents: int
    costs_incurred_to_date_cents: int
    recognized_revenue_cents: int
    progress_pct: float
    status: str
    satisfied_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SspPrice(TypedDict, total=False):
    id: str
    product_code: str
    region: str
    ssp_cents: int
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class VariableConsiderationEstimate(TypedDict, total=False):
    id: str
    contract_id: str
    method: str
    scenarios: List[dict]
    unconstrained_amount_cents: int
    constrained_amount_cents: int
    status: str
    proposed_by_user_id: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ContractModification(TypedDict, total=False):
    id: str
    contract_id: str
    mod_type: str
    delta_fixed_consideration_cents: int
    effective_date: str
    reason: Optional[str]
    proposed_by_user_id: str
    approved_by_user_id: Optional[str]
    spawned_contract_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ContractClause(TypedDict, total=False):
    id: str
    contract_id: str
    clause_code: str
    clause_type: str
    is_non_standard: bool
    clause_text: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReviewTask(TypedDict, total=False):
    id: str
    contract_id: str
    clause_id: str
    status: str
    reviewer_user_id: Optional[str]
    recommendation: Optional[str]
    recommended_by_user_id: Optional[str]
    decision: Optional[str]
    decided_by_user_id: Optional[str]
    note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    contract_id: str
    invoice_ref: str
    amount_cents: int
    invoice_date: str
    status: str
    voided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccountingPeriod(TypedDict, total=False):
    id: str
    period_code: str
    start_date: str
    end_date: str
    status: str
    reopened_once: bool
    recognized_total_cents: int
    created_at: str
    updated_at: str
    version: int


# Append-only (PRD §2.4): only id + created_at; NO updated_at, NO version.
class RevenueEntry(TypedDict, total=False):
    id: str
    contract_id: str
    pob_id: str
    accounting_period_id: str
    reversed_entry_id: Optional[str]
    entry_type: str
    amount_cents: int
    posting_date: str
    origin: str
    status: str
    created_at: str


# Append-only (PRD §2.4): only id + created_at; NO updated_at, NO version.
class CostEntry(TypedDict, total=False):
    id: str
    pob_id: str
    amount_cents: int
    incurred_date: str
    memo: Optional[str]
    created_at: str


class DisclosurePack(TypedDict, total=False):
    id: str
    accounting_period_id: str
    status: str
    rpo_cents: Optional[int]
    period_revenue_cents: Optional[int]
    revenue_by_region: Optional[Dict[str, int]]
    revenue_by_product: Optional[Dict[str, int]]
    contract_asset_total_cents: Optional[int]
    deferred_revenue_total_cents: Optional[int]
    assembled_by_user_id: Optional[str]
    finalized_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Rollforward(TypedDict, total=False):
    contract_id: str
    accounting_period_id: str
    beginning_billed_cents: int
    beginning_recognized_cents: int
    billed_cents: int
    recognized_cents: int
    catch_up_cents: int
    reversal_cents: int
    ending_billed_cents: int
    ending_recognized_cents: int
    ending_deferred_revenue_cents: int
    ending_contract_asset_cents: int
