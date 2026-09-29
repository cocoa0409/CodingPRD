"""Statutory constants and the pre-computed expectations of the shared chains.

Every figure below is either quoted directly from the PRD or derived from the
canonical portfolio the fixtures build, using the PRD's own step order. Test
bodies assert against these literals rather than recomputing them, so a test
never mirrors an implementation's arithmetic.
"""

# --------------------------------------------------------------------------- #
# Statutory ladders and thresholds (PRD §3.2, §3.6, §3.7, §3.8, §3.9)
# --------------------------------------------------------------------------- #
TIER_FACTORS_BPS = [2500, 5000, 7500, 10000]
JUDGMENTAL_CAP_BPS = 1000
SHORTFALL_TRIGGER_BPS = 150
METHODOLOGY_FLAG_BPS = 500
ERROR_WINDOW_YEARS = 3
CUSHION_CREDIT_BPS = 200
BLACKOUT_HOURS = 48
VOTE_WINDOW_DAYS = 7

TARGET_BAND_LOW_BPS = 500
TARGET_BAND_MID_BPS = 800
TARGET_BAND_HIGH_BPS = 1200
VOLATILITY_BAND_LOW_MAX_BPS = 300
VOLATILITY_BAND_MID_MAX_BPS = 800

COVERAGE_STRONG_BPS = 10000
COVERAGE_ADEQUATE_BPS = 6000
COVERAGE_THIN_BPS = 3000

SCENARIO_WEIGHT_TOTAL_BPS = 10000
RATIONALE_MIN_LENGTH = 20
NARRATIVE_MIN_LENGTH = 20

# Pagination (PRD §2.3)
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100

# Logical clock (PRD §2.5)
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------- #
# The canonical fiscal year and cycle
# --------------------------------------------------------------------------- #
FISCAL_YEAR = 2027
FY_FIRST_DAY = "2026-07-01"
FY_LAST_DAY = "2027-06-30"

ENACTED_APPROPRIATION_CENTS = 1_650_000_000
PRIOR_RECURRING_BASELINE_CENTS = 1_500_000_000

# --------------------------------------------------------------------------- #
# The canonical revenue portfolio
# --------------------------------------------------------------------------- #
PIT_BASE_RECEIPTS_CENTS = 1_234_567_800
PIT_ELASTICITY_EMPLOYMENT_BPS = 4150
PIT_ELASTICITY_WAGE_BPS = 7825
PIT_ELASTICITY_RETAIL_BPS = 640
PIT_ELASTICITY_ASSET_BPS = 1420

CGT_BASE_RECEIPTS_CENTS = 312_345_600
CGT_ELASTICITY_EMPLOYMENT_BPS = 0
CGT_ELASTICITY_WAGE_BPS = 2075
CGT_ELASTICITY_RETAIL_BPS = 0
CGT_ELASTICITY_ASSET_BPS = 8940

# --------------------------------------------------------------------------- #
# The canonical scenario set: weights sum to exactly 10000 bps
# --------------------------------------------------------------------------- #
SCENARIO_BASELINE = {
    "label": "BASELINE",
    "weight_bps": 6000,
    "employment_growth_bps": 150,
    "wage_income_bps": 400,
    "retail_sales_bps": 300,
    "asset_market_return_bps": 600,
}
SCENARIO_OPTIMISTIC = {
    "label": "OPTIMISTIC",
    "weight_bps": 2500,
    "employment_growth_bps": 300,
    "wage_income_bps": 700,
    "retail_sales_bps": 600,
    "asset_market_return_bps": 1500,
}
SCENARIO_PESSIMISTIC = {
    "label": "PESSIMISTIC",
    "weight_bps": 1500,
    "employment_growth_bps": -100,
    "wage_income_bps": 100,
    "retail_sales_bps": -200,
    "asset_market_return_bps": -1000,
}
CANONICAL_SCENARIOS = [SCENARIO_BASELINE, SCENARIO_OPTIMISTIC, SCENARIO_PESSIMISTIC]

# Per-scenario growth rates and revenue amounts for the PIT source.
PIT_SCENARIO_GROWTH_BPS = {"BASELINE": 480, "OPTIMISTIC": 924, "PESSIMISTIC": -118}
PIT_SCENARIO_AMOUNTS_CENTS = {
    "BASELINE": 1_293_827_054,
    "OPTIMISTIC": 1_348_641_865,
    "PESSIMISTIC": 1_219_999_900,
}
PIT_WEIGHTED_SCENARIO_CENTS = 1_296_456_684
# The forbidden shortcut — blending the growth rates first — lands here instead.
PIT_RATE_FIRST_SHORTCUT_CENTS = 1_296_419_647

