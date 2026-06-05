"""Domain types: entity TypedDicts, status enums, role enum.

All field names are PRD-exact (PRD §3). PointsLot is the only entity that does
NOT carry the common quartet — per PRD §2.4 it carries only `id` and
`created_at` (no `updated_at`, no `version`).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Roles (PRD §2.1) ───────────────────────────────────────────
class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    CARDHOLDER = "Cardholder"
    REWARDS_OPS = "RewardsOps"


# ─── Status enums (PRD §3) ──────────────────────────────────────
class CardProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class CashbackCategoryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class TransferPartnerType(str, Enum):
    AIRLINE = "AIRLINE"
    HOTEL = "HOTEL"


class TransferPartnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CardAccountStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class SignupBonusStatus(str, Enum):
    NOT_QUALIFIED = "NOT_QUALIFIED"
    EARNED = "EARNED"
    EXPIRED_UNQUALIFIED = "EXPIRED_UNQUALIFIED"


class TransactionStatus(str, Enum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    DECLINED = "DECLINED"
    REFUNDED = "REFUNDED"


class PointsLotType(str, Enum):
    EARN = "EARN"
    SIGNUP_BONUS = "SIGNUP_BONUS"


class PointsLotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"
    CLAWED_BACK = "CLAWED_BACK"


class RedemptionType(str, Enum):
    STATEMENT_CREDIT = "STATEMENT_CREDIT"
    POINTS_TRANSFER = "POINTS_TRANSFER"


class RedemptionStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    REVERSED = "REVERSED"


class CategoryActivationStatus(str, Enum):
    ACTIVE = "ACTIVE"


# ─── Entity TypedDicts (common_fields: true) ────────────────────
class CardProduct(TypedDict):
    id: str
    name: str
    base_earn_rate_bps: int
    signup_bonus_points: int
    signup_bonus_spend_threshold_cents: int
    signup_bonus_window_days: int
    tier_thresholds: list
    points_expiry_months: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CashbackCategory(TypedDict):
    id: str
    card_product_id: str
    code: str
    earn_multiplier_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class QuarterlyCategory(TypedDict):
    id: str
    card_product_id: str
    code: str
    quarter_label: str
    window_start: str
    window_end: str
    earn_multiplier_bps: int
    bonus_cap_cents: int
    created_at: str
    updated_at: str
    version: int


class TransferPartner(TypedDict):
    id: str
    name: str
    partner_type: str
    transfer_ratio_num: int
    transfer_ratio_den: int
    min_transfer_points: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CardAccount(TypedDict):
    id: str
    card_product_id: str
    cardholder_name: str
    opened_at: str
    points_balance: int
    pending_points: int
    qualifying_spend_cents: int
    annual_spend_cents: int
    current_tier_index: int
    signup_bonus_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Transaction(TypedDict):
    id: str
    card_account_id: str
    amount_cents: int
    category_code: str
    transacted_at: str
    earned_points: int
    quarterly_bonus_applied_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Redemption(TypedDict):
    id: str
    card_account_id: str
    redemption_type: str
    points_requested: int
    transfer_partner_id: Optional[str]
    expected_card_account_version: int
    redeemed_value: int
    lots_consumed: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class CategoryActivation(TypedDict):
    id: str
    card_account_id: str
    quarterly_category_id: str
    activated_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Append-only entity (common_fields: false) — PRD §2.4 ───────
# PointsLot carries ONLY id + created_at (no updated_at, no version).
class PointsLot(TypedDict):
    id: str
    card_account_id: str
    source_transaction_id: Optional[str]
    lot_type: str
    original_points: int
    remaining_points: int
    expires_at: str
    status: str
    created_at: str
