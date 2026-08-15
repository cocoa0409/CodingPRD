"""Domain constants — program defaults, shared timestamps, canonical texts."""

# The fixed startup reading of the server logical clock (PRD logical-clock section).
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# Program configuration defaults applied when optional fields are omitted.
PROGRAM_DEFAULTS = {
    "ack_deadline_days": 14,
    "reminder_interval_days": 7,
    "max_reminders_before_escalation": 3,
    "stale_hold_days": 180,
    "over_preservation_warn_pct": 20,
    "ack_sla_mode": "STRICT",
}

# Canonical open-ended rule window start used across fixtures.
STANDARD_WINDOW_START = "2020-01-01T00:00:00Z"

# Canonical texts meeting the PRD minimum-length rules.
JUSTIFICATION_20 = "Purge eligible record batch"   # >= 20 chars
JUSTIFICATION_SHORTEST_20 = "Counsel approved shorter statutory minimum"  # >= 20 chars
RELEASE_REASON_10 = "matter closed"                # >= 10 chars
REJECTION_REASON_10 = "Need counsel review first"  # >= 10 chars
JUSTIFICATION_19 = "nineteen characters"           # exactly 19 chars (too short)
JUSTIFICATION_SHORT = "short"                      # 5 chars (too short everywhere)
