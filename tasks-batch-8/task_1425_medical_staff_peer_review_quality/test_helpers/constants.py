"""Domain thresholds and logical-clock landmarks (PRD §2.5, §3.2, §3.5, §3.6, §3.8)."""

# PRD §2.5: at startup the logical clock reads exactly this instant.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# PRD §3.5/§3.6: response_deadline = sent_at + 14 days exactly.
RESPONSE_WINDOW_DAYS = 14
# With a notification sent at the default clock, the deadline lands here.
DEFAULT_SENT_DEADLINE = "2026-08-15T00:00:00Z"
# One second and one day past that deadline.
DEADLINE_PLUS_ONE_SECOND = "2026-08-15T00:00:01Z"
AFTER_DEADLINE = "2026-08-16T00:00:00Z"

# PRD §3.2: referral cooldown of thirty days after a SCREENED_OUT terminal event.
REFERRAL_COOLDOWN_DAYS = 30
COOLDOWN_DAY_29 = "2026-08-30T00:00:00Z"
COOLDOWN_DAY_30 = "2026-08-31T00:00:00Z"

# PRD §3.8: trailing trend window of 365 days.
TREND_WINDOW_DAYS = 365

# PRD §3.3: per-case cap of three non-WAIVED assignments.
MAX_NON_WAIVED_ASSIGNMENTS = 3

# PRD §3.4: reviewer scores are integers from 1 to 5.
SCORE_MIN = 1
SCORE_MAX = 5

# PRD §3.8: focused-review trigger thresholds.
TRIGGER_CASE_COUNT = 3
TRIGGER_AVG_BELOW = 3.0
TRIGGER_MAJOR_OFI_COUNT = 1
TRIGGER_UNACCEPTABLE_COUNT = 1

# PRD §3.5: a deliberation needs three SUBMITTED reviewers; quorum needs two of
# them in a focus group when the subject is under an ACTIVE focused review.
ASSIGNMENTS_PER_CASE = 3
FOCUS_PANEL_QUORUM = 2

# Default intake timestamp used by fixtures (comfortably before the default clock).
DEFAULT_REFERRED_AT = "2026-07-20T00:00:00Z"
