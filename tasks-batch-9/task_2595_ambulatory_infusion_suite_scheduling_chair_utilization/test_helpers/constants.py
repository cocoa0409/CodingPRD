"""Domain thresholds, defaults and canonical fixture values."""

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
#: The clock reads exactly this instant before it has ever been set.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

#: The clock instant most fixtures pin so that timestamps are literals.
FIXTURE_CLOCK = "2026-08-05T07:00:00Z"

MINUTE_OF_DAY_MIN = 0
MINUTE_OF_DAY_MAX = 1439

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Infusion center defaults and permitted ranges
# ---------------------------------------------------------------------------
DEFAULT_TURNOVER_BUFFER_MINUTES = 15
TURNOVER_BUFFER_MIN = 0
TURNOVER_BUFFER_MAX = 60

DEFAULT_URGENT_RESERVE_CHAIR_COUNT = 1
URGENT_RESERVE_CHAIR_COUNT_MIN = 0
URGENT_RESERVE_CHAIR_COUNT_MAX = 10

DEFAULT_ADDON_CUTOFF_MINUTE = 900

DEFAULT_LAB_VALIDITY_HOURS = 72
LAB_VALIDITY_HOURS_MIN = 1
LAB_VALIDITY_HOURS_MAX = 168

DEFAULT_STAGGER_GRID_MINUTES = 15
ALLOWED_STAGGER_GRID_MINUTES = [5, 10, 15, 20, 30]

DEFAULT_ACUITY_SLOT_MINUTES = 30
ALLOWED_ACUITY_SLOT_MINUTES = [15, 30, 60]

CENTER_NAME_MAX_LEN = 120
CHAIR_LABEL_MAX_LEN = 16
CLOSE_MINUTE_MAX = 1440

# ---------------------------------------------------------------------------
# Nurse / drug ranges
# ---------------------------------------------------------------------------
ACUITY_CAPACITY_POINTS_MIN = 1
ACUITY_CAPACITY_POINTS_MAX = 20

ADMIN_MINUTES_MIN = 5
ADMIN_MINUTES_MAX = 480
PREMEDICATION_MINUTES_MAX = 120
OBSERVATION_MINUTES_MAX = 240
DRUG_ACUITY_POINTS_MIN = 1
DRUG_ACUITY_POINTS_MAX = 10
PREP_STABILITY_MINUTES_MIN = 15
PREP_STABILITY_MINUTES_MAX = 1440

LAB_ANC_MAX = 100
LAB_PLATELETS_MAX = 2000

# ---------------------------------------------------------------------------
# Patient / regimen ranges
# ---------------------------------------------------------------------------
MRN_MAX_LEN = 32
WEIGHT_KG_MIN = 1
WEIGHT_KG_MAX = 400
DOSE_MG_PER_KG_MAX = 100
TOTAL_CYCLES_MIN = 1
TOTAL_CYCLES_MAX = 52
UNITS_REQUESTED_MIN = 1
UNITS_REQUESTED_MAX = 100

#: A patient's no-show strikes window, in calendar days ending on the clock's date.
NO_SHOW_STRIKE_WINDOW_DAYS = 180
#: no_show_strikes at or above this figure flips steering to HOME_INFUSION_REVIEW.
STEERING_STRIKE_THRESHOLD = 3
#: waste_liability_cents at or above this figure flips steering to HOME_INFUSION_REVIEW.
STEERING_LIABILITY_THRESHOLD_CENTS = 50000

# ---------------------------------------------------------------------------
# Dose tiers
# ---------------------------------------------------------------------------
#: Both upper edges inclusive: LOW <= 500 < MID <= 1000 < HIGH.
DOSE_TIER_LOW_MAX_MG = 500
DOSE_TIER_MID_MAX_MG = 1000

#: Escalation minutes added to the push time per derived tier.
TIER_ESCALATION_MINUTES = {"LOW": 0, "MID": 30, "HIGH": 60}

#: A HIGH template carries one surcharge acuity point over the drug's own figure.
HIGH_TIER_ACUITY_SURCHARGE = 1
#: A template whose derived acuity is at or above this doubles the stagger offset.
STAGGER_DOUBLING_ACUITY_THRESHOLD = 4
#: A visit on a regimen whose first dose has not completed carries one extra point.
FIRST_DOSE_ACUITY_SURCHARGE = 1

# ---------------------------------------------------------------------------
# Booking / selector geometry
# ---------------------------------------------------------------------------
#: ROUTINE and SAME_DAY_ADDON search a nine-candidate ascending grid.
ROUTINE_CANDIDATE_COUNT = 9
#: URGENT takes the snapped minute as its only candidate.
URGENT_CANDIDATE_COUNT = 1

# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------
#: submission_count must be below this figure for a submission to be accepted.
MAX_SUBMISSION_COUNT = 3
#: An APPROVED decision sets expires_at to decided_at plus this many days.
AUTH_VALIDITY_DAYS = 30

# ---------------------------------------------------------------------------
# Reactions
# ---------------------------------------------------------------------------
#: Grade-implied observation extension in minutes.
GRADE_EXTENSION_MINUTES = {1: 0, 2: 30, 3: 60, 4: 120}
#: An ABORT action floors the extension at one hour.
ABORT_EXTENSION_FLOOR_MINUTES = 60
#: A reaction at or above this grade drives readiness to BLOCKED.
BLOCKING_GRADE = 3

