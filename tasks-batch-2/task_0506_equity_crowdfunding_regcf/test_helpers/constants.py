"""Domain thresholds — numeric constants from the PRD's calculations and time rules."""

# Investor annual-limit thresholds (PRD §3.4)
ANNUAL_LIMIT_FLOOR_CENTS = 250_000        # $2,500 floor
ANNUAL_LIMIT_CAP_CENTS = 12_400_000       # $124,000 cap / both-above-cap threshold

# Trailing investment window (PRD §3.4)
TRAILING_WINDOW_DAYS = 365

# Platform fee on a close (PRD §3.6)
FEE_BPS = 750                             # 7.5% in basis points

# Per-issuer 12-month Reg CF proceeds cap (PRD §3.7)
ISSUER_CAP_CENTS = 500_000_000            # $5,000,000

# Investor-update quiet period (PRD §3.8)
QUIET_PERIOD_HOURS = 24

# Logical clock default boot instant (PRD §2.9)
CLOCK_DEFAULT = "2026-01-01T00:00:00Z"

# Convenient large income/net-worth values that force ACCREDITED-eligible status
# (also far above the unaccredited annual limit, used for whale / accredited investors).
BIG_INCOME_CENTS = 100_000_000
BIG_NET_WORTH_CENTS = 100_000_000
