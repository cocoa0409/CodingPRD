"""Domain thresholds and numeric constants from the PRD's calculation rules."""

# Logical clock default (PRD: before any clock-setting call the clock reads
# exactly 2026-05-01T00:00:00Z).
DEFAULT_CLOCK = "2026-05-01T00:00:00Z"

# Queue priority score (PRD Section 3.2)
PRIORITY = {
    "TIER_MAX_POINTS": 100,        # aging tier top value (11+ days)
    "AMOUNT_CAP": 30,              # charge component cap
    "AMOUNT_CHUNK_CENTS": 100000,  # one point per whole 100000-cent block
    "DNFB_BOOST": 25,              # dnfb_flag boost
    "SCORE_CAP": 150,
    "ACUITY_POINTS": {"MEDICAL_LOW": 0, "MEDICAL_HIGH": 10, "SURGICAL": 20},
}

# DRG grouping weight tables (PRD Section 3.4)
MS_WEIGHT = {"WITHOUT_CC_MCC": 1.0000, "WITH_CC": 1.4000, "WITH_MCC": 2.1000}
AP_WEIGHT = {"SOI_1": 0.9000, "SOI_2": 1.2000, "SOI_3": 1.8000, "SOI_4": 2.5000}

# Expected reimbursement (PRD Section 3.4)
REIMBURSEMENT = {
    "BASE_RATE_CENTS": 650000,
    "COST_CHARGE_RATIO": 0.30,
    "OUTLIER_FIXED_LOSS_CENTS": 500000,
    "OUTLIER_SHARE": 0.80,
}

# Coder accuracy / productivity (PRD Sections 3.5, 3.8)
ACCURACY_FLAG_THRESHOLD = 0.9500          # credential review iff strictly below
PRODUCTIVITY_BASIS_DAYS = 30
ACUITY_WORKLOAD_WEIGHT = {"MEDICAL_LOW": 1, "MEDICAL_HIGH": 2, "SURGICAL": 3}

# Credential ranks (PRD Section 3.2)
CREDENTIAL_RANK = {"CCA": 1, "CCS": 2, "RHIT": 3, "RHIA": 4}
ACUITY_MIN_CREDENTIAL = {"MEDICAL_LOW": "CCA", "MEDICAL_HIGH": "CCS", "SURGICAL": "RHIT"}

# DNFB sweep (PRD Section 3.7)
DNFB_DEFAULT_THRESHOLD_DAYS = 3

# Timely filing (PRD Section 3.9)
TIMELY_FILING_DAYS = 120
