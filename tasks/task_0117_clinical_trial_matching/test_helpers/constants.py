"""Domain thresholds — numeric constants used by tests.

Each constant traces back to a verbatim sentence in PRD.md.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Eligibility — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "a score greater than or equal to 80.0 is ELIGIBLE (the
# threshold is inclusive); a score less than 80.0 is INELIGIBLE."
ELIGIBILITY_THRESHOLD: float = 80.0


# ---------------------------------------------------------------------------
# Compensation — PRD §3.8
# ---------------------------------------------------------------------------
# PRD §3.8: "The base compensation is 5000 cents."
BASE_VISIT_CENTS: int = 5000

# PRD §3.8: "When d equals zero — the draw is exactly on target_date —
# the bonus is the on-time bonus of 1000 cents."
ON_TIME_BONUS_CENTS: int = 1000

# PRD §3.8: "the late-day penalty of 750 cents is multiplied by the
# number of days past the grace period, computed as (d - 2)."
LATE_PENALTY_CENTS: int = 750

# PRD §3.8: "a re-consent bonus of 2500 cents is allocated to the last
# chronological COMPLETED visit".
RE_CONSENT_BONUS_CENTS: int = 2500


# ---------------------------------------------------------------------------
# IRB approval — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "sets irb_approval_expires_at to exactly 365 days after the
# decided_at timestamp".
IRB_APPROVAL_VALIDITY_DAYS: int = 365


# ---------------------------------------------------------------------------
# Trial blood-draw window — PRD §2.9
# ---------------------------------------------------------------------------
# PRD §2.9: "an integer between 0 and 14 inclusive".
BLOOD_DRAW_WINDOW_DAYS_MIN: int = 0
BLOOD_DRAW_WINDOW_DAYS_MAX: int = 14


# ---------------------------------------------------------------------------
# Target enrollment — PRD §3.1
# ---------------------------------------------------------------------------
# PRD §3.1: "the target_enrollment integer in the range 1 to 10000
# inclusive".
TARGET_ENROLLMENT_MIN: int = 1
TARGET_ENROLLMENT_MAX: int = 10000


# ---------------------------------------------------------------------------
# Arm weight — PRD §3.1
# ---------------------------------------------------------------------------
# PRD §3.1: "a weight integer between 1 and 10 inclusive."
ARM_WEIGHT_MIN: int = 1
ARM_WEIGHT_MAX: int = 10


# ---------------------------------------------------------------------------
# Visit sequence_no — PRD §3.6
# ---------------------------------------------------------------------------
# PRD §3.6: "a 1-indexed sequence_no between 1 and 50 that must be
# unique within the participant".
VISIT_SEQUENCE_NO_MIN: int = 1
VISIT_SEQUENCE_NO_MAX: int = 50


# ---------------------------------------------------------------------------
# Block-size allowed values — PRD §3.1
# ---------------------------------------------------------------------------
# PRD §3.1: "block_size, which must be one of 2, 4, 6, or 8".
ALLOWED_BLOCK_SIZES: tuple = (2, 4, 6, 8)


# ---------------------------------------------------------------------------
# AE narrative bounds — PRD §3.7
# ---------------------------------------------------------------------------
# PRD §3.7: "a narrative of 1 to 2000 characters".
NARRATIVE_MIN_CHARS: int = 1
NARRATIVE_MAX_CHARS: int = 2000


# ---------------------------------------------------------------------------
# Resolution note bounds — PRD §3.7
# ---------------------------------------------------------------------------
# PRD §3.7: "supplying a resolution_note of 1 to 1000 characters".
RESOLUTION_NOTE_MIN_CHARS: int = 1
RESOLUTION_NOTE_MAX_CHARS: int = 1000


# ---------------------------------------------------------------------------
# IRB review notes bounds — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "reviewer notes of 1 to 1000 characters".
IRB_NOTES_MIN_CHARS: int = 1
IRB_NOTES_MAX_CHARS: int = 1000


# ---------------------------------------------------------------------------
# Document URI bounds — PRD §3.1
# ---------------------------------------------------------------------------
# PRD §3.1: "Consent publication adds a document_uri of 1 to 500
# characters, optionally a change_summary (required from version 2
# onward)".
DOCUMENT_URI_MIN_CHARS: int = 1
DOCUMENT_URI_MAX_CHARS: int = 500
CHANGE_SUMMARY_MIN_CHARS: int = 1
CHANGE_SUMMARY_MAX_CHARS: int = 500


# ---------------------------------------------------------------------------
# Title bounds — PRD §3.1
# ---------------------------------------------------------------------------
# PRD §3.1: "a human-readable title of 1–200 characters after trimming".
TITLE_MIN_CHARS: int = 1
TITLE_MAX_CHARS: int = 200


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "defaulting to 10 if not provided, with a minimum of 1 and a
# maximum of 100".
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Test defaults.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    # PRD §2.12 deterministic clock anchor used by time-sensitive tests.
    "CLOCK_ANCHOR": "2026-05-16T00:00:00.000Z",
    # A generous default blood-draw window.
    "DEFAULT_BLOOD_DRAW_WINDOW_DAYS": 7,
    # Two-arm trials are the minimum that satisfies submit-for-irb
    # (PRD §3.1: "the trial has at least 2 arms").
    "DEFAULT_TARGET_ENROLLMENT": 10,
}


__all__ = [
    "ELIGIBILITY_THRESHOLD",
    "BASE_VISIT_CENTS",
    "ON_TIME_BONUS_CENTS",
    "LATE_PENALTY_CENTS",
    "RE_CONSENT_BONUS_CENTS",
    "IRB_APPROVAL_VALIDITY_DAYS",
    "BLOOD_DRAW_WINDOW_DAYS_MIN",
    "BLOOD_DRAW_WINDOW_DAYS_MAX",
    "TARGET_ENROLLMENT_MIN",
    "TARGET_ENROLLMENT_MAX",
    "ARM_WEIGHT_MIN",
    "ARM_WEIGHT_MAX",
    "VISIT_SEQUENCE_NO_MIN",
    "VISIT_SEQUENCE_NO_MAX",
    "ALLOWED_BLOCK_SIZES",
    "NARRATIVE_MIN_CHARS",
    "NARRATIVE_MAX_CHARS",
    "RESOLUTION_NOTE_MIN_CHARS",
    "RESOLUTION_NOTE_MAX_CHARS",
    "IRB_NOTES_MIN_CHARS",
    "IRB_NOTES_MAX_CHARS",
    "DOCUMENT_URI_MIN_CHARS",
    "DOCUMENT_URI_MAX_CHARS",
    "CHANGE_SUMMARY_MIN_CHARS",
    "CHANGE_SUMMARY_MAX_CHARS",
    "TITLE_MIN_CHARS",
    "TITLE_MAX_CHARS",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "TEST_DEFAULTS",
]
