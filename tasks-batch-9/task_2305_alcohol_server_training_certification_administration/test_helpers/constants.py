"""Domain thresholds and reusable literal inputs drawn from the PRD's own numbers."""

# --------------------------------------------------------------------------------------
# The logical clock
# --------------------------------------------------------------------------------------

# At startup the logical clock reads exactly this instant.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# Instants used by the scenario walks below.
CLOCK_SETUP = "2026-08-03T09:00:00Z"
CLOCK_CLASS_START = "2026-08-10T14:00:00Z"
CLOCK_EXAM_OPEN = "2026-08-10T14:05:00Z"
CLOCK_CLASS_END = "2026-08-10T18:00:00Z"
CLOCK_COMPLETION = "2026-08-10T18:30:00Z"
CLOCK_DOCUMENTATION = "2026-08-15T09:00:00Z"
CLOCK_REGISTRY_ACK = "2026-08-20T10:00:00Z"


# --------------------------------------------------------------------------------------
# Jurisdiction policy defaults declared by the PRD
# --------------------------------------------------------------------------------------

JURISDICTION_DEFAULTS = {
    "certificate_validity_months": 36,
    "renewal_grace_days": 30,
    "new_hire_training_days": 30,
    "registry_submission_required": True,
    "registry_deadline_days": 30,
    "registry_late_fee_cents_per_day": 250,
    "min_passing_score_pct": 70,
    "max_retakes_allowed": 2,
    "retake_cooling_off_hours": 24,
    "proctor_separation_required": True,
    "reminder_lead_days": 60,
}

# Mandate type and mandated-track cardinality must agree.
MANDATE_TRACK_CARDINALITY = {
    "MANDATORY": 2,
    "CONDITIONAL": 1,
    "VOLUNTARY": 0,
}


# --------------------------------------------------------------------------------------
# Shape constraints that produce ERR_INVALID_REQUEST
# --------------------------------------------------------------------------------------

SHAPE_LIMITS = {
    "CAPACITY_MIN": 1,
    "CAPACITY_MAX": 40,
    "SEAT_QUANTITY_MIN": 1,
    "SEAT_QUANTITY_MAX": 500,
    "UNIT_PRICE_CENTS_MIN": 1,
    "CONTACT_HOURS_MAX": 24,
    "QUESTION_COUNT_MIN": 10,
    "QUESTION_COUNT_MAX": 200,
    "MIN_PASSING_SCORE_PCT_MIN": 50.00,
    "MIN_PASSING_SCORE_PCT_MAX": 100.00,
    "ANNUAL_PREMIUM_CENTS_MAX": 100000000,
    "PAGE_LIMIT_MIN": 1,
    "PAGE_LIMIT_MAX": 100,
    "PAGE_LIMIT_DEFAULT": 10,
}


# --------------------------------------------------------------------------------------
# Scheduling buffers and windows
# --------------------------------------------------------------------------------------

# The trainer's requested window is widened by one hour on each side into a closed interval.
TRAINER_BUFFER_MINUTES = 60


# --------------------------------------------------------------------------------------
# Seat-credit purchase settlement
# --------------------------------------------------------------------------------------

# Volume discount percentage chosen from the gross subtotal in cents.
VOLUME_DISCOUNT_BANDS = [
    (500_00, 0.00),        # below five hundred dollars
    (1_500_00, 3.00),      # five hundred up to but excluding fifteen hundred dollars
    (5_000_00, 6.00),      # fifteen hundred up to but excluding five thousand dollars
    (None, 10.00),         # five thousand dollars and above
]
PROCESSING_FEE_CAP_CENTS = 25_00
PROCESSING_FEE_RATE_PCT = 2.9
BONUS_CREDIT_UNIT_CENTS = 1_000_00


# --------------------------------------------------------------------------------------
# Compliance posture and dram-shop discount
# --------------------------------------------------------------------------------------

POSTURE_COMPLIANT_FLOOR_PCT = 95.00
POSTURE_AT_RISK_FLOOR_PCT = 80.00
DOCUMENTATION_FLOOR_PCT = 80.00
EMPTY_LOCATION_RATE_PCT = 100.00
EMPTY_ACCOUNT_RATE_PCT = 0.00

DISCOUNT_TIER_BANDS = [
    (98.00, "TIER_3", 10.00),
    (90.00, "TIER_2", 7.00),
    (80.00, "TIER_1", 4.00),
]
TENURE_BONUS_CAP_PCT = 3.00
MULTI_LOCATION_BONUS_PCT = 2.00
MULTI_LOCATION_MIN_LOCATIONS = 3
MULTI_LOCATION_MIN_STRICT_RATE_PCT = 90.00
DISCOUNT_CLAMP_MAX_PCT = 12.00

# Registry lateness escalation: one plus five hundredths for each attempt beyond the first.
REGISTRY_ESCALATION_STEP = 0.05

# Reminders stop once reminder_sent_count reaches this value.
REMINDER_CAP = 2


# --------------------------------------------------------------------------------------
# Reusable literal inputs for the Texas scenario used across the suite
# --------------------------------------------------------------------------------------

TX_JURISDICTION = {
    "state_code": "TX",
    "mandate_type": "MANDATORY",
    "mandated_tracks": ["ON_PREMISE", "OFF_PREMISE"],
    "certificate_validity_months": 24,
    "renewal_grace_days": 30,
    "new_hire_training_days": 30,
    "registry_submission_required": True,
    "registry_deadline_days": 15,
    "registry_late_fee_cents_per_day": 250,
    "min_passing_score_pct": 70,
    "max_retakes_allowed": 2,
    "retake_cooling_off_hours": 24,
    "proctor_separation_required": False,
    "reminder_lead_days": 60,
}

TX_COURSE = {
    "title": "TIPS On-Premise Core",
    "track": "ON_PREMISE",
    "delivery_mode": "CLASSROOM",
    "contact_hours": 4,
    "question_count": 40,
    "version_label": "v1",
}

TX_APPROVAL_DECISION = {
    "decision": "APPROVE",
    "approval_number": "TX-ABC-2026-001",
    "effective_from": "2026-08-01T00:00:00Z",
    "expires_at": "2027-08-01T00:00:00Z",
}

TRAINER_CREDENTIAL_EXPIRES_AT = "2027-06-30T00:00:00Z"

EMPLOYER_LEGAL_NAME = "Lone Star Taverns LLC"

LOCATION_PREMIUMS = {
    "Alamo Taproom": 4821734,
    "Riverwalk Cantina": 1257444,
    "Hill Country Icehouse": 999920,
}

SEAT_PURCHASE_LARGE = {"seat_quantity": 80, "unit_price_cents": 2500}
