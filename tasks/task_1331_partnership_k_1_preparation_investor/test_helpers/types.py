"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    FUND_TAX_ADMIN = "FundTaxAdmin"
    TAX_PREPARER = "TaxPreparer"
    TAX_REVIEWER = "TaxReviewer"
    INVESTOR_SERVICES_REP = "InvestorServicesRep"
    INVESTOR = "Investor"


class TaxYearStatus(str, Enum):
    OPEN = "OPEN"
    BOOKS_CLOSED = "BOOKS_CLOSED"
    ALLOCATED = "ALLOCATED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"


class PartnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class PartnerType(str, Enum):
    US_INDIVIDUAL = "US_INDIVIDUAL"
    US_ENTITY = "US_ENTITY"
    TAX_EXEMPT = "TAX_EXEMPT"
    FOREIGN_INDIVIDUAL = "FOREIGN_INDIVIDUAL"
    FOREIGN_ENTITY = "FOREIGN_ENTITY"


class PartnerClass(str, Enum):
    GENERAL = "GENERAL"
    LIMITED = "LIMITED"


class CapitalEventType(str, Enum):
    CONTRIBUTION = "CONTRIBUTION"
    DISTRIBUTION = "DISTRIBUTION"
    ALLOCATION_SHARE = "ALLOCATION_SHARE"
    TRANSFER_IN = "TRANSFER_IN"
    TRANSFER_OUT = "TRANSFER_OUT"
    ADJUSTMENT = "ADJUSTMENT"


class CapitalEventStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class TransferStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class RunKind(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class AllocationRunStatus(str, Enum):
    COMPUTED = "COMPUTED"
    LOCKED = "LOCKED"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"


class AllocationCategory(str, Enum):
    ORDINARY = "ORDINARY"
    CAPITAL_GAIN = "CAPITAL_GAIN"
    INTEREST = "INTEREST"


class AppliedMechanism(str, Enum):
    PRO_RATA = "PRO_RATA"
    SPECIAL = "SPECIAL"
    PREFERRED = "PREFERRED"
    CATCHUP = "CATCHUP"
    RESIDUAL = "RESIDUAL"


class SpecialAllocationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class CompositeFilingStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    ACCEPTED = "ACCEPTED"


class WithholdingMethod(str, Enum):
    SAFE_HARBOR = "SAFE_HARBOR"
    CURRENT_ACTUAL = "CURRENT_ACTUAL"


class WithholdingStatus(str, Enum):
    ACCRUED = "ACCRUED"
    PARTIALLY_REMITTED = "PARTIALLY_REMITTED"
    REMITTED = "REMITTED"
    RECONCILED = "RECONCILED"


class K1PrepStatus(str, Enum):
    GENERATED = "GENERATED"
    REVIEWED = "REVIEWED"
    APPROVED = "APPROVED"
    DELIVERED = "DELIVERED"
    SUPERSEDED = "SUPERSEDED"


class K1DeliveryStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    BOUNCED = "BOUNCED"


class DeliveryMethod(str, Enum):
    PORTAL = "PORTAL"
    MAIL = "MAIL"
    EMAIL = "EMAIL"


class AmendmentReason(str, Enum):
    ALLOCATION_CHANGE = "ALLOCATION_CHANGE"
    PARTNER_DATA_FIX = "PARTNER_DATA_FIX"
    STATE_REAPPORTIONMENT = "STATE_REAPPORTIONMENT"
    LATE_K1_CORRECTION = "LATE_K1_CORRECTION"


class AmendmentStatus(str, Enum):
    OPENED = "OPENED"
    IN_PREP = "IN_PREP"
    IN_REVIEW = "IN_REVIEW"
    ISSUED = "ISSUED"


class TicketCategory(str, Enum):
    ALLOCATION_QUESTION = "ALLOCATION_QUESTION"
    WITHHOLDING_QUESTION = "WITHHOLDING_QUESTION"
    DELIVERY_ISSUE = "DELIVERY_ISSUE"
    AMENDED_K1_QUESTION = "AMENDED_K1_QUESTION"
    STATE_FILING_QUESTION = "STATE_FILING_QUESTION"


class TicketStatus(str, Enum):
    OPEN = "OPEN"
    ANSWERED = "ANSWERED"
    REOPENED = "REOPENED"
    CLOSED = "CLOSED"


class Fund(TypedDict, total=False):
    id: str
    legal_name: str
    ein: str
    waterfall_hurdle_rate_bps: int
    waterfall_catchup_bps: int
    waterfall_carry_bps: int
    foreign_ownership_cap_pct_bps: int
    management_fee_rate_bps: int
    fee_discount_threshold_cents: int
    fee_discount_bps: int
    created_at: str
    updated_at: str
    version: int


class TaxYear(TypedDict, total=False):
    id: str
    fund_id: str
    year: int
    gross_ordinary_income_cents: int
    capital_gain_cents: int
    interest_income_cents: int
    federal_extension_filed: bool
    management_fee_cents: int
    net_ordinary_income_cents: int
    k1_delivery_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Partner(TypedDict, total=False):
    id: str
    fund_id: str
    legal_name: str
    partner_type: str
    partner_class: str
    residency_state: str
    ownership_pct_bps: int
    capital_commitment_cents: int
    admission_date: str
    is_foreign: bool
    current_ownership_pct_bps: int
    capital_account_balance_cents: int
    tax_basis_cents: int
    excess_distribution_gain_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CapitalAccountEvent(TypedDict, total=False):
    id: str
    partner_id: str
    tax_year_id: str
    event_type: str
    amount_cents: int
    effective_date: str
    memo: Optional[str]
    reverses_event_id: Optional[str]
    sequence_no: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OwnershipTransfer(TypedDict, total=False):
    id: str
    fund_id: str
    transferor_partner_id: str
    transferee_partner_id: str
    pct_bps: int
    effective_date: str
    settlement_date: str
    transferred_capital_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class AllocationRun(TypedDict, total=False):
    id: str
    tax_year_id: str
    run_kind: str
    run_seq: int
    ordinary_total_cents: int
    capital_gain_total_cents: int
    interest_total_cents: int
    computed_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AllocationLine(TypedDict, total=False):
    id: str
    run_id: str
    partner_id: str
    category: str
    amount_cents: int
    applied_mechanism: str
    created_at: str
    updated_at: str
    version: int


class SpecialAllocation(TypedDict, total=False):
    id: str
    tax_year_id: str
    partner_id: str
    category: str
    target_pct_bps: int
    effective_from: str
    effective_to: str
    proposed_by_user_id: str
    reviewed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CompositeFiling(TypedDict, total=False):
    id: str
    tax_year_id: str
    state_code: str
    apportionment_pct_bps: int
    composite_rate_bps: int
    min_income_cents: int
    included_partner_ids: List[str]
    total_state_source_income_cents: int
    total_composite_tax_cents: int
    filed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WithholdingRecord(TypedDict, total=False):
    id: str
    partner_id: str
    tax_year_id: str
    quarter: int
    method: str
    annual_ecti_cents: int
    rate_bps: int
    accrued_cents: int
    remitted_cents: int
    due_date: str
    penalty_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class K1Package(TypedDict, total=False):
    id: str
    partner_id: str
    tax_year_id: str
    run_id: str
    generation: int
    supersedes_k1_id: Optional[str]
    prep_status: str
    delivery_status: str
    line_snapshot: dict
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    delivery_method: Optional[str]
    delivered_at: Optional[str]
    is_late: bool
    created_at: str
    updated_at: str
    version: int


class K1Amendment(TypedDict, total=False):
    id: str
    k1_package_id: str
    reason: str
    opened_by_user_id: str
    prepared_by_user_id: Optional[str]
    issued_by_user_id: Optional[str]
    new_k1_package_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InvestorTicket(TypedDict, total=False):
    id: str
    partner_id: str
    tax_year_id: Optional[str]
    category: str
    subject: str
    due_at: str
    is_escalated: bool
    answer_text: Optional[str]
    answered_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
