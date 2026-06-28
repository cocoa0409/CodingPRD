"""Domain thresholds — numeric constants from the PRD calculation narratives (§3)."""

# Readiness blend coefficients (§3.4)
DOMAIN_WEIGHT_COEFF = 0.60
MOCK_WEIGHT_COEFF = 0.40

# EWMA mastery smoothing coefficient (§3.4)
ALPHA = 0.40

# Pass-guarantee eligibility thresholds (§3.5)
MIN_QUESTIONS = 200
MIN_MOCKS = 2
READINESS_THRESHOLD = 75  # conservative readiness_score >= 75 inclusive

# Cohort-session buffer (§3.8)
SESSION_BUFFER_MINUTES = 30

# Initial mastery materialized on activation (§3.3)
INITIAL_MASTERY = 50

# Logical clock default at server startup (§3.9)
CLOCK_DEFAULT_UTC = "2026-04-01T00:00:00Z"
