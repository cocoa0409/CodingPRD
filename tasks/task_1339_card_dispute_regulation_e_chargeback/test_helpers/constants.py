"""Domain thresholds — numeric constants from the PRD's deadline/fee rules."""

THRESHOLDS = {
    # Consumer liability tiers (integer cents)
    "TIER1_MAX_DELAY_DAYS": 2,
    "TIER2_MAX_DELAY_DAYS": 60,
    "TIER1_CAP_CENTS": 5000,
    "TIER2_CAP_CENTS": 50000,
    # Investigation window (calendar days)
    "WINDOW_STANDARD_DAYS": 45,
    "WINDOW_EXTENDED_DAYS": 90,
    "NEW_ACCOUNT_MAX_AGE_DAYS": 30,
    # Provisional credit deadline (business days)
    "BD_STANDARD": 10,
    "BD_NEW_ACCOUNT": 20,
    # Network fees (integer cents / percentages)
    "FILING_FEE_CENTS": 2500,
    "PRE_COMP_BASE_CENTS": 10000,
    "PRE_COMP_PCT": 0.008,
    "ARB_BASE_CENTS": 25000,
    "ARB_PCT": 0.015,
    # Network filing deadlines (calendar days)
    "NETWORK_FILING_DAYS_VISA": 120,
    "NETWORK_FILING_DAYS_MASTERCARD": 90,
    # Merchant response window (calendar days)
    "MERCHANT_RESPONSE_DAYS": 30,
    # Reversal notice cooling (business days)
    "REVERSAL_NOTICE_COOLING_BD": 3,
}

# Canonical logical-clock timestamps shared by many scenarios.
CLOCK = {
    "ACCOUNT_OPEN": "2026-05-01T00:00:00Z",
    "TXN_POSTED": "2026-07-01T10:00:00Z",
    "DISPUTE_RECEIVED": "2026-08-03T09:00:00Z",
    "CHARGEBACK_FILED": "2026-08-05T09:00:00Z",
    "CHARGEBACK_WITHDRAWN": "2026-08-10T09:00:00Z",
    "RESOLVE_NO_ERROR": "2026-08-21T10:00:00Z",  # a Friday
    "COOLING_2BD": "2026-08-25T09:00:00Z",       # Tuesday: 2 business days after Fri
    "COOLING_3BD": "2026-08-26T09:00:00Z",       # Wednesday: 3 business days after Fri
}

# Precomputed inclusive deadline instants for the canonical receive time
# 2026-08-03T09:00:00Z on an old (non-new) account.
DEADLINES = {
    # 10 business days after 2026-08-03 -> 2026-08-17, end of day inclusive.
    "PROVISIONAL_DUE_OLD_ACCOUNT": "2026-08-17T23:59:59Z",
    # 20 business days after 2026-08-03 -> 2026-08-31, end of day inclusive.
    "PROVISIONAL_DUE_NEW_ACCOUNT": "2026-08-31T23:59:59Z",
    # 45 calendar days after 2026-08-03 -> 2026-09-17, end of day inclusive.
    "INVESTIGATION_DEADLINE_45D": "2026-09-17T23:59:59Z",
    # 90 calendar days after 2026-08-03 -> 2026-11-01, end of day inclusive.
    "INVESTIGATION_DEADLINE_90D": "2026-11-01T23:59:59Z",
    # MASTERCARD filing deadline: posted 2026-07-01 + 90 days -> 2026-09-29 EOD.
    "MASTERCARD_FILING_DEADLINE": "2026-09-29T23:59:59Z",
}

# Server's startup default logical clock (PRD §2.4).
STARTUP_CLOCK = "2026-08-01T00:00:00Z"

# A well-formed UUID that never resolves to a seeded resource.
MISSING_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
