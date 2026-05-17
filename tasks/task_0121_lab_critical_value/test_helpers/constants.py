"""Domain thresholds — numeric constants used by tests.

Each constant traces back to a verbatim sentence in PRD.md.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Acknowledgement windows — PRD §3.5.
# ---------------------------------------------------------------------------
# PRD §3.5: "30 minutes when priority is ROUTINE, 10 minutes when
# priority is STAT."
ACK_WINDOW_ROUTINE_MIN: int = 30
ACK_WINDOW_STAT_MIN: int = 10

# PRD §3.5: "extends ack_deadline_at by 10 minutes regardless of the
# original priority."
ESCALATION_EXTENSION_MIN: int = 10


# ---------------------------------------------------------------------------
# Severity scoring — PRD §3.6.
# ---------------------------------------------------------------------------
# PRD §3.6: "Both variants use a per-flag weight of 2 when the flag's
# `side` is `HIGH` and 1 when the flag's `side` is `LOW`."
SEVERITY_HIGH_WEIGHT: int = 2
SEVERITY_LOW_WEIGHT: int = 1

# PRD §3.6: "the system looks up the two most recently released lab
# results for the same `patient_id` and the same `panel_id`, ordered by
# `released_at` descending, excluding the current result itself."
SEVERITY_HISTORY_LOOKBACK: int = 2

# PRD §3.6: "counts how many had any critical flags, multiplies that
# count by 0.25, adds 1.0, and uses the sum as a historical factor."
SEVERITY_HISTORY_BOOST_PER_PRIOR_CRITICAL: float = 0.25
SEVERITY_HISTORY_BASE_FACTOR: float = 1.0


# ---------------------------------------------------------------------------
# Specimen stability — PRD §3.3 / §2.9.
# ---------------------------------------------------------------------------
# PRD §2.9: "transit minutes equal to the panel's `stability_minutes` is
# considered on-time and accepted, and only transit minutes strictly
# greater than `stability_minutes` cause a rejection."
STABILITY_STRICT_COMPARISON: bool = True

# PRD §3.3 / §3.5 anchor: lab location code (used to identify final
# leg). PRD §3.3: "When the arriving leg's `to_location` equals the
# lab's location code (the constant `LAB_MAIN`), this is the final leg
# and the system performs the specimen stability check..."
LAB_LOCATION_CODE: str = "LAB_MAIN"


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3.
# ---------------------------------------------------------------------------
# PRD §2.3: "The `limit` parameter caps the number of items returned and
# defaults to 10 when omitted, with a minimum permitted value of 1 and a
# maximum permitted value of 100."
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
# PRD §2.3: "The `offset` parameter ... defaults to 0; values below 0
# are not accepted."
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Format regexes — PRD §3.1 / §2.13.
# ---------------------------------------------------------------------------
# PRD §3.1: "`mrn` ... must be unique across patients and conform to the
# format of two uppercase letters followed by eight digits."
MRN_REGEX: str = r"^[A-Z]{2}[0-9]{8}$"

# PRD §3.1: "`npi` (the National Provider Identifier, ten digits, unique
# across clinicians)."
NPI_REGEX: str = r"^[0-9]{10}$"

# PRD §3.1: "`code` (a LOINC-style identifier 3 to 20 characters drawn
# from uppercase letters, digits, and underscores; unique across
# panels)."
PANEL_CODE_REGEX: str = r"^[A-Z0-9_]{3,20}$"

# PRD §3.1: "`primary_phone_e164` formatted as a leading `+`, a leading
# non-zero digit, and 6 to 14 further digits."
E164_REGEX: str = r"^\+[1-9][0-9]{6,14}$"


# ---------------------------------------------------------------------------
# Default panel set used by tests.
# ---------------------------------------------------------------------------
# A clock anchor used by all time-sensitive setups. PRD §2.11 / §3.8
# establish the test-driven clock-advance capability.
TEST_DEFAULTS: dict = {
    "CLOCK_ANCHOR": "2026-05-17T10:00:00.000Z",
    # Panel defaults used in basic fixtures.
    "DEFAULT_PANEL_STABILITY_MIN": 120,
    "DEFAULT_PANEL_CODE_PREFIX": "PNL_",
}


# ---------------------------------------------------------------------------
# Audit event types — PRD §3.8 enumeration.
# ---------------------------------------------------------------------------
# PRD §3.8: "an `event_type` drawn from `ORDER_PLACED`,
# `SPECIMEN_REJECTED`, `RESULT_RELEASED`, `CRITICAL_NOTIFIED`,
# `CRITICAL_ACKED`, `CRITICAL_ESCALATED`, `RETEST_ISSUED`, or
# `AMENDMENT_RECORDED`."
AUDIT_EVENT_TYPES: frozenset = frozenset({
    "ORDER_PLACED",
    "SPECIMEN_REJECTED",
    "RESULT_RELEASED",
    "CRITICAL_NOTIFIED",
    "CRITICAL_ACKED",
    "CRITICAL_ESCALATED",
    "RETEST_ISSUED",
    "AMENDMENT_RECORDED",
})


# ---------------------------------------------------------------------------
# Terminal sets used by tests.
# ---------------------------------------------------------------------------
# PRD §3.2 lifecycle: LabOrder reaches RELEASED, CANCELED, REJECTED.
LAB_ORDER_TERMINAL_STATES: frozenset = frozenset(
    {"RELEASED", "CANCELED", "REJECTED"},
)
# PRD §3.4 lifecycle: LabResult terminal is RETRACTED only.
LAB_RESULT_TERMINAL_STATES: frozenset = frozenset({"RETRACTED"})
# PRD §3.3 specimen terminals.
SPECIMEN_TERMINAL_STATES: frozenset = frozenset({"RECEIVED", "REJECTED"})
# PRD §3.5 notification terminals.
NOTIFICATION_TERMINAL_STATES: frozenset = frozenset(
    {"ACKNOWLEDGED", "FAILED"},
)


__all__ = [
    "ACK_WINDOW_ROUTINE_MIN",
    "ACK_WINDOW_STAT_MIN",
    "ESCALATION_EXTENSION_MIN",
    "SEVERITY_HIGH_WEIGHT",
    "SEVERITY_LOW_WEIGHT",
    "SEVERITY_HISTORY_LOOKBACK",
    "SEVERITY_HISTORY_BOOST_PER_PRIOR_CRITICAL",
    "SEVERITY_HISTORY_BASE_FACTOR",
    "STABILITY_STRICT_COMPARISON",
    "LAB_LOCATION_CODE",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "MRN_REGEX",
    "NPI_REGEX",
    "PANEL_CODE_REGEX",
    "E164_REGEX",
    "TEST_DEFAULTS",
    "AUDIT_EVENT_TYPES",
    "LAB_ORDER_TERMINAL_STATES",
    "LAB_RESULT_TERMINAL_STATES",
    "SPECIMEN_TERMINAL_STATES",
    "NOTIFICATION_TERMINAL_STATES",
]
