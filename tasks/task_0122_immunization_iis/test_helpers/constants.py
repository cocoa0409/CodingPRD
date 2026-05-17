"""Domain thresholds — numeric constants used by tests.

Each constant traces back to a verbatim sentence in PRD.md.
"""
from __future__ import annotations

from typing import Any, Dict


# ---------------------------------------------------------------------------
# Compliance scoring - PRD §3.6.
# ---------------------------------------------------------------------------
# PRD §3.6: "A lag of at most 24 hours earns 100.00 — full credit,
# on-time."
COMPLIANCE_ON_TIME_HOURS: float = 24.0

# PRD §3.6: "a lag greater than 24 hours and at most 72 hours falls on
# a linear ramp from 100 down to 40"
COMPLIANCE_LINEAR_END_HOURS: float = 72.0

# PRD §3.6: "A lag greater than 72 hours and at most 168 hours (one
# week) is floored at 40.00."
COMPLIANCE_FLOOR_HOURS: float = 168.0
COMPLIANCE_FLOOR_SCORE: float = 40.0

# PRD §3.6 implicit slope: "the score is 100.00 minus the lag in hours
# minus 24, multiplied by 1.25"
COMPLIANCE_LINEAR_SLOPE: float = 1.25

# PRD §3.6: "When the recomputed score falls below 70.00, the provider
# organization's status auto-transitions to SUSPENDED."
COMPLIANCE_AUTO_SUSPEND_BELOW: float = 70.0

# PRD §3.6: "may reinstate a suspended provider only when its score
# has climbed back to at least 90.00."
COMPLIANCE_REINSTATE_THRESHOLD: float = 90.0

# PRD §3.6: "The window is the rolling 365 days ending at the server's
# current time"
COMPLIANCE_WINDOW_DAYS: int = 365


# ---------------------------------------------------------------------------
# VAERS reportability - PRD §3.9 / §2.8.
# ---------------------------------------------------------------------------
# PRD §3.9: "the lag in hours is at most 24.0" / PRD §2.8: "exactly
# 24.0 hours qualifies, 24.0001 hours does not."
VAERS_RAPID_ONSET_HOURS_INCLUSIVE: float = 24.0


# ---------------------------------------------------------------------------
# Adverse event - PRD §3.9.
# ---------------------------------------------------------------------------
# PRD §3.9: "onset_at ... must be at or after the dose's administered_at
# and within 42 days of it"
ADVERSE_EVENT_ONSET_WINDOW_DAYS: int = 42


# ---------------------------------------------------------------------------
# Pagination - PRD §2.3.
# ---------------------------------------------------------------------------
# PRD §2.3: "The default value of limit is 10, its minimum is 1, and
# its maximum is 100."
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Field length constraints - PRD §3.1.
# ---------------------------------------------------------------------------
# PRD §3.1: "first_name (1 to 80 characters)"
PATIENT_NAME_MIN_LEN: int = 1
PATIENT_NAME_MAX_LEN: int = 80


# ---------------------------------------------------------------------------
# Test default scaffolding.
# ---------------------------------------------------------------------------
TEST_DEFAULTS: Dict[str, Any] = {
    "CLOCK_ANCHOR": "2026-01-01T00:00:00.000Z",
}


__all__ = [
    "COMPLIANCE_ON_TIME_HOURS",
    "COMPLIANCE_LINEAR_END_HOURS",
    "COMPLIANCE_FLOOR_HOURS",
    "COMPLIANCE_FLOOR_SCORE",
    "COMPLIANCE_LINEAR_SLOPE",
    "COMPLIANCE_AUTO_SUSPEND_BELOW",
    "COMPLIANCE_REINSTATE_THRESHOLD",
    "COMPLIANCE_WINDOW_DAYS",
    "VAERS_RAPID_ONSET_HOURS_INCLUSIVE",
    "ADVERSE_EVENT_ONSET_WINDOW_DAYS",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "PATIENT_NAME_MIN_LEN",
    "PATIENT_NAME_MAX_LEN",
    "TEST_DEFAULTS",
]
