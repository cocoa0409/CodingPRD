"""Domain thresholds — numeric constants drawn from the PRD's calculations.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Credential-trust weighting and thresholds (PRD §3.3).
STANDARD_WEIGHTS = {"kba": 0.5, "credential": 0.3, "biometric": 0.2}
ENHANCED_WEIGHTS = {"kba": 0.3, "credential": 0.4, "biometric": 0.3}
STANDARD_THRESHOLD = 70
ENHANCED_THRESHOLD = 75

# Concurrent-session cap (PRD §3.4).
MAX_CONCURRENT_SESSIONS = 3

# Apostille flat authentication fees (PRD §3.8).
HAGUE_MEMBERS = ["FR", "DE", "JP", "MX", "IT", "ES", "GB", "NL"]
APOSTILLE_FEE_CENTS = 2000
CERTIFICATION_FEE_CENTS = 4000

# Apostille resubmit cap (PRD §3.8).
RESUBMIT_LIMIT = 3

# Default account retention horizon (PRD §3.1).
DEFAULT_RETENTION_YEARS = 10

# Default logical-clock startup instant (PRD §2.4).
CLOCK_DEFAULT = "2026-03-01T00:00:00Z"

# A canonical default fee schedule used across many setups.
DEFAULT_FEE_SCHEDULE = {
    "state_code": "CA",
    "per_stamp_cents": 1500,
    "travel_base_cents": 4000,
    "travel_per_mile_cents": 100,
    "ron_surcharge_cents": 2500,
    "state_cap_cents": 20000,
}
