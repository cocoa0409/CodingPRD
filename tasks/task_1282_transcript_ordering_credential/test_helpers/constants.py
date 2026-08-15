"""Domain thresholds and defaults — numeric constants from PRD calculations."""

THRESHOLDS = {
    # Basis-point denominator: 15000 bp == 1.5x multiplier (PRD §2.7)
    "BP_DENOMINATOR": 10000,
    # Rush cutoff: 14:00 local registrar time, strict less-than (PRD §3.3)
    "RUSH_CUTOFF_LOCAL": "14:00",
    # Post-cutoff grace window for rush components at capture (PRD §3.6)
    "RUSH_GRACE_HOURS": 4,
    # Archive retrieval SLA in hours (PRD §3.8)
    "RETRIEVAL_SLA_HOURS": 48,
    # Identity verification token lifetime in hours (PRD §3.4)
    "VERIFICATION_TTL_HOURS": 72,
    # Financial zero-amount hold auto-expiry in days (PRD §3.2)
    "HOLD_AUTO_EXPIRE_DAYS": 365,
    # Verification fee components in cents (PRD §3.9)
    "VERIFICATION_BASE_CENTS": 500,
    "VERIFICATION_DEGREE_SURCHARGE_CENTS": 300,
    "VERIFICATION_FULL_RECORD_SURCHARGE_CENTS": 700,
    "VERIFICATION_ARCHIVE_SURCHARGE_CENTS": 1500,
}

TEST_DEFAULTS = {
    "OFFICIAL_BASE_CENTS": 1000,
    "UNOFFICIAL_BASE_CENTS": 500,
    "PAPER_SURCHARGE_CENTS": 200,
    "PICKUP_SURCHARGE_CENTS": 100,
    "RUSH_FLAT_CENTS": 1500,
    "RUSH_MULTIPLIER_BP": 15000,
    "EFFECTIVE_FROM": "2026-08-01T00:00:00Z",
    "CLOCK_DEFAULT": "2026-08-01T00:00:00Z",
}
