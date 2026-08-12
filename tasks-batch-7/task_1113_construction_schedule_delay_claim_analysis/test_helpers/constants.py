"""Domain thresholds and default values from the PRD (§2.4, §2.10, §3)."""

# PRD §2.4: at startup the logical clock reads 2026-05-01T00:00:00Z.
DEFAULT_STARTUP_CLOCK = "2026-05-01T00:00:00Z"

# PRD §2.10: contract doctrine defaults applied at project creation when omitted.
DEFAULT_FLOAT_OWNERSHIP_POLICY = "CONTRACTOR_OWNS"
DEFAULT_NOTICE_WINDOW_DAYS = 21

# PRD §3.2 / §3.4: percent_complete ranges 0..100 inclusive.
PERCENT_COMPLETE_MIN = 0
PERCENT_COMPLETE_MAX = 100

# PRD §3.6: an appeal is allowed only while the submission_round is below 3.
EOT_APPEAL_ROUND_CAP = 3

TEST_DEFAULTS = {
    "PROJECT_NAME": "Test Project",
    "CONTRACT_START_DATE": "2026-05-01T00:00:00Z",
    "CONTRACT_COMPLETION_DATE": "2026-06-30T00:00:00Z",
    "LD_DAILY_RATE_CENTS": 100000,
    "LD_CAP_CENTS": 1000000,
    "BASELINE_DATA_DATE": "2026-05-01T00:00:00Z",
    "ACTIVITY_DURATION_DAYS": 5,
}
