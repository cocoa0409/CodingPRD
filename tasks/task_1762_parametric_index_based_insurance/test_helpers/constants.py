"""Domain thresholds and pricing constants from the PRD's calculation rules."""

THRESHOLDS = {
    # Fraud gate: approval routes to FRAUD_HOLD once fraud_score reaches this (PRD §3.4/§3.7).
    "FRAUD_SCORE_AUTO_HOLD": 70,
    # Fraud contagion penalties (PRD §3.4, §3.8).
    "DENIED_DATA_SOURCE_PENALTY": 10,
    "MANUAL_FLAG_PENALTY": 25,
    "SCORE_FLOOR": 0,
    "SCORE_CEILING": 100,
    # Blend precision (PRD §2.7).
    "BLEND_PRECISION_DP": 4,
}

# Premium pricing branches by regulatory classification (PRD §3.5).
PREMIUM_LOADING_PCT = {
    "ADMITTED_INSURANCE": 0.25,
    "SURPLUS_LINES": 0.35,
    "DERIVATIVE_CONTRACT": 0.15,
}
PREMIUM_TAX_PCT = {
    "ADMITTED_INSURANCE": 0.02,
    "SURPLUS_LINES": 0.05,
    "DERIVATIVE_CONTRACT": 0.00,
}

TEST_DEFAULTS = {
    # Canonical ADMITTED program pricing case: si 2,000,000, freq 0.20, elr 0.60
    # -> pure 240,000; premium 300,000; tax 6,000; invoice 306,000.
    "SUM_INSURED": 2_000_000,
    "BREACH_FREQUENCY": 0.20,
    "LOSS_RATIO": 0.60,
    "ADMITTED_PREMIUM_CENTS": 300_000,
    "ADMITTED_TAX_CENTS": 6_000,
    "ADMITTED_INVOICE_CENTS": 306_000,
    "EXPOSURE_LIMIT_CENTS": 100_000_000,
    "POLICY_START_DATE": "2026-01-01",
    "POLICY_END_DATE": "2026-12-31",
    "WINDOW_END_DATE": "2026-06-30",
}

# Non-existent UUID used for 404 existence probes.
MISSING_UUID = "00000000-0000-0000-0000-000000000000"
