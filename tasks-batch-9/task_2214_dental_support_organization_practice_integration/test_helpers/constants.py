"""Domain thresholds and pinned numeric constants declared by the PRD."""

# Rates, ceilings and floors named verbatim in the PRD prose.
THRESHOLDS = {
    # PRD §2.5 — management fee cap at the moment of effectiveness.
    "MGMT_FEE_CAP_BPS": 2000,
    # PRD §2.5 — material fee erosion boundary (inclusive, negative).
    "MATERIAL_EROSION_CENTS": -500_000,
    # PRD §3.5 — chart validation tolerance.
    "VALIDATION_TOLERANCE_BPS": 200,
    # PRD §3.5 — mandatory separation between cutover windows.
    "CUTOVER_BUFFER_HOURS": 48,
    # PRD §3.6 — utilization blend factor applied per priced line.
    "UTILIZATION_BLEND_BPS": 6500,
    # PRD §3.6 / §3.3 — credentialing lead time in whole days.
    "CREDENTIALING_LEAD_DAYS_MIN": 90,
    # PRD §3.7 — consolidation realization factor.
    "REALIZATION_BPS": 8500,
    # PRD §3.7 — inclusive hygiene FTE ratio band.
    "STAFFING_RATIO_MIN_BPS": 8000,
    "STAFFING_RATIO_MAX_BPS": 25000,
    # PRD §3.8 — quality review sample floor and weighting.
    "QUALITY_SAMPLE_MIN": 20,
    "FINDING_WEIGHT_BPS": 6000,
    "OVERRIDE_WEIGHT_BPS": 4000,
    "ESCALATION_THRESHOLD_BPS": 8000,
    "PERFECT_SCORE_BPS": 10000,
    # PRD §3.9 — earn-out fee tiers, growth tiers and claims-lag holdback.
    "MGMT_FEE_TIER_LOW_BPS": 700,
    "MGMT_FEE_TIER_MID_BPS": 600,
    "MGMT_FEE_TIER_HIGH_BPS": 550,
    "MGMT_FEE_TIER_MID_FLOOR_CENTS": 150_000_000,
    "MGMT_FEE_TIER_HIGH_FLOOR_CENTS": 300_000_000,
    "MULTIPLE_TIER_ZERO_BPS": 0,
    "MULTIPLE_TIER_LOW_BPS": 25000,
    "MULTIPLE_TIER_MID_BPS": 35000,
    "MULTIPLE_TIER_HIGH_BPS": 45000,
    "GROWTH_TIER_MID_FLOOR_BPS": 800,
    "GROWTH_TIER_HIGH_FLOOR_BPS": 1500,
    "LAG_HOLDBACK_BPS": 250,
    "ANNUALIZATION_DAYS": 365,
    # PRD §3.4 — compensation harmonization uplift ceiling.
    "COMP_UPLIFT_CAP_BPS": 12500,
    # PRD §3.1 — repricing rounds available.
    "MAX_REPRICING_ROUNDS": 2,
    # PRD §2.3 — pagination bounds.
    "PAGINATION_LIMIT_DEFAULT": 10,
    "PAGINATION_LIMIT_MIN": 1,
    "PAGINATION_LIMIT_MAX": 100,
}

# The logical clock's mandated starting instant (PRD §2.4).
CLOCK_DEFAULT_UTC = "2026-08-01T00:00:00Z"

# Instants reused across the suite's setup chains.
CLOCK_CLOSE_DAY = "2026-09-01T00:00:00Z"

# Absent term_date is compared as this sentinel (PRD §3.6).
OPEN_ENDED_TERM_DATE = "9999-12-31T00:00:00Z"

# Identifiers that never resolve to a persisted row.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_UUID_ALT = "00000000-0000-0000-0000-0000000000ff"

# Default payload values reused by the factories.
TEST_DEFAULTS = {
    "SELLER_GROUP_NAME": "Elm Ridge Dental Group",
    "PURCHASE_PRICE_CENTS": 450_000_000,
    "EARNOUT_POOL_CENTS": 90_000_000,
    "BASELINE_EBITDA_CENTS": 90_000_000,
    "BASELINE_NET_COLLECTIONS_CENTS": 400_000_000,
    "POST_CLOSE_DOCTOR_TERM_MONTHS": 36,
    "VENDOR_NAME": "ChartBridge Conversions",
    "VENDOR_MAX_CONCURRENT_WINDOWS": 3,
    "PRACTICE_NAME": "Elm Street Dental",
    "PRACTICE_STATE_CODE": "IL",
    "CHARTS_TOTAL_EXPECTED": 5000,
    "DOCTOR_FULL_NAME": "Ana Reyes",
    "DOCTOR_NPI": "1710000001",
    "DOCTOR_LICENSE_NUMBER": "IL-DDS-4410",
    "BASE_SALARY_MONTHLY_CENTS": 1_800_000,
    "COLLECTIONS_PCT_BPS": 3000,
    "LEGACY_ANNUAL_COMP_CENTS": 24_000_000,
    "POST_CLOSE_TERM_MONTHS": 36,
    "NON_COMPETE_MONTHS": 24,
    "NON_COMPETE_RADIUS_MILES": 10,
    "MGMT_FEE_BPS": 1800,
    "SERVICE_CODE": "SVC-RCM-01",
    "SERVICE_DOMAIN": "BILLING",
    "MONTHLY_FEE_CENTS": 250_000,
    "PAYER_NAME": "Statewide Dental Plan",
    "PROCEDURE_CODE": "D0120",
    "LEGACY_ALLOWED_CENTS": 5503,
    "DSO_ALLOWED_CENTS": 4900,
    "ANNUAL_VOLUME": 100,
}

# Opaque operator identifiers (PRD §2.1) used where two distinct finance
# controller users are required.
FINANCE_RESERVER_USER_ID = "u-fin-reserver"
FINANCE_SETTLER_USER_ID = "u-fin-settler"

__all__ = [
    "THRESHOLDS",
    "CLOCK_DEFAULT_UTC",
    "CLOCK_CLOSE_DAY",
    "OPEN_ENDED_TERM_DATE",
    "UNKNOWN_UUID",
    "UNKNOWN_UUID_ALT",
    "TEST_DEFAULTS",
    "FINANCE_RESERVER_USER_ID",
    "FINANCE_SETTLER_USER_ID",
]
