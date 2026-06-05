"""Domain thresholds — numeric constants from PRD calculations."""

# Pattern Day Trader rule (§3.9)
PDT_DAYTRADE_THRESHOLD = 4
PDT_WINDOW_BUSINESS_DAYS = 5
PDT_MIN_EQUITY_CENTS = 2_500_000          # $25,000.00

# Margin (§3.6)
PMA_INITIAL_MARGIN_RATE = 0.15
PMA_MIN_EQUITY_CENTS = 15_000_000         # $150,000.00

# Maintenance margin (§2.9)
EQUITY_MAINT_RATE = 0.25
OPTION_MAINT_RATE = 1.00

# Order notional (§3.8)
OPTION_CONTRACT_MULTIPLIER = 100

# Options suitability gate (§3.7)
LEVEL_MIN_COMBINED_CENTS = {1: 0, 2: 5_000_000, 3: 10_000_000, 4: 25_000_000}
LEVEL_MIN_EXP_RANK = {1: 0, 2: 1, 3: 2, 4: 3}
