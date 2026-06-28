"""Platform-wide constants (from SCAFFOLD calculations + PRD §3)."""

# Roles (PRD §2.1)
ROLES = {"PlatformAdmin", "ReviewAgent", "FinanceAdmin", "Member"}

# Auth header names (PRD §2.1)
HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

# Pagination (PRD §2.3 / response_envelope.pagination_defaults)
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# reward_amount_computation
RATE_CAP_BPS = 5000  # 50.00% hard cap on the combined online rate

# cashout_payout_and_fee
CHECK_FEE_CENTS = 200
SMALL_CASHOUT_FEE_BPS = 200       # 2.00%
LARGE_CASHOUT_CENTS = 5000        # $50.00; at/above this PayPal & gift card are fee-free

# streak_bonus_computation
STREAK_BASE_CENTS = 25
STREAK_GROWTH = 0.5               # each additional consecutive week adds 50% of base

# cashout_threshold_eligibility (per-method minimums)
MIN_PAYPAL_CENTS = 500           # $5.00
MIN_CHECK_CENTS = 2500           # $25.00
MIN_GIFT_CARD_CENTS = 1000       # $10.00

# Double-dip window (PRD §3.4)
DOUBLE_DIP_WINDOW_HOURS = 24

# Platform-wide claim/referral windows (PRD §3.5 / §3.7 — fixed numbers of days).
# Concrete values are not pinned in the PRD/scaffold prose; chosen here.
AVAILABLE_EXPIRY_DAYS = 90
REFERRAL_EXPIRY_DAYS = 30

# Week epoch: Monday 1970-01-05 UTC (streak_bonus_computation)
WEEK_EPOCH_ISO = "1970-01-05T00:00:00Z"

# Enum value sets
MERCHANT_STATUSES = {"ACTIVE", "DISABLED"}
OFFER_TYPES = {"LINKED", "RECEIPT_REBATE"}
OFFER_STATUSES = {"ACTIVE", "EXPIRED"}
ACCOUNT_STATUSES = {"ACTIVE", "SUSPENDED"}
VERIFICATION_STATUSES = {"UNVERIFIED", "VERIFIED"}
RECEIPT_STATUSES = {"SUBMITTED", "IN_REVIEW", "APPROVED", "REJECTED"}
CLAIM_STATUSES = {"PENDING", "AVAILABLE", "RESERVED", "PAID", "CLAWED_BACK", "EXPIRED"}
ATTRIBUTIONS = {"ONLINE", "IN_STORE"}
CASHOUT_METHODS = {"PAYPAL", "CHECK", "GIFT_CARD"}
CASHOUT_STATUSES = {"REQUESTED", "PROCESSING", "PAID", "FAILED"}
REFERRAL_STATUSES = {"INVITED", "SIGNED_UP", "QUALIFIED", "REWARDED", "EXPIRED"}
LEDGER_ENTRY_TYPES = {
    "CLAIM_PENDING", "CLAIM_MATURED", "CLAIM_CLAWBACK", "CLAIM_EXPIRED",
    "CASHOUT_DEBIT", "CASHOUT_REVERSAL", "REFERRAL_BONUS", "STREAK_BONUS",
}

CLAIM_TERMINAL_STATES = {"PAID", "CLAWED_BACK", "EXPIRED"}
