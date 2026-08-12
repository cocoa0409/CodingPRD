"""Domain thresholds — numeric constants from PRD calculations (§3)."""

THRESHOLDS = {
    # Moisture / drying-day classification (PRD §3.3)
    "MOISTURE_WET_MARGIN": 2,
    "DRYING_T1": 8,
    "DRYING_T2": 20,
    "WORST_DAYS": [1, 3, 5],
    "MEAN_DAYS": [1, 2, 4],
    # Inspection scheduling travel buffer, minutes (PRD §3.3)
    "TRAVEL_BUFFER_MINUTES": 30,
    # Work authorization validity, days (PRD §3.8)
    "WA_VALIDITY_DAYS": 30,
    # Scope-drift void tolerance, fraction of scope_rcv_cents (PRD §3.6)
    "WA_SCOPE_DRIFT_TOLERANCE": 0.10,
    # Carrier defaults (PRD §3.1)
    "DEFAULT_OVERHEAD_RATE": 0.10,
    "DEFAULT_PROFIT_RATE": 0.10,
    "DEFAULT_O_AND_P_MIN_TRADES": 3,
    "DEFAULT_NEGOTIATION_RESPONSE_DAYS": 7,
}

TEST_DEFAULTS = {
    # Logical clock startup value (PRD §2.4)
    "START_CLOCK": "2026-05-01T00:00:00Z",
    "DEFAULT_DATE_OF_LOSS": "2026-03-10T00:00:00Z",
    "POLICY_PERIOD_START": "2026-01-01T00:00:00Z",
    "POLICY_PERIOD_END": "2026-12-31T23:59:59Z",
    "ENTRY_WINDOW_FROM": "2026-01-01T00:00:00Z",
    "ENTRY_WINDOW_TO": "2027-01-01T00:00:00Z",
}