CGT_SCENARIO_GROWTH_BPS = {"BASELINE": 619, "OPTIMISTIC": 1486, "PESSIMISTIC": -873}
CGT_SCENARIO_AMOUNTS_CENTS = {
    "BASELINE": 331_679_793,
    "OPTIMISTIC": 358_760_156,
    "PESSIMISTIC": 285_077_829,
}
CGT_WEIGHTED_SCENARIO_CENTS = 331_459_589

# --------------------------------------------------------------------------- #
# The canonical statutory policy changes
# --------------------------------------------------------------------------- #
# PIT: a prorated decrease whose half-open window covers nine months of FY2027.
PIT_POLICY_ANNUALIZED_CENTS = 50_000_000
PIT_POLICY_START_DATE = "2026-10-01"
PIT_POLICY_END_DATE = "2027-07-01"
PIT_POLICY_MONTHS = 9
PIT_POLICY_ADJUSTMENT_CENTS = -37_500_000

# CGT: a tiered increase in its first effective year, bitten by its own cap.
CGT_POLICY_ANNUALIZED_CENTS = 20_000_000
CGT_POLICY_CAP_CENTS = 4_000_000
CGT_POLICY_RAW_CENTS = 5_000_000
CGT_POLICY_ADJUSTMENT_CENTS = 4_000_000

# --------------------------------------------------------------------------- #
# The canonical non-recurring receipt
# --------------------------------------------------------------------------- #
ONE_TIME_AMOUNT_CENTS = 12_000_000

# --------------------------------------------------------------------------- #
# SHORT chain — the PIT source alone, no policy change, no one-time item
# --------------------------------------------------------------------------- #
SHORT_ESTIMATE_CENTS = 1_296_456_684
SHORT_EXEC_TOTAL_CENTS = 1_296_456_684
SHORT_LEG_TOTAL_CENTS = 1_296_456_684
SHORT_VARIANCE_BPS = 0
SHORT_RECONCILED_TOTAL_CENTS = 1_296_456_684
SHORT_CERTIFIED_TOTAL_CENTS = 1_296_456_684
SHORT_CERTIFIED_ONE_TIME_CENTS = 0
SHORT_CERTIFIED_RECURRING_CENTS = 1_296_456_684
SHORT_SHORTFALL_GAP_CENTS = 353_543_316
SHORT_SHORTFALL_PCT_BPS = 2142
SHORT_CAP_CENTS = 129_645_668
SHORT_REQUIRED_RESERVE_CENTS = 64_822_834

# --------------------------------------------------------------------------- #
# FULL chain — both sources, both policy changes, the one-time item
# --------------------------------------------------------------------------- #
EXEC_PIT_ESTIMATE_CENTS = 1_258_956_684
EXEC_CGT_ESTIMATE_CENTS = 347_459_589
EXEC_TOTAL_CENTS = 1_606_416_273

LEG_PIT_JUDGMENTAL_CENTS = -8_000_000
LEG_CGT_JUDGMENTAL_CENTS = -3_000_000
LEG_PIT_ESTIMATE_CENTS = 1_250_956_684
LEG_CGT_ESTIMATE_CENTS = 344_459_589
LEG_TOTAL_CENTS = 1_595_416_273

PIT_SOURCE_MIDPOINT_CENTS = 1_254_956_684
CGT_SOURCE_MIDPOINT_CENTS = 345_959_589
PIT_SOURCE_VARIANCE_BPS = 64
CGT_SOURCE_VARIANCE_BPS = 87
GRAND_MIDPOINT_CENTS = 1_600_916_273
GRAND_VARIANCE_BPS = 69

VARIANCE_TOLERANCE_BPS = 150
PER_SOURCE_TOLERANCE_BPS = 150

MIDPOINT_AVERAGE_RECONCILED_CENTS = 1_600_916_273
LOWER_OF_TWO_RECONCILED_CENTS = 1_595_416_273
RECONCILIATION_POLICY_DELTA_CENTS = 5_500_000

# Dispute variant: the legislative CGT figure is pushed far enough out that the
# per-source tolerance breaks on CGT alone while PIT stays comfortably inside.
DISPUTE_LEG_CGT_JUDGMENTAL_CENTS = -30_000_000
DISPUTE_LEG_CGT_ESTIMATE_CENTS = 317_459_589
DISPUTE_LEG_TOTAL_CENTS = 1_568_416_273
DISPUTE_CGT_SOURCE_VARIANCE_BPS = 902
DISPUTE_GRAND_VARIANCE_BPS = 239
DISPUTE_LEG_VALUE_RECONCILED_CENTS = 1_572_416_273

# --------------------------------------------------------------------------- #
# Certification of the FULL chain
# --------------------------------------------------------------------------- #
CERTIFIED_TOTAL_CENTS = 1_600_916_273
CERTIFIED_ONE_TIME_CENTS = 12_000_000
CERTIFIED_RECURRING_CENTS = 1_588_916_273
CERTIFIED_SHORTFALL_GAP_CENTS = 49_083_727
CERTIFIED_SHORTFALL_PCT_BPS = 297

