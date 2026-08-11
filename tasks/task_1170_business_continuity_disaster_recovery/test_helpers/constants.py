"""Domain thresholds — numeric constants from PRD calculations (§3)."""

THRESHOLDS = {
    # BIA criticality score (§3.2)
    "TIER1_UPLIFT": 0.15,
    # Vendor continuity score (§3.4)
    "EVENT_DRIVEN_DISCOUNT": 15,
    # Attestation readiness (§3.9)
    "SIGN_THRESHOLD": 70,
    "PLAN_POINTS": 40,
    "CAPABILITY_BASE": 25,
    "OVERDUE_PENALTY_PER_GAP": 10,
    "EXERCISE_POINTS_MET": 25,
    "EXERCISE_POINTS_OTHER": 10,
    "OPEN_GAP_MULTIPLIER": 0.8,
    "RECENCY_DAYS": 365,
    # Capability freshness (§3.7)
    "FRESHNESS_MONTHS": 12,
    # Gap backlog pressure (§3.7)
    "CRITICAL_OVERDUE_MULTIPLIER": 2,
}

GAP_SEVERITY_WEIGHTS = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}

TEST_DEFAULTS = {
    # Logical program clock used by time-sensitive scenarios (§2.4).
    "CLOCK": "2026-06-01T00:00:00Z",
    "RTO_TARGET": 8,
    "RPO_TARGET": 2,
}
