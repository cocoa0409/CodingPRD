"""Domain thresholds — numeric constants from PRD calculations and timing rules."""

# Finding severity CVSS band floors (PRD §3.5).
CVSS_BANDS = {
    "LOW_FLOOR": 0.1,
    "MEDIUM_FLOOR": 4.0,
    "HIGH_FLOOR": 7.0,
    "CRITICAL_FLOOR": 9.0,
}

# Remediation SLA base windows in hours, keyed by severity (PRD §3.5).
SLA_BASE_HOURS = {
    "CRITICAL": 24,
    "HIGH": 72,
    "MEDIUM": 168,
    "LOW": 720,
    "INFO": None,
}

# Tier multipliers shrinking the SLA window for higher tiers (PRD §3.5).
TIER_MULTIPLIER = {
    "ESSENTIAL": 1.0,
    "ADVANCED": 0.75,
    "ELITE": 0.5,
}

# Alert triage weighted-scoring weights and band floors (PRD §3.6).
TRIAGE = {
    "RAW_WEIGHT": 0.6,
    "CRIT_WEIGHT": {"LOW": 0, "MEDIUM": 10, "HIGH": 20, "CROWN_JEWEL": 35},
    "EXPOSURE_BONUS": 15,
    "P1_FLOOR": 80,
    "P2_FLOOR": 55,
    "P3_FLOOR": 30,
}

# Scan cooldown: a new scan may not start within 24 hours of another RUNNING
# scan on the same engagement (closed buffered interval) (PRD §3.4).
SCAN_COOLDOWN_HOURS = 24

# Default logical clock at server startup (PRD §1, §3.9).
DEFAULT_CLOCK = "2026-03-01T00:00:00Z"

TEST_DEFAULTS = {
    "RETAINER_HOURS": 100,
    "ESTIMATED_HOURS": 10,
}
