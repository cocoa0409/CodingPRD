"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    FIRM_ADMIN = "FirmAdmin"
    TAX_OPS = "TaxOps"
    CUSTOMER_SERVICE = "CustomerService"
    CUSTOMER = "Customer"
    AUDITOR = "Auditor"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------

class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class AccountStatus(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class AccountType(str, Enum):
    TAXABLE = "TAXABLE"
    IRA = "IRA"
    ROTH_IRA = "ROTH_IRA"


class DisposalMethod(str, Enum):
    FIFO = "FIFO"
    LIFO = "LIFO"
    HIFO = "HIFO"
    SPECIFIC_ID = "SPECIFIC_ID"


class SecurityType(str, Enum):
    EQUITY = "EQUITY"
    CORPORATE_BOND = "CORPORATE_BOND"
    OPTION = "OPTION"
    MUTUAL_FUND = "MUTUAL_FUND"


class AcquisitionKind(str, Enum):
    PURCHASE = "PURCHASE"
    GIFT = "GIFT"
    INHERITANCE = "INHERITANCE"
    TRANSFER_IN = "TRANSFER_IN"
    CORPORATE_ACTION_DERIVED = "CORPORATE_ACTION_DERIVED"


class CoveredStatus(str, Enum):
    COVERED = "COVERED"
    NONCOVERED = "NONCOVERED"


class LotStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_DISPOSED = "PARTIALLY_DISPOSED"
    FULLY_DISPOSED = "FULLY_DISPOSED"
    SUPERSEDED = "SUPERSEDED"


class DispositionStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    CORRECTED = "CORRECTED"
    VOIDED = "VOIDED"


class CorporateActionType(str, Enum):
    SPLIT = "SPLIT"
    REVERSE_SPLIT = "REVERSE_SPLIT"
    MERGER = "MERGER"
    SPINOFF = "SPINOFF"


class CorporateActionStatus(str, Enum):
    ANNOUNCED = "ANNOUNCED"
    EFFECTIVE = "EFFECTIVE"
    CANCELLED = "CANCELLED"


class TransferDirection(str, Enum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class TransferStatementStatus(str, Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class MatchingRule(str, Enum):
    SHARE_FOR_SHARE = "SHARE_FOR_SHARE"
    PARTIAL_PRORATA = "PARTIAL_PRORATA"


class TaxFormStatus(str, Enum):
    DRAFT = "DRAFT"
    GENERATED = "GENERATED"
    FILED = "FILED"
    CORRECTION_PENDING = "CORRECTION_PENDING"
    REFILED = "REFILED"
    FROZEN = "FROZEN"


class BasisRequestKind(str, Enum):
    COVERAGE_RECLASS = "COVERAGE_RECLASS"
    BASIS_AMOUNT_CORRECTION = "BASIS_AMOUNT_CORRECTION"
    ACQUISITION_DATE_CORRECTION = "ACQUISITION_DATE_CORRECTION"
    GIFT_BASIS_SUPPLY = "GIFT_BASIS_SUPPLY"


class BasisRequestStatus(str, Enum):
    PENDING = "PENDING"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    RESUBMITTED = "RESUBMITTED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — every entity carries id + created_at + updated_at +
# version (PRD §2.4 common resource properties).
# ---------------------------------------------------------------------------

class BrokerageFirm(TypedDict):
    id: str
    legal_name: str
    tax_year_open: int
    wash_sale_window_days: int
    correction_deadline_days: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    firm_id: str
    taxpayer_tin: str
    display_name: str
    status: str
    wash_sale_scope_key: str
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    firm_id: str
    customer_id: str
    account_number: str
    account_type: str
    default_disposal_method: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Security(TypedDict):
    id: str
    firm_id: str
    cusip: str
    ticker: str
    security_type: str
    covered_security_effective_date: str
    created_at: str
    updated_at: str
    version: int


class TaxLot(TypedDict):
    id: str
    firm_id: str
    account_id: str
    security_id: str
    acquisition_date: str
    quantity: float
    quantity_remaining: float
    original_cost_basis_cents: int
    adjusted_cost_basis_cents: int
    acquisition_kind: str
    holding_period_start: str
    wash_sale_taint_basis_cents: int
    covered_status: str
    lot_status: str
    created_at: str
    updated_at: str
    version: int


class Disposition(TypedDict):
    id: str
    firm_id: str
    account_id: str
    security_id: str
    trade_date: str
    settlement_date: str
    quantity: float
    proceeds_cents: int
    method: str
    status: str
    realized_gain_cents: int
    is_wash_sale_flag: bool
    wash_sale_disallowed_loss_cents: int
    created_at: str
    updated_at: str
    version: int


class CorporateAction(TypedDict):
    id: str
    firm_id: str
    security_id: str
    action_type: str
    effective_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TransferStatement(TypedDict):
    id: str
    firm_id: str
    account_id: str
    direction: str
    counterparty_firm_name: str
    security_id: str
    quantity: float
    transfer_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WashSaleEvent(TypedDict):
    id: str
    firm_id: str
    disposition_id: str
    triggering_lot_id: str
    sold_lot_id: str
    disallowed_loss_cents: int
    wash_sale_window_start: str
    wash_sale_window_end: str
    matching_rule: str
    created_at: str
    updated_at: str
    version: int


class TaxForm1099B(TypedDict):
    id: str
    firm_id: str
    customer_id: str
    tax_year: int
    status: str
    short_term_proceeds_cents: int
    short_term_basis_cents: int
    short_term_gain_cents: int
    long_term_proceeds_cents: int
    long_term_basis_cents: int
    long_term_gain_cents: int
    disallowed_wash_sale_loss_cents: int
    correction_count: int
    generated_from_version: int
    created_at: str
    updated_at: str
    version: int


class BasisChangeRequest(TypedDict):
    id: str
    firm_id: str
    customer_id: str
    tax_lot_id: str
    request_kind: str
    status: str
    approved_by_user_id: str
    applied_by_user_id: str
    version_applied_to: int
    created_at: str
    updated_at: str
    version: int
