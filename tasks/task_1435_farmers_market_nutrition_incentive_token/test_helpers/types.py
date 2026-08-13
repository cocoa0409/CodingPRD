"""Domain types: entity TypedDicts, status enums, role enum.

All eleven primary resources carry the common system-managed fields
(id, created_at, updated_at, version) per PRD "Common Resource Properties".
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    MARKET_MANAGER = "MarketManager"
    BOOTH_OPERATOR = "BoothOperator"
    VENDOR = "Vendor"
    AUDITOR = "Auditor"
    SHOPPER = "Shopper"


class BenefitType(str, Enum):
    SNAP = "SNAP"
    WIC = "WIC"
    SENIOR = "SENIOR"


class VendorStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ShopperStatus(str, Enum):
    ENROLLED = "ENROLLED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class MarketDayStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    VARIANCE_FLAGGED = "VARIANCE_FLAGGED"
    RECONCILED = "RECONCILED"


class TokenBatchStatus(str, Enum):
    SEALED = "SEALED"
    ACTIVE = "ACTIVE"
    RECALLED = "RECALLED"


class TokenKind(str, Enum):
    BASE = "BASE"
    MATCH = "MATCH"


class IssuanceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class TokenStatus(str, Enum):
    ISSUED = "ISSUED"
    REDEEMED = "REDEEMED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"
    FLAGGED = "FLAGGED"
    CONFISCATED = "CONFISCATED"


class SubmissionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAID = "PAID"


class FraudCaseOrigin(str, Enum):
    MANUAL = "MANUAL"
    AUTO_DOUBLE_SPEND = "AUTO_DOUBLE_SPEND"
    AUTO_COUNTERFEIT_SERIAL = "AUTO_COUNTERFEIT_SERIAL"


class FraudCaseStatus(str, Enum):
    OPEN = "OPEN"
    CONFIRMED = "CONFIRMED"
    CLEARED = "CLEARED"


class Program(TypedDict, total=False):
    id: str
    name: str
    season_start: str
    season_end: str
    match_pool_budget_cents: int
    match_pool_remaining_cents: int
    liability_forward_cents: int
    liability_realized_cents: int
    paid_out_cents: int
    created_at: str
    updated_at: str
    version: int


class Market(TypedDict, total=False):
    id: str
    program_id: str
    name: str
    city: str
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict, total=False):
    id: str
    market_id: str
    legal_name: str
    stall_number: str
    status: str
    payable_cents: int
    created_at: str
    updated_at: str
    version: int


class Shopper(TypedDict, total=False):
    id: str
    program_id: str
    external_benefit_ref: str
    benefit_type: str
    status: str
    season_match_used_cents: int
    created_at: str
    updated_at: str
    version: int


class MarketDay(TypedDict, total=False):
    id: str
    market_id: str
    date: str
    opens_at: str
    closes_at: str
    status: str
    issued_value_cents: int
    voided_value_cents: int
    redeemed_value_cents: int
    variance_cents: int
    created_at: str
    updated_at: str
    version: int


class TokenBatch(TypedDict, total=False):
    id: str
    market_id: str
    kind: str
    denomination_cents: int
    serial_start: int
    serial_end: int
    status: str
    next_serial: int
    created_at: str
    updated_at: str
    version: int


class Issuance(TypedDict, total=False):
    id: str
    shopper_id: str
    market_day_id: str
    benefit_charged_cents: int
    base_value_cents: int
    match_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Token(TypedDict, total=False):
    id: str
    serial_number: int
    kind: str
    denomination_cents: int
    issuance_id: str
    token_batch_id: str
    status: str
    redeemed_vendor_id: Optional[str]
    submission_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RedemptionSubmission(TypedDict, total=False):
    id: str
    vendor_id: str
    market_day_id: str
    token_ids: List[str]
    status: str
    provisional_amount_cents: int
    approved_amount_cents: Optional[int]
    paid_amount_cents: Optional[int]
    approved_at: Optional[str]
    disputed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FraudCase(TypedDict, total=False):
    id: str
    vendor_id: Optional[str]
    shopper_id: Optional[str]
    token_id: Optional[str]
    reason: str
    origin: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SettlementRun(TypedDict, total=False):
    id: str
    program_id: str
    cutoff_at: str
    swept_submission_ids: List[str]
    total_paid_cents: int
    vendor_payment_count: int
    created_at: str
    updated_at: str
    version: int
