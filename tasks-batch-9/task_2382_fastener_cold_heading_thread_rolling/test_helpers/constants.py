"""Domain thresholds and numeric constants stated in the PRD narratives."""

# Logical clock (PRD §2.4): before any client sets it the clock reads exactly this.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# Field defaults the server applies when the input is omitted (PRD §3.1, §3.3, §3.5).
DEFAULTS = {
    "QUALIFICATION_PROGRAM": "NONE",
    "SCRAP_ALLOWANCE_PCT": 0.05,
    "COUNT_TOLERANCE_PCT": 0.02,
    "BORON_PPM": 0,
    "MAX_REGRINDS": 3,
    "COOLDOWN_MINUTES": 30,
    "LABEL_FIELDS_COMPLETE": False,
    "DESTRUCTIVE": True,
}

THRESHOLDS = {
    # Wire lot release gates (PRD §3.2)
    "MIN_COATING_WEIGHT_GSM": 2.0,
    "MIN_REDUCTION_PCT": 8.0,
    "MAX_REDUCTION_PCT": 35.0,
    # Die life budgets (PRD §3.3)
    "REGRIND_DERATE_PER_CYCLE": 0.15,
    "CONSERVATIVE_FACTOR": 0.90,
    # Relief bake (PRD §3.1, §3.6)
    "HE_BAKE_MIN_MINUTES_LONG": 480,   # CLASS_12_9 and GRADE_8
    "HE_BAKE_MIN_MINUTES_SHORT": 240,  # CLASS_10_9
    "HE_BAKE_MIN_MINUTES_NONE": 0,
    "BAKE_DELAY_MAX_HOURS": 4.0,
    "BAKE_TEMP_MIN_C": 190,
    "BAKE_TEMP_MAX_C": 230,
    # Pre-test risk score (PRD §3.6)
    "RISK_HEAT_TERM_UNVERIFIED": 25,
    "RISK_TOOL_TERM_CAP": 100,
    "RISK_BAKE_FREE_HOURS": 2.0,
    "RISK_BAKE_SLOPE": 40,
    "RISK_BAKE_CAP": 100,
    "RISK_DECARB_CAP": 100,
    "RISK_WEIGHT_HEAT": 0.30,
    "RISK_WEIGHT_TOOL": 0.20,
    "RISK_WEIGHT_BAKE": 0.25,
    "RISK_WEIGHT_DECARB": 0.25,
    # Final risk score (PRD §3.7)
    "RISK_PER_FAILURE": 12.5,
    "RISK_FINAL_CAP": 100,
    # Sampling plan (PRD §3.7)
    "SEVERITY_TIGHTENED_RISK_THRESHOLD": 40.0,
    "NORMAL_SAMPLE_FLOOR": 8,
    "NORMAL_ACCEPTANCE_SAMPLE_SIZE_THRESHOLD": 20,
    "TIGHTENED_SAMPLE_FLOOR": 13,
    "TIGHTENED_SAMPLE_MULTIPLIER": 1.5,
    # Certification gates (PRD §3.8)
    "AEROSPACE_TOOL_UTILIZATION_MAX_PCT": 80.00,
    "RISK_SCORE_CERTIFIABLE_MAX": 55.00,
}

# Achieved strength class bands, in Vickers, both bounds inclusive (PRD §3.7).
STRENGTH_CLASS_BANDS = {
    "CLASS_8_8": (242, 318),
    "CLASS_10_9": (304, 361),
    "CLASS_12_9": (366, 414),
    "GRADE_5": (241, 302),
    "GRADE_8": (321, 352),
}

# Fixed scan order used when the measured hardness misses the specified class band.
STRENGTH_CLASS_SCAN_ORDER = [
    "CLASS_12_9",
    "CLASS_10_9",
    "GRADE_8",
    "CLASS_8_8",
    "GRADE_5",
]

# Embrittlement-prone classes: he_bake_required is true only for these when plated.
EMBRITTLEMENT_PRONE_CLASSES = ["CLASS_10_9", "CLASS_12_9", "GRADE_8"]

# Pagination (PRD §2.3)
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# Rounding discipline (PRD §2.6)
DECIMALS = {
    "MASS_KG": 3,
    "REDUCTION_PCT": 2,
    "DECARB_DEPTH_MM": 3,
    "BAKE_DELAY_HOURS": 3,
    "TOOL_LIFE_STATS": 2,
    "RISK_SCORE": 2,
}
