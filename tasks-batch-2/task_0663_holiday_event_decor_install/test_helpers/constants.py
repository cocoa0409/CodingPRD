"""Domain thresholds — numeric constants from PRD pricing and routing rules."""

# Bundle-discount tiers for the install fee (PRD §3.3 "Install fee").
INSTALL_BUNDLE = {
    "TIER1_MAX": 50,    # < 50 units → 0%
    "TIER2_MAX": 100,   # 50..99 → 5%
    "TIER3_MAX": 200,   # 100..199 → 10%; >= 200 → 15%
    "TIER1_PCT": 0.05,
    "TIER2_PCT": 0.10,
    "TIER3_PCT": 0.15,
}

# Storage fee threshold (PRD §3.3 "Storage fee").
STORAGE_FEE = {
    "BASE_FEE_CENTS": 15000,
    "FREE_UNITS": 20,
    "PER_UNIT_OVERAGE_CENTS": 600,
}

# Early-bird percentages (PRD §3.3 "Early-bird discount and total").
EARLY_BIRD_PCT = {
    "COMMERCIAL": 0.10,
    "HOA": 0.12,
    "EVENT": 0.00,
}

# Damage settlement labor tiers and loyalty waiver (PRD §3.7 "Settlement amount").
DAMAGE_SETTLEMENT = {
    "TIER_LOW_MAX": 50000,    # < 50000 → 20%
    "TIER_MID_MAX": 150000,   # 50000..149999 → 15%; >= 150000 → 10%
    "PCT_LOW": 0.20,
    "PCT_MID": 0.15,
    "PCT_HIGH": 0.10,
    "LOYALTY_WAIVER": 0.05,
    "PCT_FLOOR": 0.05,
}

# Renewal escalation (PRD §3.9 "Renewal pricing").
RENEWAL = {
    "ESCALATION_PCT": 0.05,   # COMMERCIAL or HOA; EVENT = 0
}

# Route minutes (PRD §3.4 "Route time").
ROUTE = {
    "AVG_SPEED_KMH": 40,
}

# Logical clock default (PRD §2.10).
CLOCK_DEFAULT_UTC = "2026-04-01T00:00:00Z"

# Convenient generic test defaults for fixtures.
TEST_DEFAULTS = {
    "DEFAULT_CAPACITY_MINUTES": 480,
    "DEFAULT_HOME_BASE_ZIP": "90001",
    "DEFAULT_SEASON_YEAR": 2026,
    "DEFAULT_EARLY_BIRD_DEADLINE": "2026-03-01T00:00:00Z",
}
