"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# PRD §3.4: fraction dose allocation round_half_up at integer cGy
# PRD §3.1/§3.7: BED alpha/beta ratio and repopulation parameters
ALPHA_BETA_GY = 10
REPOPULATION_K_GY_PER_DAY = 0.6
REPOPULATION_KICKOFF_DAY = 28

# PRD §3.8: adaptation weight-loss trigger
WEIGHT_LOSS_THRESHOLD_PCT = 10.0

# PRD §3.7: chart-review gate
CHART_REVIEW_FRACTION_LIMIT = 5

# PRD §3.7: fraction delivery pricing
FRACTION_DELIVERY_RATE_CENTS = {"THREE_DCRT": 18000, "IMRT": 32000, "SBRT": 55000}
IGRT_FEE_CENTS = 7500
FIRST_FRACTION_SETUP_FEE_CENTS = 12000
NO_SHOW_FEE_CENTS = 5000
SIMULATION_FEE_CENTS = 65000
PHYSICS_CHECK_FEE_CENTS = 25000

# PRD §3.5: planning charge tiers
PLANNING_BASE_CENTS = {"THREE_DCRT": 90000, "IMRT": 210000, "SBRT": 300000}
PLANNING_EXTRA_TARGET_FACTOR = 0.25
ADAPTATION_PLANNING_FACTOR = 0.5

# PRD §3.9: claim discount
DISCOUNT_TIER_THRESHOLD_CENTS = 1500000
DISCOUNT_RATE = 0.05

# PRD §3.6: LINAC turnover buffer
LINAC_TURNOVER_MINUTES = 10

# PRD §3.2: simulator daily capacity
SIM_DAILY_CAPACITY = 8

# PRD §2.8: logical clock startup default
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# PRD §2.3: pagination defaults
DEFAULT_PAGE_LIMIT = 10
