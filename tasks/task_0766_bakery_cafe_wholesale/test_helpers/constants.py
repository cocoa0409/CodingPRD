"""Domain thresholds and pricing constants drawn from the PRD's calculation rules."""

# Markdown pricing (PRD 3.4)
MARKDOWN_WINDOW_HOURS = 8      # markdown eligible only when 0 < hours_to_expiry <= 8
MID_TIER_HOURS = 4            # > 4 hours => MID_DISCOUNT; <= 4 hours => LATE_DISCOUNT
MID_DISCOUNT = 0.25
LATE_DISCOUNT = 0.50
SURPLUS_RATIO = 0.5          # remaining_qty / baked_qty >= 0.5 adds the surplus bonus
SURPLUS_BONUS = 0.15
MAX_DISCOUNT = 0.60

# Wholesale contract pricing (PRD 3.6)
STANDARD_DISCOUNT = 0.10
PREMIUM_DISCOUNT = 0.15
BULK_DISCOUNT = 0.20
BULK_MIN_QTY = 24           # qty >= 24 raises the discount to at least the bulk rate

# Oven scheduling default (PRD 3.1)
DEFAULT_CLEAN_BUFFER_MINUTES = 15

# Standing-order default (PRD 3.6)
DEFAULT_CUTOFF_HOURS = 24

# Logical clock startup default (PRD 2.5)
CLOCK_DEFAULT = "2026-03-01T00:00:00Z"

# Pagination (PRD 2.3)
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
