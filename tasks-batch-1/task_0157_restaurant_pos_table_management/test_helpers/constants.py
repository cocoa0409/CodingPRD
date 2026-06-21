"""Domain thresholds and pricing-config defaults from the Restaurant POS PRD."""

# Restaurant pricing-policy defaults (PRD §3.1).
RESTAURANT_DEFAULTS = {
    "large_party_threshold": 8,   # default party size for auto-gratuity (>= 2)
    "auto_gratuity_bps": 2000,    # 20% default gratuity (cap 5000)
    "comp_cap_bps": 10000,        # 100% comp cap default (never above 10000)
    "min_rest_minutes": 0,        # no rest gap by default (never negative)
}

# Basis-points scale: 10000 bps == 100% (PRD §2.5).
BPS_DENOMINATOR = 10000

# Minutes-after-midnight upper bound (PRD §2.5).
MAX_MINUTE_OF_DAY = 1440
