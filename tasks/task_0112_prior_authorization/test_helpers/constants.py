"""Domain thresholds — numeric constants used by tests.

Each constant traces back to a verbatim sentence in PRD.md.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Evidence completeness thresholds — PRD §3.4 / §3.7
# ---------------------------------------------------------------------------
# PRD §3.4: "the request's evidence_completeness_score must be at least
# 0.50. A request that does not yet meet that bar is rejected with
# ERR_EVIDENCE_INSUFFICIENT."
EVIDENCE_THRESHOLD_START_REVIEW: float = 0.50

# PRD §3.4: "Resumption is gated by a stricter evidence threshold:
# evidence_completeness_score must be at least 0.75 (else
# ERR_EVIDENCE_INSUFFICIENT)."
EVIDENCE_THRESHOLD_RESUME_REVIEW: float = 0.75


# ---------------------------------------------------------------------------
# Reuse discount — PRD §3.7
# ---------------------------------------------------------------------------
# PRD §3.7: "computes the discount as 0.05 multiplied by the count of
# reused documents, but never larger than 0.20".
REUSE_DISCOUNT_PER_DOC: float = 0.05
REUSE_DISCOUNT_CAP: float = 0.20

# PRD §3.5: "If the outcome is OVERTURNED, the parent authorization's
# evidence_completeness_score is recomputed using the post-peer-to-peer
# variant, which adds a bonus of 0.10 to the base score before clamping".
P2P_OVERTURNED_BONUS: float = 0.10


# ---------------------------------------------------------------------------
# SLA hours — PRD §3.1 / §3.6
# ---------------------------------------------------------------------------
# PRD §3.1: "standard_sla_hours (the decision window for a STANDARD
# request, defaulting to 336 — that is, 14 days — and required to be at
# least 24)".
DEFAULT_STANDARD_SLA_HOURS: int = 336
STANDARD_SLA_MIN_HOURS: int = 24

# PRD §3.1: "expedited_sla_hours (defaulting to 72 — three days — and
# required to be at least 4 and strictly less than standard_sla_hours)".
DEFAULT_EXPEDITED_SLA_HOURS: int = 72
EXPEDITED_SLA_MIN_HOURS: int = 4

# PRD §3.6: "The extension per cycle is 168 hours (one week) for a
# STANDARD request and 24 hours (one day) for an EXPEDITED request."
STANDARD_PENDING_INFO_EXTENSION_HOURS: int = 168
EXPEDITED_PENDING_INFO_EXTENSION_HOURS: int = 24


# ---------------------------------------------------------------------------
# Appeal-tier SLA hours — PRD §3.11
# ---------------------------------------------------------------------------
# PRD §3.11: "For STANDARD authorizations, tier 1 has a 240-hour window
# (10 days), tier 2 has 480 hours (20 days), and tier 3 has 720 hours
# (30 days)."
STANDARD_APPEAL_TIER_1_HOURS: int = 240
STANDARD_APPEAL_TIER_2_HOURS: int = 480
STANDARD_APPEAL_TIER_3_HOURS: int = 720

# PRD §3.11: "For EXPEDITED authorizations, the per-tier windows shrink
# considerably: tier 1 has 72 hours (3 days), tier 2 has 96 hours (4
# days), and tier 3 has 168 hours (7 days)."
EXPEDITED_APPEAL_TIER_1_HOURS: int = 72
EXPEDITED_APPEAL_TIER_2_HOURS: int = 96
EXPEDITED_APPEAL_TIER_3_HOURS: int = 168


# ---------------------------------------------------------------------------
# Approval validity — PRD §3.1 / §3.10
# ---------------------------------------------------------------------------
# PRD §3.1: "approval_validity_days (defaulting to 90 and required to be
# at least 1; this is how long an APPROVED authorization remains usable
# from its approval timestamp)".
DEFAULT_APPROVAL_VALIDITY_DAYS: int = 90


# ---------------------------------------------------------------------------
# ClinicalEvidence byte-size bounds — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "The byte_size must be strictly greater than 0 and no greater
# than 50,000,000 (50 MB)".
EVIDENCE_BYTE_SIZE_MIN: int = 1
EVIDENCE_BYTE_SIZE_MAX: int = 50_000_000


# ---------------------------------------------------------------------------
# Clinical justification — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "if urgency is EXPEDITED — the clinical_justification must
# contain at least 50 non-whitespace characters".
EXPEDITED_JUSTIFICATION_MIN_NONSPACE_CHARS: int = 50

# PRD §3.2: "a free-text clinical_justification capped at 4,000
# characters".
JUSTIFICATION_MAX_CHARS: int = 4000


# ---------------------------------------------------------------------------
# Peer-to-peer review duration — PRD §3.5
# ---------------------------------------------------------------------------
# PRD §3.5: "duration_minutes (the call window length, between 15 and 60
# inclusive)".
P2P_DURATION_MIN_MINUTES: int = 15
P2P_DURATION_MAX_MINUTES: int = 60


# ---------------------------------------------------------------------------
# Appeal tiers — PRD §3.11
# ---------------------------------------------------------------------------
# PRD §3.11: "The values 1, 2, and 3 are the only legal tiers."
APPEAL_TIER_MIN: int = 1
APPEAL_TIER_MAX: int = 3


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "The limit parameter specifies the maximum number of items
# to return; it defaults to 10, with a minimum of 1 and a maximum of
# 100. The offset parameter specifies the number of items to skip and
# defaults to 0."
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Hours in a day — used to relate approval_validity_days to expires_at.
# ---------------------------------------------------------------------------
HOURS_PER_DAY: int = 24


# ---------------------------------------------------------------------------
# Test defaults — anchored to PRD-named values.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    # PRD §3.1 sensible defaults for a typical catalog item.
    "STANDARD_SLA_HOURS": DEFAULT_STANDARD_SLA_HOURS,
    "EXPEDITED_SLA_HOURS": DEFAULT_EXPEDITED_SLA_HOURS,
    "APPROVAL_VALIDITY_DAYS": DEFAULT_APPROVAL_VALIDITY_DAYS,
    # The four-category required evidence list used by most fixtures and
    # by SCAFFOLD_DIFFICULTY_DESIGN.yaml. Each missing category drops
    # base coverage by 0.25.
    "REQUIRED_EVIDENCE_CATEGORIES": [
        "LAB", "IMAGING", "NOTES", "MED_HISTORY",
    ],
    # PRD §3.10 — deterministic clock anchor used by the time-sensitive
    # difficulty-design instances.
    "CLOCK_ANCHOR": "2026-05-16T00:00:00.000Z",
    # Sensible default justification: 60 non-whitespace chars satisfies
    # both STANDARD and EXPEDITED rules.
    "DEFAULT_JUSTIFICATION": (
        "Patient requires the requested service per published clinical "
        "guidelines."
    ),
    # PRD §3.4 default; tests override as needed.
    "DEFAULT_REQUESTED_UNITS": 5,
}


__all__ = [
    "EVIDENCE_THRESHOLD_START_REVIEW",
    "EVIDENCE_THRESHOLD_RESUME_REVIEW",
    "REUSE_DISCOUNT_PER_DOC",
    "REUSE_DISCOUNT_CAP",
    "P2P_OVERTURNED_BONUS",
    "DEFAULT_STANDARD_SLA_HOURS",
    "STANDARD_SLA_MIN_HOURS",
    "DEFAULT_EXPEDITED_SLA_HOURS",
    "EXPEDITED_SLA_MIN_HOURS",
    "STANDARD_PENDING_INFO_EXTENSION_HOURS",
    "EXPEDITED_PENDING_INFO_EXTENSION_HOURS",
    "STANDARD_APPEAL_TIER_1_HOURS",
    "STANDARD_APPEAL_TIER_2_HOURS",
    "STANDARD_APPEAL_TIER_3_HOURS",
    "EXPEDITED_APPEAL_TIER_1_HOURS",
    "EXPEDITED_APPEAL_TIER_2_HOURS",
    "EXPEDITED_APPEAL_TIER_3_HOURS",
    "DEFAULT_APPROVAL_VALIDITY_DAYS",
    "EVIDENCE_BYTE_SIZE_MIN",
    "EVIDENCE_BYTE_SIZE_MAX",
    "EXPEDITED_JUSTIFICATION_MIN_NONSPACE_CHARS",
    "JUSTIFICATION_MAX_CHARS",
    "P2P_DURATION_MIN_MINUTES",
    "P2P_DURATION_MAX_MINUTES",
    "APPEAL_TIER_MIN",
    "APPEAL_TIER_MAX",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "HOURS_PER_DAY",
    "TEST_DEFAULTS",
]
