"""Server-wide configuration constants."""
import os

PORT = int(os.environ.get("PORT", 10000))
HOST = "0.0.0.0"

# Roles recognised by the system (PRD §2.1).
ROLES = {
    "ListingAgent",
    "BuyerAgent",
    "MlsAdmin",
}

# Pagination defaults (scaffold §1.0).
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# Headers (PRD §2.1).
HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

# Agent role enum values.
AGENT_ROLE_LISTING = "LISTING_AGENT"
AGENT_ROLE_BUYER = "BUYER_AGENT"
AGENT_ROLE_DUAL = "DUAL_AGENT"

# Buyer-matching weights (scaffold calculations.buyer_match_score).
W_PRICE = "0.40"
W_LOC = "0.25"
W_BB = "0.20"
W_FEAT = "0.15"
MATCH_CUTOFF = "50.0"

# Listing lifetime (PRD §3.2 / §3.9).
LISTING_LIFETIME_DAYS = 180

# Listing field bounds (PRD §3.2).
MIN_LIST_PRICE_CENTS = 1_000_000
MAX_CO_OP_PCT = "0.06"
MAX_TOTAL_COMMISSION_PCT = "0.10"

# Showing window bounds (PRD §3.5).
MIN_SHOWING_DURATION_SEC = 15 * 60
MAX_SHOWING_DURATION_SEC = 4 * 60 * 60
