"""Domain thresholds — numeric constants from the PRD's pricing, stars, and reward rules."""

# Tax (PRD §3.5): 875 basis points = 8.75%, rounded once on post-discount base.
TAX_RATE_BPS = 875

# Star accrual rates (PRD §3.4).
GREEN_STARS_PER_DOLLAR = 1
GOLD_STARS_PER_DOLLAR = 2
STORED_VALUE_BONUS_PER_DOLLAR = 1

# Tier threshold (PRD §2.5): GOLD when lifetime_stars >= 200.
GOLD_THRESHOLD = 200

# Reward economics (PRD §3.9).
REDEEM_STAR_COST = 150                # stars to mint a FREE_ITEM reward
FREE_ITEM_MAX_DISCOUNT_CENTS = 700    # max_discount on a minted FREE_ITEM reward
FREE_ITEM_TTL_DAYS = 60               # FREE_ITEM expires_at = mint_time + 60 days
BIRTHDAY_MAX_DISCOUNT_CENTS = 700     # max_discount on a BIRTHDAY reward
BIRTHDAY_TTL_DAYS = 30                # BIRTHDAY expires_at = grant_time + 30 days

# Stored-value card defaults (PRD §3.1).
DEFAULT_AUTO_RELOAD_THRESHOLD_CENTS = 1000
DEFAULT_AUTO_RELOAD_AMOUNT_CENTS = 2500

# Pagination (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
