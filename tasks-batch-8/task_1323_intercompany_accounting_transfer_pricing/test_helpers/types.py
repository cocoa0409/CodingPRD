"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class FiscalYearStatus(str, Enum):
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class LegalEntityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    UNDER_AMENDMENT = "UNDER_AMENDMENT"
    TERMINATED = "TERMINATED"


class EliminationStatus(str, Enum):
    UNMATCHED = "UNMATCHED"
    MATCHED = "MATCHED"
    ELIMINATED = "ELIMINATED"


class SettlementStatus(str, Enum):
    UNSETTLED = "UNSETTLED"
    NETTED = "NETTED"
    SETTLED = "SETTLED"


class TrueUpRunStatus(str, Enum):
    DRAFT = "DRAFT"
    COMPUTED = "COMPUTED"
    APPROVED = "APPROVED"
    POSTED = "POSTED"


class StudyStatus(str, Enum):
    DRAFT = "DRAFT"
    CURRENT = "CURRENT"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"


class DocPackageStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    FILED = "FILED"


class AuditCaseStatus(str, Enum):
    OPENED = "OPENED"
    ACTIVE_PREP = "ACTIVE_PREP"
    SUBMITTED_TO_AUTHORITY = "SUBMITTED_TO_AUTHORITY"
    CLOSED_RESOLVED = "CLOSED_RESOLVED"
    CLOSED_AGREED = "CLOSED_AGREED"


class CashPoolStatus(str, Enum):
    OPEN = "OPEN"
    NETTING = "NETTING"
    SETTLED = "SETTLED"


class TransactionType(str, Enum):
    GOODS = "GOODS"
    SERVICES = "SERVICES"
    IP_ROYALTY = "IP_ROYALTY"
    FINANCING = "FINANCING"
    COST_SHARING = "COST_SHARING"


class PricingMethod(str, Enum):
    COST_PLUS = "COST_PLUS"
    TNMM = "TNMM"
    RESALE_MINUS = "RESALE_MINUS"
    CUP = "CUP"


class TrueUpMethod(str, Enum):
    TO_MEDIAN = "TO_MEDIAN"
    TO_RANGE_EDGE = "TO_RANGE_EDGE"


class DocType(str, Enum):
    MASTER_FILE = "MASTER_FILE"
    LOCAL_FILE = "LOCAL_FILE"
    CBC_REPORT = "CBC_REPORT"


class CaseType(str, Enum):
    AUDIT = "AUDIT"
    APA = "APA"


class InterestMethod(str, Enum):
    AVERAGE_BALANCE = "AVERAGE_BALANCE"
    CLOSING_BALANCE = "CLOSING_BALANCE"


class UserRole(str, Enum):
    GROUP_TAX_ADMIN = "GroupTaxAdmin"
    TAX_ANALYST = "TaxAnalyst"
    TAX_MANAGER = "TaxManager"
    TRANSFER_PRICING_LEAD = "TransferPricingLead"
    TREASURY_MANAGER = "TreasuryManager"


# --- Entity TypedDicts ---
# Every resource carries the common fields id / created_at / updated_at /
# version (PRD section 2.4).


class FiscalYear(TypedDict, total=False):
    id: str
    year_index: int
    group_revenue_eur: int
    cbc_required: bool
    status: str
    consolidated_intercompany_net_cents: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LegalEntity(TypedDict, total=False):
    id: str
    name: str
    country_code: str
    functional_currency: str
    status: str
    created_at: str
    updated_at: str
    version: int


class IntercompanyAgreement(TypedDict, total=False):
    id: str
    provider_entity_id: str
    recipient_entity_id: str
    transaction_type: str
    pricing_method: str
    markup_bp: int
    true_up_method: str
    benchmarking_study_id: str
    pinned_study_id: Optional[str]
    pinned_p25_bp: Optional[int]
    pinned_median_bp: Optional[int]
    pinned_p75_bp: Optional[int]
    effective_from: str
    effective_to: str
    status: str
    pending_markup_bp: Optional[int]
    pending_study_id: Optional[str]
    amendment_started_by_user_id: Optional[str]
    created_by_user_id: str
    amendments_count: int
    pricing_review_required: bool
    apa_locked: bool
    created_at: str
    updated_at: str
    version: int


class ICTransaction(TypedDict, total=False):
    id: str
    agreement_id: str
    fiscal_year_id: str
    cost_base_cents: int
    provider_revenue_cents: int
    recipient_cost_cents: int
    origin_run_id: Optional[str]
    is_true_up_adjustment: bool
    provisional_al_price_cents: int
    margin_bp: int
    elimination_status: str
    settlement_status: str
    matched_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrueUpRun(TypedDict, total=False):
    id: str
    agreement_id: str
    fiscal_year_id: str
    status: str
    actual_margin_bp: Optional[int]
    true_up_amount_cents: Optional[int]
    adjustment_transaction_id: Optional[str]
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BenchmarkingStudy(TypedDict, total=False):
    id: str
    transaction_type: str
    region: str
    vintage_year: int
    comparables_bp: List[int]
    p25_bp: Optional[int]
    median_bp: Optional[int]
    p75_bp: Optional[int]
    status: str
    supersedes_study_id: Optional[str]
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class DocPackage(TypedDict, total=False):
    id: str
    fiscal_year_id: str
    entity_id: Optional[str]
    doc_type: str
    status: str
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    filed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditCase(TypedDict, total=False):
    id: str
    entity_id: str
    case_type: str
    authority_country: str
    covered_year_indexes: Optional[List[int]]
    defense_doc_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CashPoolPosition(TypedDict, total=False):
    entity_id: str
    balance_cents: int
    accrued_balance_day_cents: int
    pending_cents: int
    interest_cents: int
    fee_cents: int
    status: str


class CashPool(TypedDict, total=False):
    id: str
    fiscal_year_id: str
    interest_method: str
    admin_fee_cents: int
    status: str
    positions: List[Dict[str, Any]]
    opened_at_utc: str
    netting_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int
