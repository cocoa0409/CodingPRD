"""Domain thresholds — numeric constants from the PRD.

Withholding rates (PRD §3.5), indemnity-bond constants (PRD §3.4), dormancy
table (PRD §3.7), time horizons, and the logical-clock startup default
(PRD §2.4).
"""

# Logical clock (PRD §2.4): startup default before any set call.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# Dividend withholding rates (PRD §3.5).
BACKUP_WITHHOLDING_RATE = 0.24   # tin_status MISSING or UNCERTIFIED
NRA_STANDARD_RATE = 0.30         # CERTIFIED + FOREIGN + STANDARD
NRA_TREATY_RATE = 0.15           # CERTIFIED + FOREIGN + TREATY
MILLICENTS_PER_CENT = 1000

# Indemnity bond (PRD §3.4): double-indemnity basis and tiered premium.
BOND_MULTIPLIER = 2
PREMIUM_TIER1_CAP_CENTS = 10_000_000
PREMIUM_TIER1_RATE = 0.03
PREMIUM_TIER2_RATE = 0.02

# Time horizons.
STALE_DATING_DAYS = 180          # disbursed_at + 180 days -> STALE_DATED
NOTICE_WINDOW_DAYS = 60          # notice_sent_at + 60 days -> report eligible
HOLDING_PERIOD_DAYS = 180        # acquisition_date + 180 days -> Rule 144

# Dormancy table (PRD §3.7), keyed by state_code.
DORMANCY_YEARS = {"CA": 3, "NY": 5, "TX": 3}
DORMANCY_DEFAULT = 5

# Common test defaults.
DEFAULT_PRICE_CENTS = 5000
DEFAULT_LOSS_DATE = "2026-08-10T00:00:00Z"
DEFAULT_RECORD_DATE = "2026-09-01T00:00:00Z"
DEFAULT_PAYABLE_DATE = "2026-09-15T00:00:00Z"
