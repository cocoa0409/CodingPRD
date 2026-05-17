"""Domain thresholds — numeric constants used by tests.

Each constant traces back to a verbatim sentence in PRD.md.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Medicare cap thresholds — PRD §2.8.
# ---------------------------------------------------------------------------
# PRD §2.8: "the KX threshold is 241,000 cents ($2,410.00), the 2026
# Medicare PT/SLP soft cap; the hard cap is 300,000 cents ($3,000.00),
# the targeted-medical-review threshold above which signs are rejected."
KX_THRESHOLD_CENTS: int = 241_000
CAP_HARD_CENTS: int = 300_000


# ---------------------------------------------------------------------------
# 8-Minute Rule — PRD §3.5.
# ---------------------------------------------------------------------------
# PRD §3.5: "when timed_minutes is strictly less than 8 the billed
# units are 0; otherwise the billed units are equal to the integer
# division of (timed_minutes minus 8) by 15, plus 1."
MIN_TIMED_MIN: int = 8
BAND_WIDTH_MIN: int = 15


# ---------------------------------------------------------------------------
# Visit per-unit rates — PRD §3.5.
# ---------------------------------------------------------------------------
# PRD §3.5: "the per-unit rate keyed to the signing therapist's
# credential — 4,200 cents per unit when the credential is PT or DPT,
# 3,500 cents per unit when the credential is PTA."
RATE_PT_DPT_CENTS: int = 4_200
RATE_PTA_CENTS: int = 3_500


# ---------------------------------------------------------------------------
# Evaluation surcharge — PRD §3.5 / §3.3.
# ---------------------------------------------------------------------------
# PRD §3.5: "the system adds the evaluation surcharge for that
# evaluation's complexity — 5,000 cents for LOW, 7,500 cents for
# MODERATE, 10,500 cents for HIGH."
EVAL_LOW_CENTS: int = 5_000
EVAL_MODERATE_CENTS: int = 7_500
EVAL_HIGH_CENTS: int = 10_500


# ---------------------------------------------------------------------------
# Plan of Care certification window — PRD §3.3.
# ---------------------------------------------------------------------------
# PRD §3.3: "The window must not exceed 90 days from start to end."
CERT_PERIOD_MAX_DAYS: int = 90


# ---------------------------------------------------------------------------
# Reevaluation cadence — PRD §3.6.
# ---------------------------------------------------------------------------
# PRD §3.6: "When the test clock is advanced and the gap reaches 30
# days or more on an ACTIVE episode, the episode is swept to
# REEVAL_DUE."
REEVAL_DUE_DAYS: int = 30


# ---------------------------------------------------------------------------
# Functional score range — PRD §3.2.
# ---------------------------------------------------------------------------
# PRD §3.2: "the patient's functional_baseline_score on a 0-to-100
# scale"; "the supplied functional_baseline_score is between 0 and 100
# inclusive".
FUNCTIONAL_SCORE_MIN: int = 0
FUNCTIONAL_SCORE_MAX: int = 100


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3.
# ---------------------------------------------------------------------------
# PRD §2.3: "limit ... defaulting to 10 with a minimum of 1 and a
# maximum of 100; offset ... defaulting to 0 with a minimum of 0."
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# MIPS measure codes — PRD §3.8.
# ---------------------------------------------------------------------------
MIPS_MEASURE_CODES: tuple = (
    "Q126_PAIN_ASSESSMENT",
    "Q127_FUNCTIONAL_STATUS",
    "Q128_FALL_RISK_SCREEN",
)


# ---------------------------------------------------------------------------
# Test defaults — convenient values used by fixtures.
# ---------------------------------------------------------------------------
TEST_DEFAULTS: dict = {
    # PRD §3.10: simulated clock anchor for time-sensitive setups.
    "CLOCK_ANCHOR": "2026-06-01T10:00:00.000Z",
    # Default authorization unit_quota — large enough not to be the
    # binding constraint in basic fixtures.
    "DEFAULT_UNIT_QUOTA": 60,
    # Default planned_visit_count / planned_units_per_visit — yields
    # capped projection 20*3*4200 + surcharge.
    "DEFAULT_PLANNED_VISIT_COUNT": 20,
    "DEFAULT_PLANNED_UNITS_PER_VISIT": 3,
}


__all__ = [
    "KX_THRESHOLD_CENTS",
    "CAP_HARD_CENTS",
    "MIN_TIMED_MIN",
    "BAND_WIDTH_MIN",
    "RATE_PT_DPT_CENTS",
    "RATE_PTA_CENTS",
    "EVAL_LOW_CENTS",
    "EVAL_MODERATE_CENTS",
    "EVAL_HIGH_CENTS",
    "CERT_PERIOD_MAX_DAYS",
    "REEVAL_DUE_DAYS",
    "FUNCTIONAL_SCORE_MIN",
    "FUNCTIONAL_SCORE_MAX",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "MIPS_MEASURE_CODES",
    "TEST_DEFAULTS",
]
