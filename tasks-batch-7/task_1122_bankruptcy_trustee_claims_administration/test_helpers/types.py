"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §2.6, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    TRUSTEE = "Trustee"
    CLERK = "Clerk"
    COURT = "Court"
    CREDITOR = "Creditor"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    ASSET_INVESTIGATION = "ASSET_INVESTIGATION"
    CLAIMS_ADMINISTRATION = "CLAIMS_ADMINISTRATION"
    LIQUIDATION = "LIQUIDATION"
    DISTRIBUTION = "DISTRIBUTION"
    FINAL_REPORT = "FINAL_REPORT"
    CLOSED = "CLOSED"
    CONVERTED_DISMISSED = "CONVERTED_DISMISSED"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    OBJECTED = "OBJECTED"
    ALLOWED = "ALLOWED"
    DISALLOWED = "DISALLOWED"
    WITHDRAWN = "WITHDRAWN"


class ObjectionStatus(str, Enum):
    PENDING = "PENDING"
    SUSTAINED = "SUSTAINED"
    OVERRULED = "OVERRULED"
    SETTLED = "SETTLED"
    WITHDRAWN = "WITHDRAWN"


class AssetStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    MARKED_FOR_SALE = "MARKED_FOR_SALE"
    IN_AUCTION = "IN_AUCTION"
    SOLD = "SOLD"
    ABANDONED = "ABANDONED"
    EXEMPT_RELEASED = "EXEMPT_RELEASED"


class ActionStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    ANALYZED = "ANALYZED"
    DEMANDED = "DEMANDED"
    SETTLED = "SETTLED"
    JUDGMENT = "JUDGMENT"
    RESCINDED = "RESCINDED"
    ABANDONED = "ABANDONED"


class DepositStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class SaleStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    CONSUMMATED = "CONSUMMATED"
    CANCELLED = "CANCELLED"


class ProceedsStatus(str, Enum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class PlanStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    EXECUTING = "EXECUTING"
    FULLY_DISTRIBUTED = "FULLY_DISTRIBUTED"
    VACATED = "VACATED"


class DividendStatus(str, Enum):
    COMPUTED = "COMPUTED"
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class FeeStatus(str, Enum):
    FILED = "FILED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"


class FinalReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    APPROVED = "APPROVED"


class PriorityClass(str, Enum):
    SECURED = "SECURED"
    PRIORITY_TAX = "PRIORITY_TAX"
    PRIORITY_WAGE = "PRIORITY_WAGE"
    PRIORITY_CONSUMER = "PRIORITY_CONSUMER"
    GENERAL_UNSECURED = "GENERAL_UNSECURED"


class ActionType(str, Enum):
    PREFERENCE_547 = "PREFERENCE_547"
    FRAUDULENT_548 = "FRAUDULENT_548"


class ApplicantRole(str, Enum):
    TRUSTEE = "TRUSTEE"
    AUCTIONEER = "AUCTIONEER"
    COUNSEL = "COUNSEL"


class CommissionBasis(str, Enum):
    DISBURSED = "DISBURSED"
    PROPOSED = "PROPOSED"


class ObjectionGrounds(str, Enum):
    DUPLICATE = "DUPLICATE"
    INSUFFICIENT_DOCUMENTATION = "INSUFFICIENT_DOCUMENTATION"
    AMOUNT_DISPUTED = "AMOUNT_DISPUTED"
    WRONG_CLASS = "WRONG_CLASS"
    LATE_FILED = "LATE_FILED"
    NOT_OWED = "NOT_OWED"


class SettleOutcome(str, Enum):
    ALLOW = "ALLOW"
    DISALLOW = "DISALLOW"
    PARTIAL = "PARTIAL"


# --- Entity TypedDicts (PRD §2.5 common fields: id, created_at, updated_at, version) ---

class Case(TypedDict, total=False):
    id: str
    case_number: str
    debtor_name: str
    filed_on: str
    district: str
    status: str
    claim_bar_date: Optional[str]
    bar_date_noticed: bool
    estate_cash_on_hand_cents: int
    allowed_claims_total_cents: int
    scheduled_unsecured_total_cents: int
    no_asset_report_filed: bool
    objection_window_days: int
    trustee_user_id: str
    created_at: str
    updated_at: str
    version: int


class Creditor(TypedDict, total=False):
    id: str
    legal_name: str
    creditor_ref: str
    insider: bool
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    case_id: str
    creditor_id: str
    claim_number: int
    received_at: str
    filed_amount_cents: int
    allowed_amount_cents: int
    priority_class: str
    secured_by_asset_id: Optional[str]
    reclassified_from_claim_id: Optional[str]
    late: bool
    status: str
    objection_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClaimObjection(TypedDict, total=False):
    id: str
    case_id: str
    claim_id: str
    grounds: str
    proposed_allowed_amount_cents: int
    proposed_priority_class: str
    status: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict, total=False):
    id: str
    case_id: str
    description: str
    scheduled_value_cents: int
    exempt: bool
    encumbered_claim_id: Optional[str]
    status: str
    realized_proceeds_cents: int
    created_at: str
    updated_at: str
    version: int


class AvoidanceAction(TypedDict, total=False):
    id: str
    case_id: str
    transferee_creditor_id: str
    transfer_date: str
    transfer_amount_cents: int
    action_type: str
    lookback_window_days: int
    avoidable: bool
    demand_amount_cents: int
    recovered_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RecoveryDeposit(TypedDict, total=False):
    id: str
    case_id: str
    avoidance_action_id: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AuctionSale(TypedDict, total=False):
    id: str
    case_id: str
    asset_id: str
    buyer_name: str
    hammer_price_cents: int
    sale_costs_cents: int
    net_proceeds_cents: int
    sale_approved_on: Optional[str]
    effective_on: Optional[str]
    proceeds_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DistributionPlan(TypedDict, total=False):
    id: str
    case_id: str
    plan_sequence: int
    reserve_for_objected_cents: int
    distributable_cents: int
    status: str
    proposed_at: str
    created_at: str
    updated_at: str
    version: int


class PlanClassAllocation(TypedDict, total=False):
    id: str
    plan_id: str
    case_id: str
    priority_class: str
    allocated_cents: int
    paid_total_cents: int
    created_at: str
    updated_at: str
    version: int


class Dividend(TypedDict, total=False):
    id: str
    plan_id: str
    claim_id: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeApplication(TypedDict, total=False):
    id: str
    case_id: str
    applicant_role: str
    requested_amount_cents: int
    commission_basis: Optional[str]
    computed_commission_cents: int
    status: str
    approved_amount_cents: Optional[int]
    effective_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


# PRD §2.5: "The `FinalReport` is the single exception to this convention:
# it carries only `id` and `created_at`" — NO updated_at, NO version.
class FinalReport(TypedDict, total=False):
    id: str
    case_id: str
    total_receipts_cents: int
    total_dividends_cents: int
    total_fees_cents: int
    unclaimed_funds_cents: int
    status: str
    created_at: str
