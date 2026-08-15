"""Domain thresholds and the canonical logical-clock timeline (PRD §2.6, §3).

Every value below is pinned by PRD prose: fiscal constants from §3.3, the
revision cap and reliability basis points from §3.4/§3.5, window widths from
§2.6/§3.6, and the default season knobs from §3.1.
"""

# --- fiscal constants (PRD §3.3) ---
INVOICE_DUE_HOURS = 72
LATE_WINDOW_HOURS = 48
WITHDRAWAL_FEE_CENTS = 2500
EARLY_BIRD_LATE_CANCEL_CENTS = 5000

# --- entrant standing (PRD §3.3) ---
BARRED_THRESHOLD = 3

# --- entry revision loop (PRD §3.4) ---
MAX_REVISIONS = 2

# --- materials (PRD §3.2) ---
MAX_MATERIAL_BYTES = 104857600  # 100 MiB

# --- scoring (PRD §2.8, §3.5, §3.6) ---
SCORING_ROUND_GAP_HOURS = 12
RUBRIC_WEIGHT_SUM_BP = 10000
RELIABILITY_FULL_BP = 10000

# --- season defaults (PRD §3.1) ---
DEFAULT_ACK_WINDOW_HOURS = 72
DEFAULT_GO_LIVE_LEAD_MINUTES = 30
DEFAULT_MAX_APPEALS_PER_ENTRY = 2

# --- canonical logical-clock instants (UTC) ---
T_GENESIS = "2026-08-01T00:00:00Z"  # server default clock before any set (PRD §2.6)
T_SUBMISSION_OPEN = "2026-08-10T00:00:00Z"
T_EARLY_FEE_END = "2026-08-20T00:00:00Z"
T_SUBMISSION_CLOSE = "2026-09-01T00:00:00Z"
T_LATE_SECOND = "2026-09-01T00:00:01Z"  # one second into the late window
T_AFTER_CLOSE = "2026-09-02T00:00:00Z"
T_LATE_WINDOW_END = "2026-09-03T00:00:00Z"  # submission_closes_at + 48h exactly
T_AFTER_LATE_WINDOW = "2026-09-05T00:00:00Z"
T_EMBARGO_LIFT = "2026-10-01T18:00:00Z"
T_AFTER_EMBARGO_LIFT = "2026-10-01T18:00:01Z"
T_CEREMONY = "2026-10-01T19:00:00Z"
T_CEREMONY_END = "2026-10-01T22:00:00Z"

# --- eligibility window (PRD §3.1) ---
ELIGIBILITY_START = "2026-01-01T00:00:00Z"
ELIGIBILITY_END = "2026-08-01T00:00:00Z"
WORK_COMPLETED = "2026-06-01T00:00:00Z"

# --- canonical rubric: weights sum to exactly 10000 bp (PRD §2.8) ---
STANDARD_RUBRIC = [
    {"criterion_code": "CRAFT", "weight_bp": 6000, "max_score": 10},
    {"criterion_code": "IMPACT", "weight_bp": 4000, "max_score": 5},
]

# --- canonical fee tiers in integer cents ---
EARLY_FEE_CENTS = 10000
STANDARD_FEE_CENTS = 15000
LATE_FEE_CENTS = 20000

# --- round windows honouring the 12h minimum-gap rule (PRD §3.6) ---
R1_WINDOW = ("2026-09-05T00:00:00Z", "2026-09-07T00:00:00Z")
R2_WINDOW = ("2026-09-07T12:00:00Z", "2026-09-09T00:00:00Z")
R3_WINDOW = ("2026-09-12T00:00:00Z", "2026-09-14T00:00:00Z")

# Genesis hash-chain predecessor (PRD §2.11)
GENESIS_HASH_PREV = "0" * 64
