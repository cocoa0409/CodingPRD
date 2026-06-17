"""Domain thresholds — numeric constants from PRD calculations (PRD §2.6, §3.3-§3.9)."""

# --- Pricing engine (PRD §3.3) ---
DEMAND_SLOPE = 0.50            # demand_mult = 1.0 + 0.50 * sold_ratio
DEFAULT_PRICE_CAP_MULTIPLIER = 3.0   # PRD §3.1 — default when omitted
DEFAULT_LAST_MINUTE_CUTOFF_MINUTES = 180   # PRD §3.1 — default when omitted

# --- Buyer charge (PRD §3.4) ---
BUYER_FEE_RATE = 0.12         # buyer_fee_cents = floor(base * 0.12)

# --- Seller commission by trust tier (PRD §3.5) ---
SELLER_FEE_RATES = {
    "NEW": 0.15,
    "VERIFIED": 0.12,
    "TRUSTED": 0.10,
    "RESTRICTED": 0.20,
}

# --- Event credit goodwill bonus (PRD §3.9) ---
LOYALTY_THRESHOLD = 3         # lifetime_orders_count >= 3 earns the bonus
BONUS_MULTIPLIER = 1.10       # 110% goodwill credit

# --- Transfer deadlines (PRD §3.6) ---
STANDARD_WINDOW_MINUTES = 1440    # one full day
LAST_MINUTE_WINDOW_MINUTES = 30   # compressed last-minute window

# --- Fraud severity (PRD §3.8) ---
GOUGE_RATIO = 2.5             # PRICE_GOUGE HIGH band = floor(face * 2.5)

# --- Pagination defaults (PRD §2.3) ---
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100
PAGINATION_MIN_LIMIT = 1

# --- Canonical FIXED-listing fixture values (used widely in design recipes) ---
# Section face_value_cents=10000, Event price_cap_multiplier=3.0 (cap=30000),
# Listing ask_price_cents=20000, FIXED -> effective_price_cents=20000.
CANON_FACE_VALUE_CENTS = 10000
CANON_CAP_MULTIPLIER = 3.0
CANON_CAP_CENTS = 30000
CANON_ASK_PRICE_CENTS = 20000
CANON_EFFECTIVE_PRICE_CENTS = 20000

# Derived canonical buyer-charge figures for a qty=2 FIXED order, no credit:
#   base  = 2 * 20000 = 40000
#   fee   = floor(40000 * 0.12) = 4800
#   final = 40000 + 4800 = 44800
CANON_QTY2_BASE_CENTS = 40000
CANON_QTY2_FEE_CENTS = 4800
CANON_QTY2_FINAL_CENTS = 44800
# qty=1 final = floor(20000*0.12)=2400 ; final = 20000+2400 = 22400
CANON_QTY1_FINAL_CENTS = 22400

# Seller commission for a NEW-tier qty=2 sale (gross 40000):
#   seller_fee = floor(40000 * 0.15) = 6000 ; net = 40000 - 6000 = 34000
CANON_QTY2_NET_NEW_CENTS = 34000
