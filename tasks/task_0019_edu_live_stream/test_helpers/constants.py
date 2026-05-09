"""Domain thresholds and numeric constants from PRD calculation rules.

All values trace back to PRD §2.9, §3.4, §3.5, §3.7, §3.8.
"""

# ──────────────────────────────────────────────────────────
# Refund tier thresholds and deductions (PRD §3.7)
# ──────────────────────────────────────────────────────────

# Tier-1 (full refund) boundaries: days_elapsed <= 7 AND progress <= 5.0
FULL_REFUND_DAYS = 7
FULL_REFUND_PROGRESS = 5.0

# Tier-2 (mid refund, ratio 0.70) boundaries: days_elapsed <= 30 AND progress <= 30.0
MID_REFUND_DAYS = 30
MID_REFUND_PROGRESS = 30.0

# Tier-3 (late refund, ratio 0.30) boundary: progress <= 60.0
LATE_REFUND_PROGRESS = 60.0

# Refund ratios per tier
RATIO_FULL = 1.00
RATIO_MID = 0.70
RATIO_LATE = 0.30
RATIO_NONE = 0.00

# Per-kit / per-attended-class deductions (cents)
MATERIALS_KIT_DEDUCTION_CENTS = 5000          # $50.00 per kit
SERVICE_PER_LIVE_CLASS_CENTS = 1500           # $15.00 per attended live class


# ──────────────────────────────────────────────────────────
# Pricing (PRD §3.6)
# ──────────────────────────────────────────────────────────

MAX_DISCOUNT_PERCENT = 80
MIN_DISCOUNT_PERCENT = 0


# ──────────────────────────────────────────────────────────
# At-risk evaluation (PRD §3.5)
# ──────────────────────────────────────────────────────────

AT_RISK_PROGRESS_THRESHOLD = 30.0
AT_RISK_ATTENDANCE_THRESHOLD = 70.0
AT_RISK_DAYS_THRESHOLD = 14
SECONDS_PER_DAY = 86400


# ──────────────────────────────────────────────────────────
# Live class scheduling (PRD §3.3)
# ──────────────────────────────────────────────────────────

ROOM_BUFFER_SECONDS = 600        # 10-minute post-buffer on existing room sessions
CHECKIN_OPEN_LEAD_SECONDS = 900  # 15-minute lead window before start_ts
LATE_BOUNDARY_SECONDS = 1800     # 30-minute late-vs-window-closed boundary
START_LEAD_SECONDS = 600         # start may not fire earlier than start_ts - 600


# ──────────────────────────────────────────────────────────
# Assignment / submission (PRD §3.8)
# ──────────────────────────────────────────────────────────

REVISION_CAP = 3                 # request-revision rejected when revision_count == 3


# ──────────────────────────────────────────────────────────
# Test defaults — only the values that fixtures reuse across many tests
# ──────────────────────────────────────────────────────────

TEST_DEFAULTS = {
    "LIST_PRICE_CENTS": 100000,         # $1000.00 — round number for tier maths
    "DISCOUNT_PERCENT": 0,
    "CHAPTER_VIDEO_SECONDS": 1000,
    "ASSIGNMENT_MAX_SCORE": 100,
    "CLASS_GROUP_CAPACITY": 50,
}
