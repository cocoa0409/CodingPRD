"""Domain constants: pinned calculation constants and standard fixture values.

Every value below is named in the PRD (§2.6 logical clock, §3.1 aid-year setup,
§3.2 SAP thresholds, §3.3 EFC methodology, §3.6 Pell proration and Stafford
caps). Tests import these instead of re-deriving literals.
"""

# --- Logical clock (PRD §2.6) -------------------------------------------------
# "Before any clock-setting call has been made, the logical clock reads exactly
# 2026-08-01T00:00:00Z".
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"
# Standard test clock reading: after the priority deadline, inside the import
# window of any aid year created while this reading is in effect.
CLOCK_TEST = "2026-09-01T00:00:00Z"

# --- Standard aid-year fixture (PRD §3.1) --------------------------------------
YEAR_CODE = "2026-2027"
COA_IN_STATE_CENTS = 2_400_000
COA_OUT_OF_STATE_CENTS = 3_600_000
PRIORITY_DEADLINE = "2026-03-01T00:00:00Z"
VERIFICATION_FLAG_RATE = 0.50
# Receipt stamp at or before the priority deadline -> PRIORITY cohort (§3.3).
ISIR_RECEIVED_PRIORITY = "2026-02-01T00:00:00Z"

# Standard Pell schedule: rows sorted by efc_min ascending, contiguous,
# covering the full EFC range (shape validated when the aid year opens, §3.1).
DEFAULT_PELL_SCHEDULE = [
    {"efc_min": 0, "efc_max": 150000, "award_cents": 739500},
    {"efc_min": 150001, "efc_max": 300000, "award_cents": 500000},
    {"efc_min": 300001, "efc_max": 500000, "award_cents": 250000},
    {"efc_min": 500001, "efc_max": 99999900, "award_cents": 0},
]

# --- SSNs with deterministic verification-selection outcomes (PRD §3.3) -------
# Selection residue = sha256(ssn + '-' + year_code) mod 10000, compared against
# rate*10000 (= 5000 at the standard 0.50 rate).
SSN_SELECTED_A = "111223333"      # residue 3214 -> SELECTED
SSN_SELECTED_B = "555667777"      # residue 141  -> SELECTED
SSN_SELECTED_C = "444556666"      # residue 3724 -> SELECTED
SSN_SELECTED_D = "987654321"      # residue 1343 -> SELECTED
SSN_NOT_SELECTED_A = "333445555"  # residue 5347 -> NOT_SELECTED
SSN_NOT_SELECTED_B = "123456789"  # residue 7666 -> NOT_SELECTED

# --- EFC methodology constants (PRD §3.3) --------------------------------------
IPA_TABLE = {
    "DEPENDENT": [1000000, 1500000, 2000000, 2400000, 2800000],
    "INDEPENDENT": [1700000, 2200000, 2600000, 3000000, 3300000],
}
TIER1_MAX = 500000
TIER1_RATE = 0.22
TIER2_MAX = 1500000
TIER2_RATE = 0.35
TIER3_RATE = 0.47
ASSET_RATE = 5.64
ASSET_ALLOWANCE = 1000000
EFC_FLOOR = 0
EFC_CAP = 99999900

# --- Pell proration percentages (PRD §3.6) --------------------------------------
PRORATION = {
    "FULL_TIME": 100,
    "THREE_QUARTER": 75,
    "HALF_TIME": 50,
    "LESS_THAN_HALF": 0,
}

# --- Stafford annual caps by grade level (PRD §3.6) ------------------------------
SUB_CAP = {
    "DEPENDENT": [350000, 450000, 550000, 550000, 550000],
    "INDEPENDENT": [350000, 450000, 550000, 550000, 550000],
}
UNSUB_CAP = {
    "DEPENDENT": [200000, 200000, 200000, 200000, 200000],
    "INDEPENDENT": [600000, 600000, 700000, 700000, 700000],
}

# --- SAP thresholds (PRD §3.2) ---------------------------------------------------
GPA_FLOOR_HUNDREDTHS = 200
PACE_FLOOR_BPS = 6667
MAX_TIMEFRAME_DEFAULT_CREDITS = 180

# --- Pinned EFC outcomes for the standard fixtures --------------------------------
# agi 4_500_000, untaxed 0, assets 50_000, household 4, in-college 1, DEPENDENT.
EFC_FIXTURE_AGI_45000 = 742000
# Same household with AGI corrected to 5_200_000.
EFC_FIXTURE_AGI_52000 = 1071000
# agi 2_000_000 household 4 DEPENDENT -> EFC 0 (income below the allowance).
EFC_FIXTURE_ZERO = 0

# Standard fund spec: PELL as an entitlement (pool check skipped, §2.10/§3.6).
FUND_SPEC_PELL = {
    "fund_code": "PELL",
    "category": "FEDERAL_TITLE_IV",
    "need_based": True,
    "annual_cap_cents": 739500,
    "pool_budget_cents": 0,
    "packaging_rank": 1,
    "requires_verification_complete": False,
}
