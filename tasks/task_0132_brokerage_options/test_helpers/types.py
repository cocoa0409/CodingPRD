"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 common-fields split:

- Customer, Account, OptionsApproval, Order, ACATTransfer all carry id +
  created_at + updated_at + version. (PRD §2.4: "Every resource governed
  by this API exposes an id ... Most resources also carry three
  additional system-managed fields: created_at ... updated_at ... and
  version.")

- KYCSubmission and DayTrade are append-only audit rows: they carry only
  id and created_at. (PRD §2.4: "Two of the entities — KYCSubmission and
  DayTrade — are append-only audit rows: they carry only id and
  created_at. Both updated_at and version are absent from those two
  resource shapes, and clients must not supply them in any payload that
  touches those entities.")
"""
from __future__ import annotations

from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Customer — PRD §3.1
# ---------------------------------------------------------------------------
class KycStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# Account — PRD §3.1, §3.4, §3.5
# ---------------------------------------------------------------------------
class AccountType(str, Enum):
    CASH = "CASH"
    MARGIN_REG_T = "MARGIN_REG_T"
    MARGIN_PMA = "MARGIN_PMA"


class AccountStatus(str, Enum):
    PENDING_KYC = "PENDING_KYC"
    KYC_REVIEW = "KYC_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"


class TradingPosture(str, Enum):
    RESTRICTED = "RESTRICTED"
    OPEN = "OPEN"
    PDT_FROZEN = "PDT_FROZEN"
    TRANSFER_LOCKED = "TRANSFER_LOCKED"


# ---------------------------------------------------------------------------
# KYCSubmission — PRD §3.1
# ---------------------------------------------------------------------------
class GovernmentIdType(str, Enum):
    PASSPORT = "PASSPORT"
    DRIVERS_LICENSE = "DRIVERS_LICENSE"
    STATE_ID = "STATE_ID"


class KycSubmissionStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# OptionsApproval — PRD §3.2
# ---------------------------------------------------------------------------
class OptionsApprovalStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"


# ---------------------------------------------------------------------------
# Order — PRD §3.3
# ---------------------------------------------------------------------------
class InstrumentType(str, Enum):
    EQUITY = "EQUITY"
    OPTION = "OPTION"


class OptionStrategy(str, Enum):
    COVERED_CALL = "COVERED_CALL"
    CASH_SECURED_PUT = "CASH_SECURED_PUT"
    LONG_CALL = "LONG_CALL"
    LONG_PUT = "LONG_PUT"
    SPREAD = "SPREAD"
    NAKED_CALL = "NAKED_CALL"
    NAKED_PUT = "NAKED_PUT"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"
    TAKE_PROFIT = "TAKE_PROFIT"


class OrderStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    WORKING = "WORKING"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# ACATTransfer — PRD §3.5
# ---------------------------------------------------------------------------
class TransferDirection(str, Enum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class TransferStatus(str, Enum):
    INITIATED = "INITIATED"
    VALIDATED = "VALIDATED"
    IN_TRANSIT = "IN_TRANSIT"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


# ===========================================================================
# Top-level entities (common_fields: true) — PRD §2.4
# Carry id + created_at + updated_at + version.
# ===========================================================================
class Customer(TypedDict, total=False):
    id: str
    legal_name: str
    date_of_birth: str
    ssn_last4: str
    annual_income_cents: int
    liquid_net_worth_cents: int
    total_net_worth_cents: int
    years_options_experience: int
    kyc_status: str
    w9_collected: bool
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict, total=False):
    id: str
    customer_id: str
    account_type: str
    status: str
    trading_posture: str
    options_level: int
    cash_balance_cents: int
    equity_value_cents: int
    pdt_flag: bool
    pdt_flagged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OptionsApproval(TypedDict, total=False):
    id: str
    account_id: str
    requested_level: int
    status: str
    approved_level: Optional[int]
    review_notes: Optional[str]
    revision_count: int
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    account_id: str
    symbol: str
    instrument_type: str
    option_strategy: Optional[str]
    side: str
    order_type: str
    quantity: int
    limit_price_cents: Optional[int]
    stop_price_cents: Optional[int]
    status: str
    fill_price_cents: Optional[int]
    filled_at: Optional[str]
    opened_for_day_trade: bool
    margin_requirement_cents: int
    created_at: str
    updated_at: str
    version: int


class ACATTransfer(TypedDict, total=False):
    id: str
    account_id: str
    direction: str
    counterparty_brokerage: str
    counterparty_account_number: str
    requested_value_cents: int
    status: str
    initiated_at: str
    expected_completion_at: Optional[str]
    completed_at: Optional[str]
    business_days_elapsed: int
    created_at: str
    updated_at: str
    version: int


# ===========================================================================
# Append-only audit rows — PRD §2.4: carry ONLY id + created_at.
# NO updated_at, NO version.
# ===========================================================================
class KYCSubmission(TypedDict, total=False):
    id: str
    customer_id: str
    government_id_type: str
    government_id_number: str
    address_line1: str
    address_country: str
    w9_signed_name: str
    status: str
    rejection_reason: Optional[str]
    created_at: str
    # NO updated_at, NO version — PRD §2.4


class DayTrade(TypedDict, total=False):
    id: str
    account_id: str
    symbol: str
    opening_order_id: str
    closing_order_id: str
    trade_date: str
    created_at: str
    # NO updated_at, NO version — PRD §2.4


__all__ = [
    "UserRole",
    "KycStatus",
    "AccountType",
    "AccountStatus",
    "TradingPosture",
    "GovernmentIdType",
    "KycSubmissionStatus",
    "OptionsApprovalStatus",
    "InstrumentType",
    "OptionStrategy",
    "OrderSide",
    "OrderType",
    "OrderStatus",
    "TransferDirection",
    "TransferStatus",
    "Customer",
    "Account",
    "OptionsApproval",
    "Order",
    "ACATTransfer",
    "KYCSubmission",
    "DayTrade",
]
