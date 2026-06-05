"""Domain thresholds — numeric constants drawn from the PRD's pricing,
loyalty, and settlement rules. Generic NON_EXISTENT_UUID comes from the framework.
"""

# Pricing profile multipliers (Section 2.8 / 3.4).
PROFILE_MULT = {"STANDARD": 1.00, "MATINEE": 0.70, "PEAK": 1.30}

# Seat-class flat surcharge in cents (Section 3.2).
CLASS_SURCHARGE = {"STANDARD": 0, "PREMIUM": 400, "ACCESSIBLE": 0}

# MATINEE profile only valid when local start hour < 17 (Section 2.8).
MATINEE_CUTOFF_HOUR = 17

# A held order/ticket auto-expires this many minutes after creation (Section 3.4 / 3.6).
HOLD_TTL_MINUTES = 15

# Showtime ends_at = starts_at + runtime_minutes + this pad (Section 3.2).
TRAILER_PAD_MINUTES = 15

# Loyalty: 1 point per this many cents of ticket subtotal (Section 3.3).
POINTS_PER_CENT_DIVISOR = 100

# Tier breakpoints (>= semantics) (Section 3.3).
TIER_THRESHOLDS = {"SILVER": 50, "GOLD": 200}

# Fixed distributor cut on a RENTAL settlement (Section 3.9).
RENTAL_HOUSE_DISTRIBUTOR_PCT = 0.10
