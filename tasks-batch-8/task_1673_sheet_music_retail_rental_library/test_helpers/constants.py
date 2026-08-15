"""Domain thresholds — numeric constants named in the PRD (§3.1, §3.5, §3.6, §3.7)."""

THRESHOLDS = {
    # Rental fee arithmetic (PRD §3.5)
    "LOAN_PERIOD_DAYS": 30,
    "BAND_TIER_MULT": 1.5,
    "ORCH_TIER_MULT": 2.0,
    "VOLUME_TIER_1_QTY": 10,
    "VOLUME_TIER_1_DISC": 0.10,
    "VOLUME_TIER_2_QTY": 25,
    "VOLUME_TIER_2_DISC": 0.20,
    "DIGITAL_FEE_FACTOR": 0.80,
    # Late-return surcharge tiers (PRD §3.6)
    "LATE_TIER_1_DAYS": 7,
    "LATE_TIER_2_DAYS": 30,
    "LATE_RATE_1": 0.10,
    "LATE_RATE_2": 0.25,
    "LATE_RATE_3": 0.50,
    # Damage billing (PRD §3.6)
    "DAMAGE_CAP_CENTS": 200000,
    "DAMAGE_FLOOR_CENTS": 1500,
    # Perusal policy (PRD §3.7)
    "PERUSAL_DISCOUNT": 0.15,
    "PERUSAL_WINDOW_DAYS": 21,
    "QUARANTINE_DAYS": 3,
    "PERUSAL_APPROVAL_EXPIRY_DAYS": 10,
    # Out-of-print sourcing (PRD §3.1)
    "OOP_BASE_DAYS": 45,
    "OOP_GRAND_RIGHTS_ADD": 30,
    "OOP_RESTRICTED_ADD": 60,
    "OOP_SET_CREDIT": 15,
    "OOP_MIN_DAYS": 7,
    # Renewal cap (PRD §3.5)
    "RENEWAL_CAP": 2,
}

TEST_DEFAULTS = {
    "BASE_RATE_CHAMBER": 10000,
    "REPLACEMENT_VALUE": 240000,
    "COPY_COUNT": 30,
    "CHECKOUT_DATE": "2026-08-05",
    "DUE_DATE": "2026-09-04",
    "BASE_CLOCK": "2026-08-05T00:00:00Z",
    "STARTUP_CLOCK": "2026-08-01T00:00:00Z",
}
