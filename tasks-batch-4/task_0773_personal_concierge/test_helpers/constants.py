"""Domain thresholds — numeric constants from PRD calculations (§3.3, §3.5, §3.6, §3.8)."""

# Overage tier multiplier applied to the base overage_rate_cents_per_hour (§3.5).
TIER_OVERAGE_MULT = {
    "STANDARD": 1.00,
    "SILVER": 0.95,
    "GOLD": 0.90,
    "PLATINUM": 0.85,
}

# Priority score weights (§3.3).
TIER_WEIGHT = {"STANDARD": 1, "SILVER": 2, "GOLD": 3, "PLATINUM": 5}
CATEGORY_WEIGHT = {"ERRAND": 0, "BOOKING": 1, "GIFT": 2, "TRAVEL": 3}
RUSH_BONUS = 2

# Satisfaction current-standing window (§3.8): the three most recent ratings.
CURRENT_STANDING_WINDOW = 3

# Vendor buffer in minutes between committed engagements of the same vendor (§3.6).
VENDOR_BUFFER_MINUTES = 30

# Default vendor markup fraction when omitted on plan create (§3.1).
DEFAULT_MARKUP_PCT = 0.15

# Minutes per hour, used to derive included_minutes from included_hours (§3.2).
MINUTES_PER_HOUR = 60