# --------------------------------------------------------------------------- #
# Reserve fund parameters and the deposit waterfall
# --------------------------------------------------------------------------- #
FUND_CAP_PCT_BPS = 1000
FUND_TREND_GROWTH_RATE_BPS = 300
FUND_CAPTURE_RATE_BPS = 5000
FUND_ELIGIBLE_SEATS = 11
FUND_ANNUAL_WITHDRAWAL_CAP_PCT_BPS = 3000
FUND_COOLING_OFF_DAYS = 30

GROWTH_TREND_LINE_CENTS = 1_545_000_000
GROWTH_EXCESS_CENTS = 43_916_273
GROWTH_GROSS_COMPUTED_CENTS = 21_958_137

VOLATILE_MEASURED_CENTS = 333_959_589
VOLATILE_TREND_LINE_CENTS = 321_715_968
VOLATILE_EXCESS_CENTS = 12_243_621
VOLATILE_GROSS_COMPUTED_CENTS = 6_121_811

FUND_CAP_CENTS = 160_091_627

# Opening balance 50,000,000 — the whole gross amount fits under the cap.
FUND_OPENING_BALANCE_CENTS = 50_000_000
FUND_BALANCE_AFTER_DEPOSIT_CENTS = 71_958_137

# Opening balance that leaves headroom exactly equal to the gross amount.
FUND_OPENING_EXACT_FILL_CENTS = 138_133_490

# Opening balance that leaves less headroom than the gross amount.
FUND_OPENING_OVERFLOW_CENTS = 155_000_000
FUND_OVERFLOW_DEPOSITED_CENTS = 5_091_627
FUND_OVERFLOW_RETURNED_CENTS = 16_866_510

# --------------------------------------------------------------------------- #
# Adequacy disclosure against the certified FULL chain
# --------------------------------------------------------------------------- #
ADEQUACY_REQUIRED_RESERVE_CENTS = 79_445_814
ADEQUACY_BALANCE_ADEQUATE_CENTS = 71_958_137
ADEQUACY_COVERAGE_ADEQUATE_BPS = 9057
ADEQUACY_BALANCE_STRONG_EXACT_CENTS = 79_445_814
ADEQUACY_COVERAGE_STRONG_EXACT_BPS = 10000
ADEQUACY_BALANCE_ONE_CENT_SHORT_CENTS = 79_445_813
ADEQUACY_COVERAGE_ONE_CENT_SHORT_BPS = 9999
ADEQUACY_BALANCE_AT_CAP_CENTS = 160_091_627
ADEQUACY_COVERAGE_AT_CAP_BPS = 20151

# Flagging the PIT source at exactly 500 bps lifts the receipts-weighted index
# to 399 bps, which crosses out of the lowest statutory target band.
FLAGGED_VOLATILITY_INDEX_BPS = 399
FLAGGED_TARGET_PCT_BPS = 800
FLAGGED_REQUIRED_RESERVE_CENTS = 127_113_302
FLAGGED_COVERAGE_BPS = 12594
FLAGGED_DISCLOSED_TARGET_PCT_BPS = 600

# --------------------------------------------------------------------------- #
# Shortfall sizing against the certified FULL chain total
# --------------------------------------------------------------------------- #
SHORTFALL_ENACTED_297_BPS = 1_650_000_000
SHORTFALL_ENACTED_150_BPS = 1_625_295_709
SHORTFALL_ENACTED_149_BPS = 1_625_295_708
SHORTFALL_ENACTED_ZERO = 1_550_000_000

# --------------------------------------------------------------------------- #
# Ballot requirements at eleven eligible seats
# --------------------------------------------------------------------------- #
VOTES_REQUIRED = 8
QUORUM_REQUIRED = 6

FY_WITHDRAWAL_CAP_CENTS = 21_587_441
WITHDRAWAL_REQUESTED_OVER_CAP_CENTS = 30_000_000
WITHDRAWAL_AUTHORIZED_AT_CAP_CENTS = 21_587_441

# --------------------------------------------------------------------------- #
# Forecast error scoring against the matched per-source PIT figure
# --------------------------------------------------------------------------- #
MATCHED_PIT_FORECAST_CENTS = 1_254_956_684
ACTUAL_499_BPS_CENTS = 1_192_271_598
ACTUAL_500_BPS_CENTS = 1_192_271_597
ERROR_499_BPS = 499
ERROR_500_BPS = 500

# --------------------------------------------------------------------------- #
# Miscellaneous fixed strings
# --------------------------------------------------------------------------- #
VALID_RATIONALE = "Documented resolution rationale for the estimating body record."
VALID_NARRATIVE = "Reserve adequacy narrative prepared for the rating agencies."
VALID_MEMO = "Manual deposit posted by the reserve treasurer."
