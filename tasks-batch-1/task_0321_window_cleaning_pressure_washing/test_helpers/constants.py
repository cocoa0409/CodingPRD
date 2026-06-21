"""Domain thresholds — numeric constants from the PRD's pricing and charging rules.

All monetary values are whole integer cents (PRD §2.6).
Generic NON_EXISTENT_UUID comes from the framework.
"""

# ─── Quote base pricing (PRD §3.1) ───────────────────────────────────────
PANE_RATE_T1_CENTS = 300       # first 20 panes
PANE_RATE_T2_CENTS = 250       # panes 21..50
PANE_RATE_T3_CENTS = 200       # panes 51+
SQFT_RATE_CENTS = 90           # per whole sq-ft (area rounded up first)
MIN_JOB_CENTS = 9900           # job-minimum floor on the base
HIGH_RISE_STORY_THRESHOLD = 3  # stories >= 3 → high-rise surcharge
HIGH_RISE_SURCHARGE_PCT = 0.20

# ─── Add-on pricing (PRD §3.1 / §3.5) ────────────────────────────────────
GUTTER_FLAT_CENTS = 7500
SCREEN_PER_PANE_CENTS = 150
SOFT_WASH_RATE_CENTS = 25
SOFT_WASH_MIN_CENTS = 12000

# ─── Deposit requirement (PRD §3.1) ──────────────────────────────────────
DEPOSIT_THRESHOLD_CENTS = 30000   # quoted_total >= threshold → deposit required
DEPOSIT_PCT = 0.25

# ─── Visit charge discount (PRD §3.5) ────────────────────────────────────
RESCHEDULE_DISCOUNT_THRESHOLD = 2   # reschedule_count >= 2 → discount applies
RESCHEDULE_DISCOUNT_PCT = 0.10

# ─── Re-clean credit (PRD §3.8) ──────────────────────────────────────────
AFTER_PHOTO_DOC_THRESHOLD = 2   # >= 2 AFTER photos → partial; exactly 1 → full
PARTIAL_CREDIT_PCT = 0.50

# ─── Pagination (PRD §2.3) ───────────────────────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
