"""Domain thresholds — numeric constants from PRD rules.

All values are stated in PRD prose: the 1000 kWh-per-REC minting ratio
(§3.3), the 30-day attestation window (§3.2), the 5-day settlement window
(§3.4), the three-strike account suspension threshold (§3.4), the broker
fee basis-point tiers (§3.4), and the program input defaults (§3.5).
"""

# PRD §2.4: logical clock startup value.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# PRD §3.3: "One thousand kilowatt-hours make one REC".
KWH_PER_REC = 1000

# PRD §3.2: attestation permitted "no later than thirty days after period_end".
ATTESTATION_WINDOW_DAYS = 30

# PRD §3.4: "fixes the settlement_deadline exactly five days later".
SETTLEMENT_WINDOW_DAYS = 5

# PRD §3.4: "the moment an account's failure_strikes reaches three".
STRIKE_LIMIT = 3

# PRD §3.4 broker-fee tiers (basis points by line quantity in MWh).
FEE_BPS_SMALL = 50       # line < 100 MWh
FEE_BPS_MEDIUM = 35      # 100 <= line < 1000 MWh
FEE_BPS_LARGE = 20       # line >= 1000 MWh
FEE_TIER_MEDIUM_THRESHOLD = 100
FEE_TIER_LARGE_THRESHOLD = 1000

# PRD §3.5 program input defaults.
DEFAULT_VINTAGE_WINDOW_MONTHS = 12
DEFAULT_KWH_PER_KW_MONTHLY = 100

# PRD §3.8: penalty rate default "5000 cents per megawatt-hour".
DEFAULT_PENALTY_RATE_CENTS_PER_MWH = 5000

# Standard metered period used across tests: July 2026, whose period_end
# coincides exactly with the startup clock (allowed — not later than now).
JULY_PERIOD_START = "2026-07-01T00:00:00Z"
JULY_PERIOD_END = "2026-08-01T00:00:00Z"
