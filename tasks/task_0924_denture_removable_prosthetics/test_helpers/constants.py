"""Domain thresholds and fees from the PRD's declared calculations."""

# --- logical clock -------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"

# --- impression / scan quality bands (integer score 0..100) --------------
IMPRESSION_ACCEPT_MIN = 85
IMPRESSION_PROVISIONAL_MIN = 70
IMPRESSION_SCORE_MIN = 0
IMPRESSION_SCORE_MAX = 100
IMPRESSION_RETAKE_CEILING = 3

# --- try-in milestone ----------------------------------------------------
TRYIN_ADJUST_CEILING = 2

# --- laboratory coordination ---------------------------------------------
LAB_STANDARD_TURNAROUND_DAYS = 10
LAB_RUSH_TURNAROUND_DAYS = 4
LAB_RUSH_FEE_BASE = 120.00
LAB_RUSH_FEE_PER_UNIT = 35.00
LAB_SHELF_LIFE_DAYS = 45
LAB_QC_RESEND_CEILING = 2
LAB_FAULT_CREDIT_RATE = 0.60
LAB_DEFAULT_INVOICE_AMOUNT = 450.00
LAB_DEFAULT_BENCH_LINE_COUNT = 3
ARCH_TURNAROUND_BUFFER_HOURS = 24

# --- warranty / replacement ----------------------------------------------
WARRANTY_WINDOW_DAYS = 365
REPLACEMENT_FREQUENCY_MONTHS = 60

# --- included post-delivery adjustment allowance -------------------------
ADJUSTMENT_ALLOWANCE_COUNT = 4
ADJUSTMENT_ALLOWANCE_WINDOW_DAYS = 90
ADJUSTMENT_CHARGEABLE_FEE = 85.00

# --- fee schedule per arch, by prosthesis_type ---------------------------
ARCH_FEE = {
    "COMPLETE_DENTURE": 1800.00,
    "IMMEDIATE_DENTURE": 2100.00,
    "CAST_PARTIAL": 1650.00,
    "FLEXIBLE_PARTIAL": 1200.00,
    "OVERDENTURE": 2400.00,
    "IMPLANT_RETAINED_OVERDENTURE": 3600.00,
}

# --- post-delivery service fees ------------------------------------------
SERVICE_FEE = {
    "ADJUSTMENT": 85.00,
    "SOFT_RELINE_CHAIRSIDE": 260.00,
    "HARD_RELINE_LAB": 420.00,
    "REBASE": 590.00,
    "REPAIR": 180.00,
    "TOOTH_ADDITION": 155.00,
    "CLASP_ADDITION": 195.00,
}

# --- post-delivery service frequency limits (whole calendar months) ------
SERVICE_FREQUENCY_MONTHS = {
    "ADJUSTMENT": 0,
    "SOFT_RELINE_CHAIRSIDE": 6,
    "HARD_RELINE_LAB": 24,
    "REBASE": 36,
    "REPAIR": 0,
    "TOOTH_ADDITION": 0,
    "CLASP_ADDITION": 0,
}

# --- immediate-denture mandatory reline ----------------------------------
IMMEDIATE_DENTURE_RELINE_DUE_DAYS = 180

# --- recall intervals per prosthesis_type (days from delivered_at) -------
RECALL_INTERVAL_DAYS = {
    "COMPLETE_DENTURE": 365,
    "IMMEDIATE_DENTURE": 90,
    "CAST_PARTIAL": 365,
    "FLEXIBLE_PARTIAL": 365,
    "OVERDENTURE": 180,
    "IMPLANT_RETAINED_OVERDENTURE": 180,
}
RECALL_OVERDUE_GRACE_DAYS = 30

# --- remake --------------------------------------------------------------
REMAKE_CEILING_PER_ARCH = 2

# --- insurance -----------------------------------------------------------
COVERAGE_DEFAULT_ANNUAL_MAXIMUM = 1500.00
COVERAGE_DEFAULT_COINSURANCE_MAJOR_RATE = 0.50
COVERAGE_DEFAULT_WAITING_PERIOD_DAYS = 180
COVERAGE_DEFAULT_REPLACEMENT_FREQUENCY_MONTHS = 60
PREDETERMINATION_REQUIRED_MIN_FEE = 1500.00
PREDETERMINATION_VALIDITY_DAYS = 180
ALTERNATE_BENEFIT_TARGET = {
    "IMPLANT_RETAINED_OVERDENTURE": "COMPLETE_DENTURE",
    "OVERDENTURE": "COMPLETE_DENTURE",
    "CAST_PARTIAL": "FLEXIBLE_PARTIAL",
}

# --- payment plan --------------------------------------------------------
PAYMENT_PLAN_MIN_INSTALLMENTS = 2
PAYMENT_PLAN_MAX_INSTALLMENTS = 12
PAYMENT_PLAN_MIN_DOWN_RATE = 0.20
PAYMENT_PLAN_DELINQUENCY_GRACE_DAYS = 10
PAYMENT_PLAN_DEFAULT_MISSED_COUNT = 3
PAYMENT_FREQUENCY_DAYS = {"MONTHLY": 30, "BIWEEKLY": 14}

# --- prompt-pay discount tiers (keyed on PRE-discount responsibility) ----
PROMPT_PAY_TIER_2_MIN = 2500.00
PROMPT_PAY_TIER_1_MIN = 1000.00
PROMPT_PAY_TIER_2_RATE = 0.05
PROMPT_PAY_TIER_1_RATE = 0.03
PROMPT_PAY_TIER_0_RATE = 0.00

# --- required milestone sequence per prosthesis_type ---------------------
REQUIRED_MILESTONES = {
    "COMPLETE_DENTURE": ["WAX", "FINISH"],
    "IMMEDIATE_DENTURE": [],
    "CAST_PARTIAL": ["FRAMEWORK", "WAX", "FINISH"],
    "FLEXIBLE_PARTIAL": ["WAX"],
    "OVERDENTURE": ["WAX", "FINISH"],
    "IMPLANT_RETAINED_OVERDENTURE": ["FRAMEWORK", "FINISH"],
}

# --- service routing sets ------------------------------------------------
CHAIRSIDE_SERVICE_TYPES = ["ADJUSTMENT", "SOFT_RELINE_CHAIRSIDE", "REPAIR"]
LAB_SERVICE_TYPES = ["HARD_RELINE_LAB", "REBASE", "TOOTH_ADDITION", "CLASP_ADDITION"]
PARTIAL_PROSTHESIS_TYPES = ["CAST_PARTIAL", "FLEXIBLE_PARTIAL"]

# --- pagination ----------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100

# --- well-formed uuids that name no row ----------------------------------
UNKNOWN_PATIENT_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
UNKNOWN_COVERAGE_ID = "1c9d55aa-7f0e-4b31-8d02-6a1b3c4d5e6f"
UNKNOWN_CASE_ID = "2c9d55aa-7f0e-4b31-8d02-6a1b3c4d5e60"
UNKNOWN_ARCH_ID = "3c9d55aa-7f0e-4b31-8d02-6a1b3c4d5e61"
UNKNOWN_LAB_CASE_ID = "4c9d55aa-7f0e-4b31-8d02-6a1b3c4d5e62"
UNKNOWN_PROSTHESIS_ID = "5c9d55aa-7f0e-4b31-8d02-6a1b3c4d5e63"
UNKNOWN_REFERENCE_ID = "6c9d55aa-7f0e-4b31-8d02-6a1b3c4d5e64"
