"""Domain thresholds — numeric constants from the PRD's calculation rules (§3.2, §3.3, §3.6, §3.7, §3.8, §3.9)."""

# --- Risk scoring (PRD §3.2) ---
RISK_WEIGHTS = {"GEO": 4, "PROD": 3, "PEP": 5, "MEDIA": 3}
PEP_MEDIA_SURCHARGE = 12
RISK_BANDS = {
    "PROHIBITED": 84,   # total_score >= 84
    "HIGH": 60,         # 60 <= total_score < 84
    "MEDIUM": 35,       # 35 <= total_score < 60
    # else LOW
}

# --- Screening hit confirmation floor (PRD §3.5) ---
CONFIRM_FLOOR = 0.95

# --- Transaction monitoring (PRD §3.6) ---
CTR_LIMIT_CENTS = 1_000_000     # strictly greater than fires CTR_THRESHOLD
STRUCT_LOW = 900_000            # inclusive lower bound of STRUCTURING band
STRUCT_HIGH = 1_000_000         # inclusive upper bound of STRUCTURING band
RAPID_FRACTION = 0.90
HIGH_RISK_COUNTRIES = ["IR", "KP", "SY", "CU"]

# --- Alert severity (PRD §3.7) ---
RULE_BASE = {
    "STRUCTURING": 40,
    "RAPID_MOVEMENT": 35,
    "HIGH_RISK_GEO": 25,
    "CTR_THRESHOLD": 20,
}
RISK_MULT = {"LOW": 1.0, "MEDIUM": 1.5, "HIGH": 2.0, "PROHIBITED": 2.0}
NULL_RATING_MULT = 1.0

# --- Case priority bands (PRD §3.8) ---
CASE_PRIORITY_BANDS = {
    "CRITICAL": 70,
    "HIGH": 50,
    "MEDIUM": 30,
    # else LOW
}

# --- Filing deadlines (PRD §3.9) ---
SAR_DEADLINE_DAYS = 30
CTR_DEADLINE_DAYS = 15

# --- Review cadence (PRD §3.3) ---
REVIEW_CADENCE_DAYS = {"HIGH": 90, "MEDIUM": 180, "LOW": 365}

# --- Ownership ceiling (PRD §3.4) ---
OWNERSHIP_CEILING = 100.00

# --- Pagination (PRD §2.3) ---
PAGINATION = {"default_limit": 10, "min_limit": 1, "max_limit": 100, "min_offset": 0}
