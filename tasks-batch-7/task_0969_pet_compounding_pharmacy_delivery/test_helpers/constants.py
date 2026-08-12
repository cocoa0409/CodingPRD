"""Domain thresholds — numeric constants from PRD §3 calculations."""

# PRD §3.4 weight-tier multiplier table (tier lower bounds inclusive)
WEIGHT_TIERS = [
    (0.0, 1.00),    # under 5 kg
    (5.0, 1.15),    # 5 up to but not including 15
    (15.0, 1.30),   # 15 up to but not including 30
    (30.0, 1.50),   # 30 kg and above
]

# PRD §3.4/§3.5 compound pricing
CONTROLLED_SURCHARGE_CENTS = 1500
WASTE_SHRINK_PCT = 0.03

# PRD §3.4 refill timing
REFILL_ELIGIBILITY_PCT = 0.75

# PRD §3.7 shipping fee
SHIPPING_BASE_CENTS = {"STANDARD": 500, "EXPRESS": 900, "OVERNIGHT": 1500}
COLD_CHAIN_SURCHARGE_CENTS = 1200
ICE_PACK_PER_24H_CENTS = 300
ZONE_TRANSIT_HOURS = {"Z1": 24, "Z2": 48, "Z3": 72}
SHIPPING_FEE_CAP_CENTS = 3500

# PRD §3.7 cold-chain excursion
EXCURSION_BREACH_MINUTES = 30

# PRD §3.7 cooler reconditioning
COOLER_CONDITIONING_HOURS = 2

# PRD §3.6 wellness credit cap (one half of the post-discount amount)
MAX_CREDIT_SHARE = 0.5

# PRD §3.3 prescription validity horizons (days)
NON_CONTROLLED_EXPIRATION_DAYS = 365
CONTROLLED_EXPIRATION_DAYS = 180

# PRD §2.5 logical clock startup default
DEFAULT_CLOCK = "2026-05-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-05-01"
