"""Domain thresholds and reference values taken from the PRD narrative."""

# ---- the logical clock (PRD §2.4) ----------------------------------------
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"

# ---- panel weighting bands (PRD §3.1) ------------------------------------
INFANT_SLOT_WEIGHT = 2.0
TODDLER_SLOT_WEIGHT = 1.5
STANDARD_SLOT_WEIGHT = 1.0
INFANT_MAX_AGE_DAYS = 365      # weight 2.0 while age_days < 365
TODDLER_MAX_AGE_DAYS = 1095    # weight 1.5 while 365 <= age_days < 1095

# ---- sibling ladder + money (PRD §2.9, §3.2) -----------------------------
SIBLING_DISCOUNT_PCT = {1: 0.00, 2: 0.20, 3: 0.35}
INVOICE_DUE_DAYS = 14

# ---- waitlist / well-visit sweeps (PRD §3.2, §3.5) -----------------------
WAITLIST_ENTRY_TTL_DAYS = 90
WELL_VISIT_MISS_GRACE_DAYS = 30

# ---- immunization (PRD §3.5) ---------------------------------------------
IMMUNIZATION_GRACE_DAYS = 4
IMMUNIZATION_DUE_LAG_DAYS = 30
VACCINE_SCHEDULE = {
    "HEPB": {
        "total_doses": 3,
        "positions": [
            {"series_index": 1, "min_age_days": 0, "min_interval_days": None},
            {"series_index": 2, "min_age_days": 28, "min_interval_days": 28},
            {"series_index": 3, "min_age_days": 168, "min_interval_days": 56},
        ],
    },
    "DTAP": {
        "total_doses": 5,
        "positions": [
            {"series_index": 1, "min_age_days": 42, "min_interval_days": None},
            {"series_index": 2, "min_age_days": 70, "min_interval_days": 28},
            {"series_index": 3, "min_age_days": 98, "min_interval_days": 28},
            {"series_index": 4, "min_age_days": 365, "min_interval_days": 168},
            {"series_index": 5, "min_age_days": 1460, "min_interval_days": 168},
        ],
    },
}

# ---- well-visit periodicity (PRD §3.5) -----------------------------------
WELL_VISIT_SCHEDULE = [
    {"milestone_code": "NEWBORN", "target": 5, "open": 3, "close": 7},
    {"milestone_code": "M1", "target": 30, "open": 23, "close": 44},
    {"milestone_code": "M2", "target": 61, "open": 53, "close": 75},
    {"milestone_code": "M4", "target": 122, "open": 114, "close": 136},
    {"milestone_code": "M6", "target": 183, "open": 175, "close": 197},
    {"milestone_code": "M9", "target": 274, "open": 259, "close": 289},
    {"milestone_code": "M12", "target": 365, "open": 350, "close": 380},
    {"milestone_code": "M24", "target": 730, "open": 700, "close": 760},
    {"milestone_code": "M36", "target": 1095, "open": 1065, "close": 1125},
    {"milestone_code": "M48", "target": 1460, "open": 1430, "close": 1490},
    {"milestone_code": "M60", "target": 1825, "open": 1795, "close": 1855},
]

# ---- after-hours ladder (PRD §3.6) ---------------------------------------
AFTER_HOURS_EVENING_START_MINUTE = 1080   # 18:00 UTC, inclusive
AFTER_HOURS_MORNING_END_MINUTE = 480      # 08:00 UTC, exclusive
AFTER_HOURS_SURCHARGE_CENTS = 7500
DECLARED_HOLIDAY_DATES = [
    "2026-05-25",
    "2026-07-03",
    "2026-09-07",
    "2026-11-26",
    "2026-12-25",
    "2027-01-01",
]

# ---- scheduling geometry (PRD §3.6, §3.8) --------------------------------
CONSULT_TURNAROUND_BUFFER_MINUTES = 15
ENCOUNTER_DURATION_MINUTES = 30
MAX_CONSULT_RESCHEDULES = 2

# ---- forms (PRD §3.9) ----------------------------------------------------
FORM_WELL_VISIT_RECENCY_DAYS = 365

# ---- charge master (PRD §3.6) --------------------------------------------
SERVICE_BILLED_AMOUNT_CENTS = {
    "WELL_VISIT": 22000,
    "SICK_VISIT": 18000,
    "TELEHEALTH_VISIT": 12000,
    "AFTER_HOURS_SURCHARGE": 7500,
}
ENCOUNTER_SERVICE_CODE_MAP = {
    "SICK_VISIT": "SICK_VISIT",
    "AFTER_HOURS_CONTACT": "SICK_VISIT",
    "ROUTINE_QUESTION": "TELEHEALTH_VISIT",
    "NEWBORN_WEIGHT_CHECK": "WELL_VISIT",
}
WELL_VISIT_LINE_CENTS = 22000

# ---- the practice's reference plan catalogue (PRD §3.1) ------------------
REFERENCE_PLAN_ESSENTIAL = {
    "tier": "ESSENTIAL",
    "monthly_rate_cents": 25000,
    "included_lactation_consults": 1,
    "included_sleep_consults": 0,
    "form_sla_hours": 120,
    "after_hours_surcharge_waived": False,
    "overage_consult_fee_cents": 18000,
}
REFERENCE_PLAN_PLUS = {
    "tier": "PLUS",
    "monthly_rate_cents": 40000,
    "included_lactation_consults": 3,
    "included_sleep_consults": 2,
    "form_sla_hours": 72,
    "after_hours_surcharge_waived": False,
    "overage_consult_fee_cents": 15000,
}
REFERENCE_PLAN_PREMIER = {
    "tier": "PREMIER",
    "monthly_rate_cents": 60000,
    "included_lactation_consults": 6,
    "included_sleep_consults": 4,
    "form_sla_hours": 24,
    "after_hours_surcharge_waived": True,
    "overage_consult_fee_cents": 12000,
}

# ---- pagination (PRD §2.3) -----------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100

# ---- identifiers that resolve to nothing ---------------------------------
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_UUID_ALT = "22222222-2222-4222-8222-222222222222"
