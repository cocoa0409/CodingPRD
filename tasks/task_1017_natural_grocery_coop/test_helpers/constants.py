"""Domain thresholds — numeric constants from the PRD's pricing, patronage,
working-member, quorum, and scheduling rules (PRD §2.5, §3.3-§3.7)."""

# Pricing (PRD §3.5)
WORKING_MEMBER_DISCOUNT_PCT = 0.10  # 10% working-member discount
TAX_RATE = 0.08                      # 8% line tax on taxable products

# Patronage dividend (PRD §3.1, §3.7)
MIN_PATRONAGE_CENTS = 5000           # minimum participation threshold
RETENTION_PCT = 0.20                 # retained-to-equity fraction of a dividend

# Working-member standing (PRD §3.4)
WORKING_MEMBER_MIN_HOURS = 12        # hours qualifying a member as a working member

# Governance (PRD §3.6)
QUORUM_PCT = 0.5                     # quorum = ceil(QUORUM_PCT * eligible board count)

# Scheduling (PRD §3.4)
REST_BUFFER_MINUTES = 60            # minimum gap between a member's shifts

THRESHOLDS = {
    "WORKING_MEMBER_DISCOUNT_PCT": WORKING_MEMBER_DISCOUNT_PCT,
    "TAX_RATE": TAX_RATE,
    "MIN_PATRONAGE_CENTS": MIN_PATRONAGE_CENTS,
    "RETENTION_PCT": RETENTION_PCT,
    "WORKING_MEMBER_MIN_HOURS": WORKING_MEMBER_MIN_HOURS,
    "QUORUM_PCT": QUORUM_PCT,
    "REST_BUFFER_MINUTES": REST_BUFFER_MINUTES,
}

# The server's logical clock default at startup (PRD §2.6).
DEFAULT_CLOCK = "2026-07-01T00:00:00Z"

TEST_DEFAULTS = {
    "EQUITY_SHARE_PRICE_CENTS": 10000,
    "PATRONAGE_RATE": 0.05,
    "YEAR": 2026,
}
