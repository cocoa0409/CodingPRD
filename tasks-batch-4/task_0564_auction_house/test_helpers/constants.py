"""Domain thresholds — numeric constants from the Auction House PRD (§3)."""

# Buyer's premium progressive tiers (PRD §3.5).
BUYERS_PREMIUM = {
    "TIER1_UPPER_CENTS": 300_000,
    "TIER1_RATE": 0.25,
    "TIER2_UPPER_CENTS": 2_000_000,
    "TIER2_RATE": 0.20,
    "TIER3_RATE": 0.15,
}

# Escalating bid-increment bands (PRD §3.4).
BID_INCREMENT_BANDS = {
    "BAND1_UPPER_CENTS": 10_000,
    "BAND1_INC_CENTS": 1_000,
    "BAND2_UPPER_CENTS": 100_000,
    "BAND2_INC_CENTS": 5_000,
    "BAND3_UPPER_CENTS": 1_000_000,
    "BAND3_INC_CENTS": 10_000,
    "BAND4_INC_CENTS": 50_000,
}

# Storage accrual (PRD §3.6).
FREE_STORAGE_DAYS = 7
DAILY_STORAGE_CENTS = 500

# High-value deposit gating (PRD §3.4).
HIGH_VALUE_LOT_CENTS = 1_000_000
MIN_DEPOSIT_FOR_HIGH_VALUE_CENTS = 100_000

# Consignor intake spacing (PRD §3.2).
INTAKE_BUFFER_MINUTES = 60

# Server logical clock startup default (PRD §2.6).
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"