# ---------------------------------------------------------------------------
# Cancellation pricing
# ---------------------------------------------------------------------------
#: A cancellation is late when the clock is at or after start minus this many hours.
LATE_CANCELLATION_WINDOW_HOURS = 24
BASE_CHARGE_ROUTINE_CENTS = 2500
BASE_CHARGE_PRIORITY_CENTS = 4000
#: Share tier edges, keyed on the provisional total; both upper edges inclusive.
SHARE_TIER_LOW_MAX_CENTS = 5000
SHARE_TIER_MID_MAX_CENTS = 25000
SHARE_PCT_LOW = 0.0
SHARE_PCT_MID = 0.20
SHARE_PCT_HIGH = 0.35

# ---------------------------------------------------------------------------
# Reminder cadence
# ---------------------------------------------------------------------------
#: How many outreach contacts a visit accepts, by the patient's reminder tier.
REMINDER_CAP_BY_TIER = {"STANDARD": 1, "ELEVATED": 3, "INTENSIVE": 5}
REMINDER_CADENCE_CODE_BY_TIER = {
    "STANDARD": "C_STANDARD",
    "ELEVATED": "C_ELEVATED",
    "INTENSIVE": "C_INTENSIVE",
}

# ---------------------------------------------------------------------------
# No-show risk
# ---------------------------------------------------------------------------
#: The ROLLING_6 window length and its recency weights, most recent row first.
ROLLING_WINDOW_SIZE = 6
ROLLING_WEIGHTS = [100, 85, 70, 55, 40, 25]
#: Event values by terminal outcome.
EVENT_VALUE_NO_SHOW = 1.00
EVENT_VALUE_CANCELLED_LATE = 0.50
EVENT_VALUE_CANCELLED_EARLY = 0.25
EVENT_VALUE_COMPLETED = 0.00
#: reminder_tier edges read straight off the ROLLING_6 score.
TIER_ELEVATED_FLOOR = 20
TIER_INTENSIVE_FLOOR = 45

# ---------------------------------------------------------------------------
# Billing / utilization
# ---------------------------------------------------------------------------
#: Realised chair time is billed in quarter-hour units, ceilinged per visit.
BILLABLE_UNIT_MINUTES = 15
#: Ninety dollars per quarter-hour of chair time.
BILLABLE_CENTS_PER_UNIT = 9000

# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------
#: A visit is a no-show once the clock reaches start plus this grace period.
NO_SHOW_GRACE_MINUTES = 30

# ---------------------------------------------------------------------------
# Compounding
# ---------------------------------------------------------------------------
#: Mixing more than this many minutes ahead of the visit start is too early.
PREP_EARLIEST_LEAD_MINUTES = 60

# ---------------------------------------------------------------------------
# Canonical fixture payload values
# ---------------------------------------------------------------------------
CENTER_DEFAULTS = {
    "name": "Riverside Infusion Suite",
    "open_minute": 480,
    "close_minute": 1140,
    "turnover_buffer_minutes": 15,
    "urgent_reserve_chair_count": 1,
    "addon_cutoff_minute": 900,
    "lab_validity_hours": 72,
    "stagger_grid_minutes": 15,
    "acuity_slot_minutes": 30,
}

#: Gate drug: base 120 / floor 90 / premed 30 / obs 60|30 / acuity 2 / stability 240.
DRUG_GATE_DEFAULTS = {
    "name": "Infliximab-Ref",
    "is_biosimilar": False,
    "base_administration_minutes": 120,
    "min_administration_minutes": 90,
    "premedication_minutes": 30,
    "observation_minutes_first_dose": 60,
    "observation_minutes_subsequent": 30,
    "acuity_points": 2,
    "prep_stability_minutes": 240,
    "unit_cost_cents": 90000,
    "requires_lab_gate": True,
    "lab_min_anc": 1.5,
    "lab_min_platelets": 100,
}

#: Iron Sucrose: a short, ungated, single-acuity-point product.
DRUG_SHORT_DEFAULTS = {
    "name": "Iron Sucrose",
    "is_biosimilar": False,
    "base_administration_minutes": 60,
    "min_administration_minutes": 45,
    "premedication_minutes": 0,
    "observation_minutes_first_dose": 30,
    "observation_minutes_subsequent": 15,
    "acuity_points": 1,
    "prep_stability_minutes": 120,
    "unit_cost_cents": 12000,
    "requires_lab_gate": False,
}

#: Vedolizumab-Slow: the floor beats the escalated base (min 150 > 60 + 30).
DRUG_FLOORED_DEFAULTS = {
    "name": "Vedolizumab-Slow",
    "is_biosimilar": False,
    "base_administration_minutes": 60,
    "min_administration_minutes": 150,
    "premedication_minutes": 20,
    "observation_minutes_first_dose": 45,
    "observation_minutes_subsequent": 20,
    "acuity_points": 1,
    "prep_stability_minutes": 120,
    "unit_cost_cents": 30000,
    "requires_lab_gate": False,
}

NURSE_DEFAULTS = {
    "full_name": "Nora Ade",
    "acuity_capacity_points": 6,
    "shift_start_minute": 480,
    "shift_end_minute": 1140,
    "status": "ACTIVE",
}

PATIENT_WEIGHT_KG = 70
#: 10 mg/kg on 70 kg -> 700 mg -> MID tier.
PLAN_MID_DOSE_MG_PER_KG = 10
#: 5 mg/kg on 70 kg -> 350 mg -> LOW tier.
PLAN_LOW_DOSE_MG_PER_KG = 5

DEFAULT_PAYER_NAME = "Meridian Health Plan"
DEFAULT_APPROVED_UNITS = 4
