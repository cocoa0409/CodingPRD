"""Domain thresholds, tuned constants and canonical fixture literals.

Every numeric constant here is stated by the PRD; the canonical instants and
payload literals below are the shared scenario baseline the fixtures build from.
"""

# ─── Logical clock ────────────────────────────────────────────────────────────

#: The logical clock before any client has moved it.
CLOCK_EPOCH_START = "2026-08-01T00:00:00Z"

# ─── Rotating barcode ─────────────────────────────────────────────────────────

BARCODE_ROTATION_SECONDS = 30
#: One epoch of skew tolerance below the current index.
SKEW_TOLERANCE_EPOCHS = 1

# ─── Zone posture ─────────────────────────────────────────────────────────────

RESTRICTED_RATIO = 0.90
FROZEN_RATIO = 1.00

# ─── Resale price cap ─────────────────────────────────────────────────────────

STATUTORY_CAP_PCT = 0.10
VENUE_POLICY_CAP_PCT = 0.30
MAX_ABS_MARKUP_CENTS = 2500

# ─── Resale settlement split ──────────────────────────────────────────────────

PLATFORM_FEE_PCT = 0.0725
VENUE_ROYALTY_PCT = 0.0350
PROCESSING_FEE_PCT = 0.0290
PROCESSING_FIXED_CENTS = 30

# ─── Denied-entry remediation credit ──────────────────────────────────────────

GOODWILL_TIER1_CENTS = 5000
GOODWILL_TIER2_CENTS = 15000
GOODWILL_TIER1_PCT = 0.10
GOODWILL_TIER2_PCT = 0.15
GOODWILL_TIER3_PCT = 0.20
STRIKE_PENALTY_CENTS = 500
STRIKE_PENALTY_CAP_CENTS = 2000

# ─── Fraud risk scoring ───────────────────────────────────────────────────────

DEVICE_CHURN_WEIGHT = 4
REMEDIATED_DISCOUNT = 0.5
SCORE_CAP = 100
#: Commercial activity requires a score strictly below this value.
FRAUD_BLOCK_THRESHOLD = 40

CATEGORY_WEIGHTS = {
    "COUNTERFEIT": 50,
    "DEVICE_MISMATCH": 45,
    "UNAUTHORIZED_RESALE": 30,
    "DUPLICATE": 20,
    "ZONE_VIOLATION": 15,
}

# ─── Re-entry lockout ─────────────────────────────────────────────────────────

RE_ENTRY_LOCKOUT_SECONDS = 120

# ─── Credential distribution ──────────────────────────────────────────────────

MIN_CREDENTIAL_QUANTITY = 1
MAX_CREDENTIAL_QUANTITY = 50
#: Resubmission requires revision_count strictly below this value.
MAX_CREDENTIAL_REVISIONS = 2

# ─── Reconciliation ───────────────────────────────────────────────────────────

MAX_VARIANCE_PCT = 2.00

# ─── Pagination ───────────────────────────────────────────────────────────────

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ─── Canonical scenario instants ──────────────────────────────────────────────

#: The anchor every canonical event fixes barcode epochs from.
BARCODE_ANCHOR_AT = "2026-09-12T18:00:00Z"
DOORS_OPEN_AT = "2026-09-12T18:00:00Z"
EVENT_START_AT = "2026-09-12T19:00:00Z"
TRANSFER_WINDOW_CLOSES_AT = "2026-09-12T17:00:00Z"

#: Instants used repeatedly by the scan scenarios, with their epoch indices
#: relative to BARCODE_ANCHOR_AT.
#: One second before TRANSFER_WINDOW_CLOSES_AT, the last instant a handover is allowed.
T_16_59_59 = "2026-09-12T16:59:59Z"

#: Three instants a scanner cache was recorded at while the uplink was down;
#: all three fall inside epoch 18.
T_18_09_00 = "2026-09-12T18:09:00Z"   # epoch 18
T_18_09_10 = "2026-09-12T18:09:10Z"   # epoch 18
T_18_09_20 = "2026-09-12T18:09:20Z"   # epoch 18

T_18_10_00 = "2026-09-12T18:10:00Z"   # epoch 20
T_18_10_30 = "2026-09-12T18:10:30Z"   # epoch 21
T_18_11_00 = "2026-09-12T18:11:00Z"   # epoch 22
T_18_12_00 = "2026-09-12T18:12:00Z"   # epoch 24
T_18_12_30 = "2026-09-12T18:12:30Z"   # epoch 25
T_18_12_31 = "2026-09-12T18:12:31Z"   # epoch 25
T_18_15_00 = "2026-09-12T18:15:00Z"   # epoch 30
T_18_20_00 = "2026-09-12T18:20:00Z"   # epoch 40

EPOCH_AT_18_09_00 = 18
EPOCH_AT_18_10_00 = 20
EPOCH_AT_18_10_30 = 21
EPOCH_AT_18_11_00 = 22
EPOCH_AT_18_12_00 = 24
EPOCH_AT_18_12_30 = 25

# ─── Canonical operator identifiers ───────────────────────────────────────────

ADMIN_USER_ID = "admin-1"
AGENT_USER_ID = "boa-1"
AGENT_2_USER_ID = "boa-2"
APPROVER_USER_ID = "appr-1"
GATE_OPERATOR_USER_ID = "gate-op-1"
INVESTIGATOR_USER_ID = "sec-1"
