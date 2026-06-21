"""Domain thresholds — numeric constants from the PRD's matching/discount rules."""

# Match-variance tolerance and OCR floor (PRD §3.3, §3.4).
THRESHOLDS = {
    "ABS_TOLERANCE_CENTS": 1000,   # absolute tolerance floor (PRD §3.4)
    "PCT_TOLERANCE": 0.02,         # percentage tolerance (PRD §3.4)
    "CONFIDENCE_FLOOR": 0.80,      # OCR confidence floor (PRD §3.3)
    "WRITEOFF_CEILING_CENTS": 5000,  # write-off / escalate ceiling (PRD §3.4)
}

# Vendor field defaults applied at creation (PRD §3.1).
VENDOR_DEFAULTS = {
    "is_1099": False,
    "early_pay_terms_pct": 0,
    "early_pay_window_days": 0,
    "net_terms_days": 30,
}

# A large sentinel upper bound used for an open-ended top approval tier (PRD §3.1).
TIER_MAX_SENTINEL = 1_000_000_000
