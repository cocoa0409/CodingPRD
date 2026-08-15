"""Domain thresholds and shared constants from the PRD.

Ten thousand basis points make a whole (PRD section 2.5). The obsolescence
sweep retires a product whose generation trails the current maximum for its
kind by more than two, and strands an ON_HAND lot ninety days after its
product was discontinued (PRD sections 3.1 and 3.3).
"""

BP_BASE = 10000

THRESHOLDS = {
    # Product falls OBSOLETE when it is more than two generations behind.
    "OBSOLESCENCE_GENERATION_LAG": 2,
    # An ON_HAND lot strands ninety days after its product is discontinued.
    "STRANDED_AGE_DAYS": 90,
    # progress_payment_pct_bp must lie between 0 and 10000 inclusive.
    "PROGRESS_PCT_MAX_BP": 10000,
}

TEST_DEFAULTS = {
    # Logical clock reads 2026-08-01T00:00:00Z at server startup (PRD 2.10).
    "DEFAULT_CLOCK": "2026-08-01T00:00:00Z",
    "TARIFF_EFFECTIVE_FROM": "2026-07-01T00:00:00Z",
    "HTS_MODULE": "8541.43",
    "HTS_INVERTER": "8504.40",
    "MODULE_DUTY_RATE_BP": 1000,
    "INVERTER_DUTY_RATE_BP": 500,
    "MODULE_WATTAGE_W": 400,
    "MODULE_DECLARED_UNIT_VALUE_CENTS": 50000,
    "MODULE_LIST_PRICE_CENTS": 22000,
    "INVERTER_LIST_PRICE_CENTS": 250000,
    "INSTALLER_CREDIT_LIMIT_CENTS": 100_000_000,
    "INSTALLER_PROGRESS_PCT_BP": 10000,
    "INSTALLER_PAYMENT_TERMS_DAYS": 30,
    "CONTAINER_ETA": "2026-08-05T00:00:00Z",
    "RULE_MIN_MODULES": 5,
    "RULE_MAX_MODULES": 20,
}
