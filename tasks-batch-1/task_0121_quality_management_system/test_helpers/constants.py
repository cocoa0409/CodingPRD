"""Domain thresholds — numeric constants from the PRD calculations and rules."""

# --- Cost of quality (PRD 3.3 / 2.5) ---
LABOUR_RATE_CENTS_PER_HOUR = 6000
USE_AS_IS_CONCESSION_PCT = 0.30
HANDLING_PCT = 0.10
SEVERITY_WEIGHT = {"CRITICAL": 1.5, "MAJOR": 1.0, "MINOR": 0.5}

# --- Supplier quality rating (PRD 3.7) ---
W_LOT = 0.6
W_NCR = 0.4
NCR_PENALTY = 0.10
SCAR_PENALTY_STEP = 0.05
SCAR_PENALTY_CAP = 0.20
APPROVE_AT = 70.00
PROBATION_AT = 50.00

# --- CAPA effectiveness gates (PRD 3.4) ---
PROVISIONAL_VERIFY_GATE = 0.50
FINAL_CLOSE_GATE = 0.80

# --- Auditor double-booking buffer (PRD 3.8) ---
AUDITOR_BUFFER_HOURS = 24

# --- AQL tightening switch (PRD 3.6) ---
TIGHTEN_AT_CONSECUTIVE_REJECTS = 2

# --- AQL single-sampling lookup table (PRD 3.6) ---
# (code_letter, aql_column) -> {"n": sample_size, "Ac": acceptance_number}
AQL_LOOKUP = {
    ("D", 1.0): {"n": 8, "Ac": 0},
    ("E", 1.0): {"n": 13, "Ac": 0},
    ("F", 1.0): {"n": 20, "Ac": 0},
    ("G", 1.0): {"n": 32, "Ac": 1},
    ("H", 1.0): {"n": 50, "Ac": 1},
    ("D", 2.5): {"n": 8, "Ac": 0},
    ("E", 2.5): {"n": 13, "Ac": 1},
    ("F", 2.5): {"n": 20, "Ac": 1},
    ("G", 2.5): {"n": 32, "Ac": 2},
    ("H", 2.5): {"n": 50, "Ac": 3},
    ("D", 4.0): {"n": 8, "Ac": 1},
    ("E", 4.0): {"n": 13, "Ac": 1},
    ("F", 4.0): {"n": 20, "Ac": 2},
    ("G", 4.0): {"n": 32, "Ac": 3},
    ("H", 4.0): {"n": 50, "Ac": 5},
}

# Test default knobs used by factories/fixtures.
TEST_DEFAULTS = {
    "DEFAULT_LOT_SIZE": 120,   # band 91..150 -> code letter F under GII
    "DEFAULT_AQL_PCT": 4.0,
    "DEFAULT_LEVEL": "GII",
    "DEFAULT_DUE_AT": "2026-09-01T00:00:00Z",
}
