"""Domain thresholds — numeric constants named in the PRD (§3)."""

THRESHOLDS = {
    # §3.3: a loan at or above one hundred million cents is individually evaluated
    "INDIVIDUAL_EVAL_THRESHOLD_CENTS": 100_000_000,
    # §3.3: a recomputed segment charge-off rate strictly above 200 bps flips WATCH
    "WATCH_RATE_THRESHOLD_BPS": 200,
    # §3.1: back-test breach when |variance| is strictly greater than 150 bps
    "BREACH_VARIANCE_THRESHOLD_BPS": 150,
    # §3.1: refresh_required flips true when consecutive breaches reach 2
    "BREACH_COUNT_THRESHOLD": 2,
    # §3.7: collateral cost-to-sell haircut of 1000 bps (ten percent)
    "COST_TO_SELL_BPS": 1000,
    # §3.7: management adjustment proportionality cap of 10% of the subtotal
    "CAP_PERCENT": 0.10,
    # §3.4: neutral unemployment anchor and sensitivity
    "U_NEUTRAL_BPS": 500,
    "SENS_U": 20,
    # §3.4: neutral growth anchor and sensitivity
    "GDP_NEUTRAL_BPS": 200,
    "SENS_G": 10,
    # §3.4: multiplier clamp bounds
    "MIN_MULT_BPS": 5_000,
    "MAX_MULT_BPS": 30_000,
    # §3.6: remaining life over which the multiplier reverts
    "REMAINING_LIFE_QUARTERS": 8,
    # §3.6: scenario weights must sum to exactly ten thousand basis points
    "WEIGHT_SUM_BPS": 10_000,
}

# §3.2: base annual lifetime loss rate by risk band
BASE_RATE_BY_BAND = {
    "PRIME": 50,
    "NEAR_PRIME": 150,
    "SUBPRIME": 400,
    "DEEP_SUBPRIME": 900,
}

TEST_DEFAULTS = {
    "MODEL_NAME": "CECL-LR",
    "FORECAST_PERIOD_QUARTERS": 2,
    "REVERSION_METHOD": "IMMEDIATE",
    "REVERSION_PERIOD_QUARTERS": 0,
    "HISTORICAL_LOOKBACK_QUARTERS": 8,
    "AS_OF_PERIOD": "2026-Q1",
    "WINDOW_FROM": "2026-Q1",
    "WINDOW_TO": "2027-Q1",
    "BASELINE_UNEMPLOYMENT_BPS": 500,
    "BASELINE_GDP_GROWTH_BPS": 200,
    "ADVERSE_UNEMPLOYMENT_BPS": 900,
    "ADVERSE_GDP_GROWTH_BPS": 0,
}
