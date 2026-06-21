"""Domain thresholds — numeric constants from the PRD's pricing, duration,
strike, and routing rules (§3.3-§3.9). Generic NON_EXISTENT_UUID comes from
the framework.
"""

# Duration estimate (PRD §3.3 "Duration estimate")
HEAVY_LBS_THRESHOLD = 60          # weight_lbs > 60 triggers the size surcharge/loading
HEAVY_SURCHARGE_MIN = 20          # minutes added when heavy
MATTED_DEMAT_MIN = 25            # de-matting minutes when coat MATTED

# Pricing loadings (PRD §3.3 / §3.5)
MATTED_PRICE_PCT = 0.30          # coat loading = 30% of tier base
HEAVY_PRICE_PCT = 0.15          # size loading = 15% of tier base

# No-show fee (PRD §3.5 "No-show fee")
NO_SHOW_PCT = 0.50              # base = 50% of quoted_price_cents
REPEAT_STRIKE_THRESHOLD = 2     # prior strikes >= 2 adds the repeat penalty
REPEAT_PENALTY_CENTS = 1500     # flat repeat penalty
NO_SHOW_FEE_CAP_CENTS = 8000    # fee capped to this

# Late-cancel fee (PRD §3.5)
LATE_CANCEL_HOURS = 24          # >= 24h out is NOT late (inclusive boundary)
LATE_CANCEL_FLAT_CENTS = 2500   # flat late-cancel fee

# Strike accounting (PRD §3.9 "Strike accounting")
STRIKE_SUSPEND_THRESHOLD = 3    # no_show_strikes >= 3 suspends the account
STRIKE_WINDOW_DAYS = 90         # rolling window

# Route load / overlap (PRD §3.4)
TRAVEL_BUFFER_MIN = 15          # per-stop travel buffer (both ends for overlap; one per stop for load)

# A syntactically valid UUID guaranteed not to resolve to any entity.
NONEXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
