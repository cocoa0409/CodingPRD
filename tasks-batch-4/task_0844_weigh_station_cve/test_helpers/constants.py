"""Domain thresholds — numeric constants from the PRD's business rules."""

# Carrier status-propagation thresholds (PRD §2.7)
ISS_REVIEW_THRESHOLD = 10          # iss_score >= 10 -> ACTIVE -> UNDER_REVIEW
OOS_ORDER_THRESHOLD = 20           # oos_points >= 20 -> carrier -> OOS_ORDERED

# Fiscal thresholds (PRD §2.7, §3.7)
FINE_HOLD_THRESHOLD_CENTS = 100000  # unpaid crossing $1000 upward -> registration_hold
FINE_CAP_CENTS = 200000             # unpaid + assessed >= $2000 at issuance -> ERR_FINE_CAP_EXCEEDED

# Overweight tiered-fine rates, marginal cents-per-pound (PRD §3.7)
OVERWEIGHT_RATE_T1_CENTS_PER_LB = 10   # first 2000 lbs
OVERWEIGHT_RATE_T2_CENTS_PER_LB = 25   # pounds 2001..5000
OVERWEIGHT_RATE_T3_CENTS_PER_LB = 50   # pounds 5001+

# Flat fine schedule by citation kind (PRD §3.7)
FLAT_FINE_CENTS = {
    "CREDENTIAL": 25000,
    "HAZMAT": 100000,
    "HOS": 50000,
    "EQUIPMENT": 15000,
}

# ISS scoring (PRD §3.6)
ISS_OOS_MULT = 1.5
ISS_WINDOW_N = 5

# Hours-of-service (PRD §3.2)
HOS_DRIVING_LIMIT_MIN = 660   # strict '>' — exactly 660 is allowed
HOS_RESET_MIN = 600           # qualifying OFF_DUTY reset / off-duty buffer

# Weigh-station defaults (PRD §3.1)
DEFAULT_GROSS_WEIGHT_LIMIT_LBS = 80000
DEFAULT_SINGLE_AXLE_LIMIT_LBS = 20000
DEFAULT_ISS_BYPASS_THRESHOLD = 50


def overweight_fine_cents(gross_lbs, axle_lbs, gross_limit=DEFAULT_GROSS_WEIGHT_LIMIT_LBS,
                          axle_limit=DEFAULT_SINGLE_AXLE_LIMIT_LBS):
    """Reference tiered overweight fine (PRD §3.7): max of the bracketed gross and axle charges."""
    def tiered(excess):
        b1 = min(excess, 2000)
        b2 = min(max(excess - 2000, 0), 3000)
        b3 = max(excess - 5000, 0)
        return (b1 * OVERWEIGHT_RATE_T1_CENTS_PER_LB
                + b2 * OVERWEIGHT_RATE_T2_CENTS_PER_LB
                + b3 * OVERWEIGHT_RATE_T3_CENTS_PER_LB)
    gross_excess = max(0, gross_lbs - gross_limit)
    axle_excess = max(0, axle_lbs - axle_limit)
    return max(tiered(gross_excess), tiered(axle_excess))
