"""Domain thresholds — numeric constants from PRD rules (§2.4, §3.4, §3.5, §3.6, §3.8)."""

THRESHOLDS = {
    # Effectiveness horizon for an accepted INITIAL filing (PRD §3.5)
    "EFFECTIVENESS_MONTHS": 60,
    # Continuation window opens this many months before expiration (PRD §3.5)
    "CONTINUATION_WINDOW_MONTHS": 6,
    # Refile window after a rejection, inclusive boundary (PRD §3.4)
    "REFILE_WINDOW_DAYS": 30,
    # Supporting-search freshness at approval; exactly 90 days old is fresh (PRD §3.3)
    "SEARCH_FRESHNESS_DAYS": 90,
    # Default report lookahead (PRD §3.8)
    "DEFAULT_HORIZON_DAYS": 90,
    # Expedited fee uplift applied once with a single half-up rounding (PRD §3.4)
    "EXPEDITED_MULTIPLIER": 1.5,
    # Per-kind flat fee deltas in cents (PRD §3.4)
    "KIND_FEE_DELTA_CENTS": {
        "NEW_UCC1": 0,
        "AMENDMENT": 1000,
        "CONTINUATION": 1500,
        "TERMINATION": 500,
    },
    # Collateral sufficiency floor (PRD §3.4)
    "MIN_COLLATERAL_CHARS": 20,
    "SUPERGENERIC_TERMS": ["ALL ASSETS", "ALL PERSONAL PROPERTY", "ALL ASSETS OF DEBTOR"],
}

TEST_DEFAULTS = {
    # Logical clock startup reading (PRD §2.4)
    "CLOCK_START_ISO": "2026-08-01T00:00:00Z",
    "CLIENT_NAME": "Acme Lending",
    "ORG_LEGAL_NAME": "Acme Manufacturing, Inc.",
    "ORG_JURISDICTION": "DE",
    "SECOND_ORG_LEGAL_NAME": "Beta Holdings, LLC",
    "SECURED_PARTY_NAME": "Acme Lending",
    "COLLATERAL_TEXT": "All manufacturing equipment located at 100 Industrial Way",
    "SECOND_COLLATERAL_TEXT": "All inventory and equipment of debtor",
    "FEE_AUTHORIZATION_CENTS": 100000,
    "SECURED_AMOUNT_CENTS": 500000,
    "FILING_NUMBER": "CA-2026-0001",
    # Canonical CA jurisdiction profile values used across tests
    "CA_BASE_FEE_CENTS": 10000,
    "CA_PER_ADDITIONAL_DEBTOR_FEE_CENTS": 1500,
    "CA_COUNTY_SURCHARGE_CENTS": 2500,
    "CA_COUNTY_COLLATERAL_CLASSES": ["FIXTURE"],
    "CA_COUNTY_NAMES": ["LOS_ANGELES", "ORANGE"],
    "CA_NAME_RULE": "LEGAL_NAME_ONLY",
    "CA_EXPEDITED_DAILY_CAPACITY": 2,
}
