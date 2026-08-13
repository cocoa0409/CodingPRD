"""Domain thresholds — numeric constants from the PRD business rules."""

# Hospital configuration defaults (PRD Section 3.1)
HOSPITAL_DEFAULTS = {
    "DOT_REVIEW_THRESHOLD": 7,
    "IV_TO_PO_MIN_IV_HOURS": 48,
    "ANTIBIOGRAM_MIN_ISOLATES": 30,
    "RESTRICTED_AUTO_EXPIRE_HOURS": 72,
}

# Logical clock fixed start (PRD Section 2.4)
CLOCK_START_ISO = "2026-08-01T00:00:00Z"

# IV-to-PO eligibility scoring (PRD Section 3.5)
IV_TO_PO = {
    "W_STABILITY": 1.0,
    "W_RENAL": 0.4,
    "W_DURATION": 1.0,
    "CONVERSION_MIN_SCORE": 60,
    "HEMODYNAMIC_STABLE_TERM": 40,
    "RENAL_CAP": 90,
    "DURATION_BASE": 30,
    "DURATION_DECAY_PER_24H": 5,
}

# De-escalation scoring (PRD Section 3.5)
DEESCALATION = {
    "MIN_SCORE": 65,
    "BASE": 50,
    "FIRST_ISOLATE_BONUS": 25,
    "REVIEW_THRESHOLD_BONUS": 15,
    "IMMUNOCOMPROMISED_PENALTY": 20,
    "BREADTH_DELTA_MULTIPLIER": 10,
}

# Class breadth ladder (PRD Section 3.5)
CLASS_BREADTH_RANK = {
    "CARBAPENEM": 90,
    "GLYCOPEPTIDE": 70,
    "FLUOROQUINOLONE": 60,
    "EXTENDED_SPECTRUM_PENICILLIN": 50,
    "AMINOGLYCOSIDE": 45,
    "CEPHALOSPORIN": 40,
    "MACROLIDE": 30,
    "NARROW_PENICILLIN": 20,
}

# Allergy risk score (PRD Section 3.6)
ALLERGY_RISK = {
    "LOW_RISK_THRESHOLD": 30,
    "SEVERITY_BASE": {"MILD": 10, "MODERATE": 35, "SEVERE": 80},
    "ANAPHYLAXIS_BONUS": 20,
    "RECENCY_BASE": 30,
    "RECENCY_DECAY_PER_YEAR": 3,
    "COMORBIDITY_BONUS": 10,
    "CAP": 100,
    "RECHALLENGE_MIN_YEARS": 5,
    "ANAPHYLAXIS_KEYWORDS": ("anaphylaxis", "angioedema", "hives", "wheeze"),
}

# Benchmark percentile floors (PRD Section 3.8)
BENCHMARK_FLOORS = {
    "P10": 0,
    "P25": 350,
    "P50": 480,
    "P75": 620,
    "P90": 780,
}

# Guideline adoption threshold (PRD Section 3.7)
ADOPTION_MIN_PCT = 70
STALENESS_DROP_POINTS = 10

# Renal guardrail (PRD Section 3.2)
RENAL_CRCL_FLOOR = 30
RENAL_DAILY_DOSE_CAP = 4000

# Restricted-order concurrency cap (PRD Section 3.2)
RESTRICTED_ORDER_CAP = 2

# Approval request text lengths (PRD Section 3.2)
JUSTIFICATION_MIN_LEN = 20
ESCALATION_REASON_MIN_LEN = 10
RECOMMENDATION_MIN_LEN = 20

# Conversion opportunity expiry (PRD Section 3.5)
OPPORTUNITY_EXPIRE_HOURS = 48
