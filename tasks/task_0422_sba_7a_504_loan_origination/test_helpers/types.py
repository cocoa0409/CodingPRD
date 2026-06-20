"""Domain types: entity TypedDicts, status enums, role enum.

All twelve resource types carry the common system-managed fields id, created_at,
updated_at, and version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Roles ---
class UserRole(str, Enum):
    LOAN_OFFICER = "LoanOfficer"
    CREDIT_APPROVER = "CreditApprover"
    SBA_OFFICER = "SbaOfficer"
    INVESTOR_SERVICER = "InvestorServicer"


# --- Status enums ---
class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDERWRITING = "UNDERWRITING"
    REVISION = "REVISION"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    AUTHORIZED = "AUTHORIZED"
    DISBURSING = "DISBURSING"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"
    DECLINED = "DECLINED"


class ServicingStatus(str, Enum):
    NOT_SERVICING = "NOT_SERVICING"
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"
    DEFAULTED = "DEFAULTED"
    LIQUIDATED = "LIQUIDATED"
    PAID_IN_FULL = "PAID_IN_FULL"


class GuarantyStatus(str, Enum):
    RETAINED = "RETAINED"
    SOLD = "SOLD"
    REPURCHASED = "REPURCHASED"
    PURCHASED_BY_SBA = "PURCHASED_BY_SBA"


class FormPackageStatus(str, Enum):
    INCOMPLETE = "INCOMPLETE"
    SUBMITTED = "SUBMITTED"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"


class CreditMemoStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DisbursementStatus(str, Enum):
    REQUESTED = "REQUESTED"
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class GuarantySaleStatus(str, Enum):
    OFFERED = "OFFERED"
    SETTLED = "SETTLED"
    REPURCHASED = "REPURCHASED"


class ServicingReportStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class LiquidationStatus(str, Enum):
    OPEN = "OPEN"
    SETTLED = "SETTLED"


class GuarantyPurchaseStatus(str, Enum):
    FILED = "FILED"
    PAID = "PAID"
    DENIED = "DENIED"


class LenderProgram(str, Enum):
    SEVEN_A = "7A"
    FIVE_OH_FOUR = "504"


class UseCategory(str, Enum):
    WORKING_CAPITAL = "WORKING_CAPITAL"
    EQUIPMENT = "EQUIPMENT"
    REAL_ESTATE = "REAL_ESTATE"
    REFINANCE = "REFINANCE"
    INVENTORY = "INVENTORY"
    GOODWILL = "GOODWILL"


class AssetType(str, Enum):
    REAL_ESTATE = "REAL_ESTATE"
    EQUIPMENT = "EQUIPMENT"
    INVENTORY = "INVENTORY"
    RECEIVABLES = "RECEIVABLES"


# --- Entity TypedDicts (all common_fields: true — carry id, created_at, updated_at, version) ---
class Lender(TypedDict):
    id: str
    name: str
    program: str
    ongoing_fee_pool_cents: int
    sold_guaranty_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Borrower(TypedDict):
    id: str
    lender_id: str
    legal_name: str
    naics_code: str
    tangible_net_worth_cents: int
    avg_net_income_cents: int
    affiliate_employee_count: int
    is_eligible_business_type: bool
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    borrower_id: str
    lender_id: str
    requested_amount_cents: int
    guaranty_pct: float
    maturity_months: int
    size_eligible: bool
    guaranteed_amount_cents: int
    guaranty_fee_cents: int
    disbursed_amount_cents: int
    outstanding_principal_cents: int
    sold_guaranteed_principal_cents: int
    status: str
    servicing_status: str
    guaranty_status: str
    created_at: str
    updated_at: str
    version: int


class ProceedsLineItem(TypedDict):
    id: str
    application_id: str
    use_category: str
    amount_cents: int
    is_fixed_asset: bool
    created_at: str
    updated_at: str
    version: int


class CollateralItem(TypedDict):
    id: str
    application_id: str
    asset_type: str
    appraised_value_cents: int
    prior_lien_cents: int
    discounted_value_cents: int
    created_at: str
    updated_at: str
    version: int


class FormPackage(TypedDict):
    id: str
    application_id: str
    form_1919_complete: bool
    form_1920_complete: bool
    character_cleared: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CreditMemo(TypedDict):
    id: str
    application_id: str
    authored_by_user_id: str
    dscr: float
    risk_rating: int
    recommendation: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict):
    id: str
    application_id: str
    amount_cents: int
    tranche_label: str
    draw_window_start_day: int
    draw_window_end_day: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GuarantySale(TypedDict):
    id: str
    application_id: str
    lender_id: str
    investor_user_id: str
    sold_principal_cents: int
    premium_bps: int
    premium_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServicingReport(TypedDict):
    id: str
    application_id: str
    period_index: int
    period_start_month: int
    period_end_month: int
    principal_paid_cents: int
    interest_paid_cents: int
    days_past_due: int
    ongoing_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LiquidationEvent(TypedDict):
    id: str
    application_id: str
    recovery_cents: int
    expense_cents: int
    sba_share_cents: int
    lender_share_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GuarantyPurchase(TypedDict):
    id: str
    application_id: str
    requested_by_user_id: str
    claimed_principal_cents: int
    repair_pct: float
    approved_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
