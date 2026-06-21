"""Domain thresholds — numeric constants from the PRD's calculations (PRD §2.8, §3)."""

# Qualifying-stay threshold (PRD §3.2): qualifies when midnights_count is at least 3.
QUALIFYING_MIDNIGHTS = 3

# Therapy group/concurrent cap (PRD §3.5): exceeds when pct strictly greater than 0.25.
GROUP_CONCURRENT_CAP_PCT = 0.25

# Paid bed-hold caps by payer (PRD §3.6): MEDICAID 10, MEDICARE_A 0, MANAGED_CARE 7, PRIVATE 30.
PAID_BEDHOLD_CAP = {
    "MEDICAID": 10,
    "MEDICARE_A": 0,
    "MANAGED_CARE": 7,
    "PRIVATE": 30,
}

# PDPM NTA front-load (PRD §3.9): factor 3.00 for stay-days 1 through 3, else 1.00.
NTA_FRONTLOAD_FACTOR = 3.00
NTA_FRONTLOAD_DAYS = 3

# PT/OT variable-adjustment decay (PRD §3.9): 1.00 for days 1-20, then -0.02 per 7-day block.
PTOT_FULL_DAYS = 20
PTOT_STEP = 0.02
PTOT_STEP_PERIOD_DAYS = 7

# Quality-measure star cut points (PRD §3.1).
QM_BASELINE_MISSING = 50
QM_STAR_CUTS = {"five": 360, "four": 280, "three": 200, "two": 120}

# Standard pricing rate book used across claim-pricing test fixtures.
# These exact rate rows are the ones the difficulty/corner design recipes price against.
STANDARD_RATES = [
    {"component": "PT", "case_mix_group": "TB", "case_mix_index": 1.69, "base_rate_cents": 7000},
    {"component": "OT", "case_mix_group": "TB", "case_mix_index": 1.69, "base_rate_cents": 6000},
    {"component": "SLP", "case_mix_group": "SB", "case_mix_index": 1.46, "base_rate_cents": 2025},
    {"component": "NTA", "case_mix_group": "NB", "case_mix_index": 2.53, "base_rate_cents": 8000},
    {"component": "NURSING", "case_mix_group": "NURS", "case_mix_index": 1.00, "base_rate_cents": 10000},
]

# Hospital qualifying-stay datetimes that yield a 4-midnight (qualifying) stay.
QUALIFYING_HOSPITAL_ADMIT = "2026-01-25T10:00:00Z"
QUALIFYING_HOSPITAL_DISCHARGE = "2026-01-29T10:00:00Z"

# Standard admission day-1 anchor used throughout the design recipes.
STANDARD_ADMIT_AT = "2026-02-01T00:00:00Z"
RATE_EFFECTIVE_FROM = "2026-01-01T00:00:00Z"
