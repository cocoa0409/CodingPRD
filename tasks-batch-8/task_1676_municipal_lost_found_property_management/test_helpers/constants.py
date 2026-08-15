"""Domain thresholds and constants from the PRD's calculation rules (§2.5, §3)."""

# Logical clock startup default (PRD §2.5).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Value-tier boundaries in cents (PRD §3.2: "a declared value below 10,000 cents
# is LOW; ... at least 10,000 cents but below 100,000 cents is MID; ... 100,000
# cents or more is HIGH").
TIER_LOW_MAX_EXCLUSIVE = 10000
TIER_MID_MAX_EXCLUSIVE = 100000

# Claim proof-score weights and approval thresholds (PRD §3.4).
PROOF_WEIGHTS = {
    "W_ID_VERIFIED": 30,
    "W_SERIAL": 30,
    "W_PHOTO": 15,
    "W_DETAIL": 15,
    "W_RECEIPT": 10,
}
APPROVAL_THRESHOLDS = {"LOW": 40, "MID": 60, "HIGH": 80}

# Lot floor-price rates per value tier (PRD §3.8).
FLOOR_RATES = {"LOW": 0.10, "MID": 0.20, "HIGH": 0.30}

# Auction settlement commission tiers keyed on gross proceeds (PRD §3.8).
COMMISSION_TIER1_MAX = 1000000
COMMISSION_TIER2_MAX = 5000000
COMMISSION_RATES = {"TIER1": 0.10, "TIER2": 0.08, "TIER3": 0.06}

# Inquiry response deadlines (PRD §3.3).
TRANSIT_SLA_HOURS = 24
FACILITY_SLA_HOURS = 72

# Unsold escalation: an item whose unsold_count reaches 2 escalates to disposal
# (PRD §3.8).
MAX_UNSOLD_CYCLES = 2

# Common instants used across tests.
FOUND_AT = "2026-08-01T09:00:00Z"
EVENT_STARTS_AT = "2026-08-20T10:00:00Z"
EVENT_ENDS_AT = "2026-08-20T12:00:00Z"
AFTER_EVENT_END = "2026-08-21T00:00:00Z"

# Deterministic operator identifiers (opaque X-User-ID values per PRD §2.1).
OPERATOR_IDS = {
    "intake_officer": "officer-intake-1",
    "custodian": "custodian-1",
    "examiner": "examiner-1",
    "examiner_other": "examiner-9",
    "release_officer": "officer-release-1",
    "liaison": "liaison-1",
    "coordinator": "coord-1",
    "coordinator_other": "coord-2",
    "admin": "admin-1",
}
