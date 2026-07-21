"""Domain thresholds and defaults from the PRD's calculation and scheduling rules."""

# --- Pricing / settlement constants (PRD §3.3, §3.5, §2.7) ---
FRESHNESS_MARKDOWN_THRESHOLD = 70      # sensory score strictly below this triggers markdown
FRESHNESS_MARKDOWN_PCT = 0.15          # 15% markdown -> price at 85%
GIFT_SET_DISCOUNT_PCT = 0.10           # 10% gift-set discount -> component priced at 90%
FREE_SHIP_THRESHOLD_CENTS = 7500       # discounted subtotal at/above this ships free
FLAT_SHIP_CENTS = 995                  # flat shipping otherwise
TIER_PCT = {"NONE": 0.0, "TIER_1": 0.10, "TIER_2": 0.20, "TIER_3": 0.30}

# --- Freshness decay (PRD §3.2) ---
OPEN_DECAY_PER_DAY = 2.5               # sensory points lost per day open

# --- Loyalty (PRD §3.5) ---
POINTS_PER_DOLLAR = 1

# --- Tasting bar scheduling (PRD §3.9) ---
BUFFER_MINUTES = 15                    # station buffer window; collision when gap strictly < 15

# --- Logical clock (PRD §2.5) ---
DEFAULT_CLOCK_UTC = "2026-07-01T00:00:00Z"

# Pagination defaults (PRD §2.3)
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
