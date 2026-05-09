"""Domain constants and thresholds for the Research Funding API.

All numeric thresholds and rate tables come from PRD §3 (workflows) and §3.6–§3.8
(execution rates, residual-fund policy, indirect-cost allocation).
"""

# --- Indirect-cost rate table (PRD §3.8 Step 2) ---
RATE_TABLE = {
    "NATIONAL":   {"DIRECT_COST": 0.20, "PERSONNEL_COST": 0.25, "FLOOR_AREA": 0.15},
    "PROVINCIAL": {"DIRECT_COST": 0.15, "PERSONNEL_COST": 0.18, "FLOOR_AREA": 0.12},
    "ENTERPRISE": {"DIRECT_COST": 0.10, "PERSONNEL_COST": 0.12, "FLOOR_AREA": 0.08},
    "INTERNAL":   {"DIRECT_COST": 0.05, "PERSONNEL_COST": 0.06, "FLOOR_AREA": 0.04},
}

# Threshold tier reduction — if total_budget > LARGE_PROJECT_THRESHOLD, rate -= 0.02 (floor 0.0)
LARGE_PROJECT_THRESHOLD = 1_000_000

# Global indirect pool ceiling (PRD §3.8 Step 3)
GLOBAL_INDIRECT_POOL = 5_000_000

# --- Source abbreviations for project_code minting (PRD §3.1) ---
SOURCE_ABBR = {
    "NATIONAL": "NTL",
    "PROVINCIAL": "PRV",
    "ENTERPRISE": "ENT",
    "INTERNAL": "INT",
}

# --- Residual fund policy (PRD §3.7) ---
# Lambdas removed for simplicity — used only for documentation/cross-checking.
# NATIONAL: RETURN ok; REALLOCATE no; CARRYOVER iff er >= 0.95
# PROVINCIAL: RETURN ok; REALLOCATE no; CARRYOVER iff er >= 0.90
# ENTERPRISE: RETURN no; REALLOCATE ok; CARRYOVER always
# INTERNAL: RETURN ok; REALLOCATE ok; CARRYOVER always
RESIDUAL_POLICY = {
    "NATIONAL":   {"RETURN": True,  "REALLOCATE": False, "CARRYOVER_THRESHOLD": 0.95},
    "PROVINCIAL": {"RETURN": True,  "REALLOCATE": False, "CARRYOVER_THRESHOLD": 0.90},
    "ENTERPRISE": {"RETURN": False, "REALLOCATE": True,  "CARRYOVER_THRESHOLD": None},  # None = always allowed
    "INTERNAL":   {"RETURN": True,  "REALLOCATE": True,  "CARRYOVER_THRESHOLD": None},
}

# --- Approval / review limits (PRD §3.1, §3.3) ---
MIN_PEER_REVIEWS_FOR_APPROVAL = 3
MAX_REWORK_COUNT = 3                    # rework_count is capped at 3; the 4th attempt (or rework_count==4 already) is blocked
MIN_PROPOSAL_LENGTH = 200               # PRD §3.1 ERR_PROPOSAL_TOO_SHORT
MIN_JUSTIFICATION_LENGTH = 20           # PRD §3.2 ERR_JUSTIFICATION_TOO_SHORT
PROJECT_TITLE_MIN = 1
PROJECT_TITLE_MAX = 200

# --- Zero-sum tolerance for budget adjustments (PRD §3.2) ---
ZERO_SUM_TOLERANCE = 0.01

# --- Pagination defaults (PRD §2.3) ---
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
MIN_OFFSET = 0

# --- Precision policy (PRD §2.8) ---
MONETARY_DECIMALS = 2
RATE_DECIMALS = 4

# --- Compliance rule codes (PRD §3.4) ---
RULE_PER_DIEM_CAP = "PER_DIEM_CAP"
RULE_EQUIP_THRESHOLD = "EQUIP_THRESHOLD"
RULE_COI = "COI"
RULE_SOLE_SOURCE_JUSTIFICATION = "SOLE_SOURCE_JUSTIFICATION"
