"""Domain thresholds — numeric constants from the PRD's fee and posture rules."""

INF = float("inf")

# Marginal rate schedules in cents per ton (PRD §3.4).
RATE_TIERS = {
    "MSW": [(0, 5, 4500), (5, INF, 3800)],
    "CONSTRUCTION_DEBRIS": [(0, INF, 5200)],
    "GREEN_WASTE": [(0, INF, 2000)],
    "CLEAN_WOOD": [(0, INF, 1800)],
    "TIRE": [(0, INF, 9000)],
    "ASBESTOS": [(0, INF, 15000)],
}

SPECIAL_SURCHARGE_CENTS = {"TIRE": 5000, "ASBESTOS": 20000}
DIVERTED_MATERIALS = {"GREEN_WASTE", "CLEAN_WOOD"}

MINIMUM_FEE_CENTS = 2500
GAS_SURCHARGE_MULT = 1.10
DIVERSION_REBATE_PCT = 0.12

HOST_FEE_PCT = 0.0875

# Gas classification thresholds in ppm (inclusive lower bounds), PRD §2.9.
ELEVATED_PPM = 200
EXCEEDANCE_PPM = 500

# Acceptance posture RESTRICTED threshold ratio (PRD §2.9).
RESTRICTED_RATIO = 0.10

# Airspace consumed per landfilled ton (PRD §3.6).
AIRSPACE_PER_TON = 1.5
