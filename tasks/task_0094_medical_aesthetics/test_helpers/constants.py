"""Domain thresholds — numeric constants from PRD calculations.

PRD §3.3 plan totals — promotional discount thresholds.
PRD §3.4 prep_lead_time — per-SKU prep weights and surgical pad.
PRD §3.4 appointment_conflict_check — sterilization gap.
PRD §3.2 customer_risk_score — declarative weights and AE multiplier.
PRD §3.7 installment_schedule — APR table, credit minimums, grace days.
PRD §2.10 sweep grace windows.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# PRD §3.3 plan_total_final — promotional discount rule.
# ---------------------------------------------------------------------------
PROMO_THRESHOLD_ITEMS = 3
PROMO_RATE_BPS = 500  # 5% expressed in basis points.

# ---------------------------------------------------------------------------
# PRD §3.4 prep_lead_time constants.
# Drugs contribute 4 minutes per unit; consumables 2 minutes per unit.
# Per-SKU raw figure rounded UP to the next multiple of 5 minutes BEFORE
# the max-across-SKUs step. SURGICAL category adds a +30 minute pad.
# ---------------------------------------------------------------------------
PREP_DRUG = 4
PREP_CONSUMABLE = 2
ROUNDING_STEP_MINUTES = 5
SURGICAL_PAD_MINUTES = 30

# ---------------------------------------------------------------------------
# PRD §3.4 appointment_conflict_check — sterilization gap on room intervals.
# ---------------------------------------------------------------------------
STERILIZATION_GAP_MINUTES = 15

# ---------------------------------------------------------------------------
# PRD §3.4 check-in / no-show / reschedule.
# ---------------------------------------------------------------------------
NO_SHOW_GRACE_MINUTES = 60
RESCHEDULE_LIMIT = 3

# ---------------------------------------------------------------------------
# PRD §3.2 customer_risk_score weights.
# ---------------------------------------------------------------------------
PREGNANCY_WEIGHT = 30
UNCONTROLLED_HYPERTENSION_WEIGHT = 25
ACTIVE_INFECTION_WEIGHT = 20
BLEEDING_DISORDER_WEIGHT = 25
ALLERGY_WEIGHT = 5
MEDICATION_WEIGHT = 3
AE_MULTIPLIER_STEP = 0.25
RISK_FLOOR = 0.0
RISK_CEILING = 100.0
SENIOR_COUNTERSIGN_RISK_THRESHOLD = 80.0

# ---------------------------------------------------------------------------
# PRD §3.3 plan items length boundary (1..10 inclusive).
# ---------------------------------------------------------------------------
PLAN_ITEMS_MIN = 1
PLAN_ITEMS_MAX = 10

# ---------------------------------------------------------------------------
# PRD §3.7 installment APR table and credit-score minimums (per term).
# ---------------------------------------------------------------------------
TERM_APR_TABLE = {3: 0, 6: 600, 12: 1200, 24: 1800}
MIN_CREDIT_SCORE = {3: 500, 6: 600, 12: 700, 24: 750}
ALLOWED_TERM_MONTHS = (3, 6, 12, 24)
GRACE_DAYS = 7

# ---------------------------------------------------------------------------
# PRD §3.6 follow-up stage offsets (days from completed appointment end).
# ---------------------------------------------------------------------------
FOLLOWUP_OFFSETS_DAYS = {"D1": 1, "W1": 7, "M1": 30, "M3": 90}
FOLLOWUP_MISS_GRACE_DAYS = 7

# ---------------------------------------------------------------------------
# PRD §3.6 adverse_event_trigger symptom sets.
# ---------------------------------------------------------------------------
SEVERE_SYMPTOMS = {"INFECTION", "NECROSIS", "ANAPHYLAXIS"}
MODERATE_SYMPTOMS = {"PERSISTENT_PAIN", "SWELLING_BEYOND_NORMAL", "NUMBNESS"}

# ---------------------------------------------------------------------------
# PRD §3.3 customer age gate on plan submission.
# ---------------------------------------------------------------------------
CUSTOMER_MIN_AGE_YEARS = 18

# ---------------------------------------------------------------------------
# PRD §2.3 pagination bounds.
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# ---------------------------------------------------------------------------
# Useful seconds-conversion constants for /_clock/advance payloads.
# ---------------------------------------------------------------------------
SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400

# ---------------------------------------------------------------------------
# Test-helper defaults (NOT in PRD; convenience values for factories).
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "BASE_PRICE_CENTS": 100000,
    "DURATION_MINUTES_NON_SURGICAL": 30,
    "DURATION_MINUTES_SURGICAL": 60,
    "RECOVERY_DAYS": 7,
}
