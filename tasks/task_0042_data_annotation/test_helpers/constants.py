"""Domain thresholds — numeric constants from PRD.

All values traceable to PRD §2.10 (thresholds), §3.6 (pricing/bonus/penalty),
§3.4 (sampling/golden), §3.2 (tier promotion), and §3.5 (timeouts).
"""
from __future__ import annotations


# --- Pagination (PRD §2.3) -------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# --- Project parameter ranges (PRD §3.1) -----------------------------------
PACKAGE_SIZE_MIN = 10
PACKAGE_SIZE_MAX = 500
TIMEOUT_SECONDS_MIN = 60
TIMEOUT_SECONDS_DEFAULT = 86400  # 24 hours
PASS_RATE_TARGET_MIN_EXCLUSIVE = 0.0
PASS_RATE_TARGET_MAX = 1.0
TAX_RATE_MIN = 0.0
TAX_RATE_MAX = 1.0
ENTRY_TEST_SCORE_MIN = 0
ENTRY_TEST_SCORE_MAX = 100


# --- Tier rank ordering (PRD §3.2) -----------------------------------------
TIER_RANK = {"JUNIOR": 1, "SENIOR": 2, "EXPERT": 3}


# --- Tier promotion thresholds (PRD §2.10, §3.2) ---------------------------
EXPERT_PASS_RATE_THRESHOLD = 0.95
EXPERT_GOLDEN_HIT_THRESHOLD = 0.95
EXPERT_MIN_PACKAGES = 50
SENIOR_PASS_RATE_THRESHOLD = 0.85
SENIOR_GOLDEN_HIT_THRESHOLD = 0.85
SENIOR_MIN_PACKAGES = 20

# --- Initial tier from entry-test (PRD §3.2) -------------------------------
INITIAL_TIER_EXPERT_THRESHOLD = 95
INITIAL_TIER_SENIOR_THRESHOLD = 80


# --- Suspension thresholds (PRD §2.10, §3.2) -------------------------------
SUSPEND_PASS_RATE_THRESHOLD = 0.70
SUSPEND_GOLDEN_HIT_THRESHOLD = 0.60


# --- Rolling-pass-rate window (PRD §2.10) ----------------------------------
ROLLING_PASS_RATE_WINDOW = 20

# --- Repeated-dispute pattern (PRD §2.10, §3.6) ----------------------------
REPEATED_DISPUTE_THRESHOLD = 3
DISPUTE_WINDOW_PACKAGES = 20


# --- Pricing and quality (PRD §2.10, §3.6) ---------------------------------
DIFFICULTY_MULTIPLIER = {"EASY": 1.00, "MEDIUM": 1.50, "HARD": 2.00}
TIER_MULTIPLIER = {"JUNIOR": 0.80, "SENIOR": 1.00, "EXPERT": 1.20}

BONUS_BAND = 0.05
PENALTY_BAND = 0.10
BONUS_RATE = 0.10
PENALTY_RATE = 0.20

PENALTY_REJECT_CENTS = 200            # arbitration rejection penalty
PENALTY_APPEAL_REJECTED_CENTS = 100   # rejected-appeal penalty


# --- Sampling and golden insertion (PRD §3.4) ------------------------------
SENIOR_SAMPLE_RATE = 0.30
EXPERT_SAMPLE_RATE = 0.10
GOLDEN_RATIO = 0.05
MAX_DEFECT_RATIO = 0.10


# --- Open preconditions / golden minimum (PRD §2.10, §3.1) -----------------
MIN_GOLDENS = 5


# --- Rework cap (PRD §2.10, §3.4) ------------------------------------------
MAX_REWORK_ROUNDS = 2


# --- Consistency threshold (PRD §3.7) --------------------------------------
CONSISTENCY_LOW_THRESHOLD = 0.50


__all__ = [
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "PACKAGE_SIZE_MIN",
    "PACKAGE_SIZE_MAX",
    "TIMEOUT_SECONDS_MIN",
    "TIMEOUT_SECONDS_DEFAULT",
    "PASS_RATE_TARGET_MIN_EXCLUSIVE",
    "PASS_RATE_TARGET_MAX",
    "TAX_RATE_MIN",
    "TAX_RATE_MAX",
    "ENTRY_TEST_SCORE_MIN",
    "ENTRY_TEST_SCORE_MAX",
    "TIER_RANK",
    "EXPERT_PASS_RATE_THRESHOLD",
    "EXPERT_GOLDEN_HIT_THRESHOLD",
    "EXPERT_MIN_PACKAGES",
    "SENIOR_PASS_RATE_THRESHOLD",
    "SENIOR_GOLDEN_HIT_THRESHOLD",
    "SENIOR_MIN_PACKAGES",
    "INITIAL_TIER_EXPERT_THRESHOLD",
    "INITIAL_TIER_SENIOR_THRESHOLD",
    "SUSPEND_PASS_RATE_THRESHOLD",
    "SUSPEND_GOLDEN_HIT_THRESHOLD",
    "ROLLING_PASS_RATE_WINDOW",
    "REPEATED_DISPUTE_THRESHOLD",
    "DISPUTE_WINDOW_PACKAGES",
    "DIFFICULTY_MULTIPLIER",
    "TIER_MULTIPLIER",
    "BONUS_BAND",
    "PENALTY_BAND",
    "BONUS_RATE",
    "PENALTY_RATE",
    "PENALTY_REJECT_CENTS",
    "PENALTY_APPEAL_REJECTED_CENTS",
    "SENIOR_SAMPLE_RATE",
    "EXPERT_SAMPLE_RATE",
    "GOLDEN_RATIO",
    "MAX_DEFECT_RATIO",
    "MIN_GOLDENS",
    "MAX_REWORK_ROUNDS",
    "CONSISTENCY_LOW_THRESHOLD",
]
