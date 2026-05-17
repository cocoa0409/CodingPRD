"""Domain thresholds — numeric constants used by tests.

Each constant traces back to a verbatim sentence in PRD.md.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Encounter scheduling — PRD §3.3.
# ---------------------------------------------------------------------------
# PRD §3.3: "the duration from start to end must be no more than 120
# minutes."
ENCOUNTER_MAX_DURATION_MINUTES: int = 120

# PRD §3.3: "the new window must not be within 15 minutes of any other
# non-terminal encounter for the same patient_id."
PATIENT_ENCOUNTER_BUFFER_MINUTES: int = 15

# PRD §3.3: "the current server time is at or after the scheduled start
# minus 30 minutes (so a patient may arrive up to half an hour early but
# no earlier)."
CHECKIN_EARLY_WINDOW_MINUTES: int = 30

# Terminal encounter states — PRD §3.3: "Non-terminal here means any
# encounter whose status is not in the terminal set
# {COMPLETED, CANCELLED, NO_SHOW}."
ENCOUNTER_TERMINAL_STATES: frozenset = frozenset(
    {"COMPLETED", "CANCELLED", "NO_SHOW"},
)


# ---------------------------------------------------------------------------
# Billing — PRD §3.3.
# ---------------------------------------------------------------------------
# PRD §3.3: "a units count between 1 and 50 inclusive."
CPT_UNITS_MIN: int = 1
CPT_UNITS_MAX: int = 50

# PRD §3.3: "when the encounter total is at most 50000 cents, the tier
# factor is 1.00; when the encounter total is greater than 50000 cents
# and at most 200000 cents, the tier factor is 0.95; when the encounter
# total is greater than 200000 cents, the tier factor is 0.90."
ALLOWED_AMOUNT_TIER1_CEILING_CENTS: int = 50_000
ALLOWED_AMOUNT_TIER2_CEILING_CENTS: int = 200_000
ALLOWED_AMOUNT_TIER1_FACTOR: float = 1.00
ALLOWED_AMOUNT_TIER2_FACTOR: float = 0.95
ALLOWED_AMOUNT_TIER3_FACTOR: float = 0.90

# PRD §3.3: modifier multipliers.
# "1.25 when the line's modifier equals the string `25`, 1.00 when the
# modifier equals the string `59`, 0.65 when the modifier equals the
# string `TC`, 0.35 when the modifier equals the string `26`, and 1.00
# in every other case (including when the modifier is null or absent)."
MODIFIER_MULTIPLIERS: dict = {
    "25": 1.25,
    "59": 1.00,
    "TC": 0.65,
    "26": 0.35,
}


# ---------------------------------------------------------------------------
# Prescription expiry — PRD §3.4.
# ---------------------------------------------------------------------------
# PRD §3.4: "365 days after signed_at for non-controlled prescriptions,
# 180 days after signed_at for schedule III, IV, or V controlled
# prescriptions, and 30 days after signed_at for schedule II controlled
# prescriptions."
PRESCRIPTION_EXPIRY_DAYS_NON_CONTROLLED: int = 365
PRESCRIPTION_EXPIRY_DAYS_SCHEDULE_III_V: int = 180
PRESCRIPTION_EXPIRY_DAYS_SCHEDULE_II: int = 30

# PRD §3.4: "a quantity between 1 and 360 tablets, and a
# refills_authorized integer between 0 and 5."
PRESCRIPTION_QUANTITY_MIN: int = 1
PRESCRIPTION_QUANTITY_MAX: int = 360
REFILLS_AUTHORIZED_MIN: int = 0
REFILLS_AUTHORIZED_MAX: int = 5


# ---------------------------------------------------------------------------
# Provider — PRD §3.2.
# ---------------------------------------------------------------------------
# PRD §3.2: "An optional panel_cap (defaulting to 2000) sets the maximum
# panel headcount."
DEFAULT_PANEL_CAP: int = 2000


# ---------------------------------------------------------------------------
# Portal — PRD §3.6.
# ---------------------------------------------------------------------------
# PRD §3.6: "a body string between 1 and 2000 characters inclusive."
PORTAL_MESSAGE_BODY_MIN: int = 1
PORTAL_MESSAGE_BODY_MAX: int = 2000


# ---------------------------------------------------------------------------
# Referral expiry — PRD §3.5.
# ---------------------------------------------------------------------------
# PRD §3.5: "72 hours after created_at when priority is URGENT, and 30
# days after created_at when priority is ROUTINE."
REFERRAL_EXPIRY_HOURS_URGENT: int = 72
REFERRAL_EXPIRY_DAYS_ROUTINE: int = 30


# ---------------------------------------------------------------------------
# HEDIS — PRD §3.8.
# ---------------------------------------------------------------------------
# PRD §3.8: "The denominator is met when the patient's age at year-end
# is at least 18..."
HEDIS_AWV_MIN_AGE: int = 18
HEDIS_TSC_MIN_AGE: int = 18
HEDIS_CBP_MIN_AGE: int = 18
HEDIS_CBP_MAX_AGE: int = 85
HEDIS_CCS_MIN_AGE: int = 21
HEDIS_CCS_MAX_AGE: int = 64

# PRD §3.8: "vital_signs.bp_systolic strictly less than 140 and
# vital_signs.bp_diastolic strictly less than 90."
CBP_SYSTOLIC_CEIL: int = 140
CBP_DIASTOLIC_CEIL: int = 90

# PRD §3.8: TSC consultation CPT codes.
TSC_CONSULTATION_CPT_CODES: frozenset = frozenset({"99406", "99407"})

# PRD §3.8: CCS screening CPT codes.
CCS_SCREENING_CPT_CODES: frozenset = frozenset({"88141", "88142"})


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3.
# ---------------------------------------------------------------------------
# PRD §2.3: "limit ... defaults to 10, has a minimum of 1, and a maximum
# of 100. offset is the number of items skipped before the page begins;
# it defaults to 0."
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Field length / format constants — PRD §3.1 / §3.2.
# ---------------------------------------------------------------------------
# PRD §3.1: "Medical Record Number (which must match the pattern of the
# three letters MRN followed by exactly eight digits)."
MRN_REGEX: str = r"^MRN[0-9]{8}$"

# PRD §3.2: "the 10-digit npi (matching exactly ten digits)."
NPI_REGEX: str = r"^[0-9]{10}$"

# PRD §3.3: "a cpt_code (a five-digit string matching the CPT-4
# pattern)."
CPT_CODE_REGEX: str = r"^[0-9]{5}$"


# ---------------------------------------------------------------------------
# Test defaults — convenient values used by fixtures.
# ---------------------------------------------------------------------------
TEST_DEFAULTS: dict = {
    # Clock anchor used by all time-sensitive setups.
    # PRD §2.9 establishes the test-driven monotonic clock.
    "CLOCK_ANCHOR": "2026-05-16T10:00:00.000Z",
    # Default catalog prices used by the basic billing fixtures.
    "CPT_LIST_PRICE_CENTS": 12_000,
    "CPT_ALLOWED_PRICE_CENTS": 8_000,
    "CPT_LIST_PRICE_CENTS_LOW": 3_000,
    "CPT_ALLOWED_PRICE_CENTS_LOW": 2_000,
}


__all__ = [
    "ENCOUNTER_MAX_DURATION_MINUTES",
    "PATIENT_ENCOUNTER_BUFFER_MINUTES",
    "CHECKIN_EARLY_WINDOW_MINUTES",
    "ENCOUNTER_TERMINAL_STATES",
    "CPT_UNITS_MIN",
    "CPT_UNITS_MAX",
    "ALLOWED_AMOUNT_TIER1_CEILING_CENTS",
    "ALLOWED_AMOUNT_TIER2_CEILING_CENTS",
    "ALLOWED_AMOUNT_TIER1_FACTOR",
    "ALLOWED_AMOUNT_TIER2_FACTOR",
    "ALLOWED_AMOUNT_TIER3_FACTOR",
    "MODIFIER_MULTIPLIERS",
    "PRESCRIPTION_EXPIRY_DAYS_NON_CONTROLLED",
    "PRESCRIPTION_EXPIRY_DAYS_SCHEDULE_III_V",
    "PRESCRIPTION_EXPIRY_DAYS_SCHEDULE_II",
    "PRESCRIPTION_QUANTITY_MIN",
    "PRESCRIPTION_QUANTITY_MAX",
    "REFILLS_AUTHORIZED_MIN",
    "REFILLS_AUTHORIZED_MAX",
    "DEFAULT_PANEL_CAP",
    "PORTAL_MESSAGE_BODY_MIN",
    "PORTAL_MESSAGE_BODY_MAX",
    "REFERRAL_EXPIRY_HOURS_URGENT",
    "REFERRAL_EXPIRY_DAYS_ROUTINE",
    "HEDIS_AWV_MIN_AGE",
    "HEDIS_TSC_MIN_AGE",
    "HEDIS_CBP_MIN_AGE",
    "HEDIS_CBP_MAX_AGE",
    "HEDIS_CCS_MIN_AGE",
    "HEDIS_CCS_MAX_AGE",
    "CBP_SYSTOLIC_CEIL",
    "CBP_DIASTOLIC_CEIL",
    "TSC_CONSULTATION_CPT_CODES",
    "CCS_SCREENING_CPT_CODES",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "MRN_REGEX",
    "NPI_REGEX",
    "CPT_CODE_REGEX",
    "TEST_DEFAULTS",
]
