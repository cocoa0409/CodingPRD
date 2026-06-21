"""Domain thresholds — numeric constants from PRD calculations and policies."""

# --- Interchange-plus pricing constants (PRD §3.4) ---
INTERCHANGE_BPS = 165
INTERCHANGE_FIXED_CENTS = 10

# --- 1099-K reporting threshold (PRD §3.11) ---
# Gross strictly greater than this is reportable.
REPORTING_THRESHOLD_CENTS = 250000

# --- Risk-band derived terms (PRD §3.2) ---
# LOW -> 0 bps reserve, T+1 funding; MEDIUM -> 500 bps, T+2; HIGH -> 1000 bps, T+2.
RISK_BAND_RESERVE_BPS = {
    "LOW": 0,
    "MEDIUM": 500,
    "HIGH": 1000,
}
RISK_BAND_FUNDING_DELAY_DAYS = {
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 2,
}

# --- High-risk Merchant Category Codes (PRD §3.2) ---
HIGH_RISK_MCC_SET = {"5933", "5967", "7995", "5122"}

# --- Dispute lifecycle windows (PRD §3.6) ---
EVIDENCE_WINDOW_DAYS = 14
MAX_REPRESENTMENT_ROUNDS = 2

# --- Reserve hold window (PRD §3.9) ---
RESERVE_HOLD_DAYS = 90

# --- Authorization hold window (PRD §3.3) ---
AUTH_HOLD_DAYS = 7

# --- Default fee plan chargeback fee (PRD §3.1) ---
DEFAULT_CHARGEBACK_FEE_CENTS = 1500

TEST_DEFAULTS = {
    "FLAT_PCT_BPS": 290,
    "FLAT_FIXED_CENTS": 30,
    "CHARGEBACK_FEE_CENTS": 1500,
}
