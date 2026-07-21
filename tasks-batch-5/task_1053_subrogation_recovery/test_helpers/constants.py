"""Domain thresholds — numeric constants from the PRD business rules."""

# PRD §3.3 — a demand's response window is 30 days after issuance.
DEMAND_RESPONSE_DAYS = 30
# PRD §3.3 — arbitration_window_due_at is 60 days after disputed_at.
ARBITRATION_FILING_DAYS = 60
# PRD §3.4 — hearing windows on the same adverse party must be >= 7 days apart.
HEARING_BUFFER_DAYS = 7
# PRD §2.10 — managerial settlement approval ceiling ($50,000).
MANAGER_AUTHORITY_CENTS = 5_000_000
# PRD §2.6 — logical-clock startup default.
CLOCK_DEFAULT_UTC = "2026-07-01T00:00:00Z"

# Common test fixture defaults.
DEFAULT_LOSS_DATE = "2026-05-01T00:00:00Z"
DEFAULT_STATUTE_DEADLINE = "2028-01-01T00:00:00Z"
