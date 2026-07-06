"""Domain thresholds — numeric constants from PRD calculations (§3)."""

# Markdown pricing (§3.5): markdown price is 60% of unit price, round half up.
MARKDOWN_PCT = 0.40

# Loyalty (§3.5): one punch per full dozen; auto-convert at 10 punches into a
# 1200-cent reward.
PUNCHES_PER_REWARD = 10
REWARD_VALUE_CENTS = 1200

# Catering pre-order deposit (§3.8).
CATERING_DEPOSIT_THRESHOLD_CENTS = 4050
DEPOSIT_PCT = 0.25

# Catering slot capacity (§3.8).
CATERING_SLOT_CAPACITY = 2

# Route window buffer in minutes (§3.7).
ROUTE_BUFFER_MINUTES = 30

# Product bulk-threshold default (§3.1).
DEFAULT_BULK_THRESHOLD = 24

# Logical clock startup value (§2.10).
CLOCK_DEFAULT_UTC = "2026-03-01T00:00:00Z"
