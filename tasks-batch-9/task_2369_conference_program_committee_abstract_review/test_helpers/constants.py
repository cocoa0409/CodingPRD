"""Numeric constants and thresholds taken from the PRD's stated formulas."""

# ─── Rubric roll-up for a single review ──────────────────────────────────
RUBRIC_WEIGHTS = {
    "WEIGHT_ORIGINALITY": 0.40,
    "WEIGHT_METHODOLOGY": 0.30,
    "WEIGHT_CLARITY": 0.15,
    "WEIGHT_RELEVANCE": 0.15,
}
SCORE_FLOOR = 1.00
SCORE_CEILING = 5.50

# ─── Consensus score ─────────────────────────────────────────────────────
CONFIDENCE_WEIGHT = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}

# ─── Score spread / discrepancy ──────────────────────────────────────────
MIN_REVIEWS_FOR_SPREAD = 2
OUTLIER_TRIM_COUNT = 1

# ─── Reviewer selector ───────────────────────────────────────────────────
MIN_MATCH_SCORE = 0.2500

# ─── Format capacity waterfall ───────────────────────────────────────────
WATERFALL_ORDER = ["ORAL", "POSTER"]
WORKSHOP_DOWNGRADABLE = False

# ─── CME credit award ────────────────────────────────────────────────────
MINUTES_PER_QUARTER_CREDIT = 15
CREDIT_STEP = 0.25

# ─── Program change fee ──────────────────────────────────────────────────
BASE_FEE_CENTS = {
    "MOVE": 4000,
    "SWAP": 6000,
    "SUBSTITUTE_PRESENTER": 2500,
    "WITHDRAW": 0,
}
ESTIMATE_RUSH_PCT = {"far": 0, "near": 10, "imminent": 25}
FINAL_RUSH_PCT = {"far": 0, "near": 20, "imminent": 50}
NEAR_DAYS_LOWER = 7
FAR_DAYS_LOWER = 14
POST_FREEZE_SURCHARGE_CENTS = 1500

# ─── Reviewer load ledger ────────────────────────────────────────────────
LOAD_STEP = 1

# ─── Session packing and interval semantics ──────────────────────────────
CHANGEOVER_MINUTES = 5
SESSION_BUFFER_MINUTES = 10
ROOM_TURNAROUND_MINUTES = 0
CHAIR_TURNAROUND_MINUTES = 15
PRESENTER_GAP_MINUTES = 0

THRESHOLDS = {
    "SCORE_FLOOR": SCORE_FLOOR,
    "SCORE_CEILING": SCORE_CEILING,
    "MIN_MATCH_SCORE": MIN_MATCH_SCORE,
    "MINUTES_PER_QUARTER_CREDIT": MINUTES_PER_QUARTER_CREDIT,
    "CREDIT_STEP": CREDIT_STEP,
    "POST_FREEZE_SURCHARGE_CENTS": POST_FREEZE_SURCHARGE_CENTS,
    "NEAR_DAYS_LOWER": NEAR_DAYS_LOWER,
    "FAR_DAYS_LOWER": FAR_DAYS_LOWER,
    "CHANGEOVER_MINUTES": CHANGEOVER_MINUTES,
    "SESSION_BUFFER_MINUTES": SESSION_BUFFER_MINUTES,
    "CHAIR_TURNAROUND_MINUTES": CHAIR_TURNAROUND_MINUTES,
    "LOAD_STEP": LOAD_STEP,
}

# ─── Shared calendar used by the composite fixtures ──────────────────────
# The logical clock defaults to 2026-08-01T00:00:00Z, so every fixture sets it
# explicitly before building state.
CLOCK_BEFORE_DEADLINES = "2026-01-05T00:00:00Z"

CONFERENCE_CALENDAR = {
    "event_start_utc": "2026-09-01T08:00:00Z",
    "event_end_utc": "2026-09-03T18:00:00Z",
    "abstract_deadline_utc": "2026-03-01T23:59:00Z",
    "review_deadline_utc": "2026-05-01T23:59:00Z",
    "program_freeze_utc": "2026-08-15T00:00:00Z",
}

TEST_DEFAULTS = {
    "CONFERENCE_NAME": "Global Oncology Summit 2026",
    "CONFERENCE_CODE": "GOS26",
    "CATEGORY_CODE": "EDU",
    "CATEGORY_NAME": "Education Research",
    "MAX_WORD_COUNT": 300,
    "CME_MINUTES_POOL_TOTAL": 600,
    "ABSTRACT_KEYWORDS": ["oncology", "immunotherapy"],
    "REVIEWER_KEYWORDS": ["oncology", "immunotherapy"],
}
