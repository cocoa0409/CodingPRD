"""Domain thresholds — numeric constants stated in the PRD narratives (§2.5, §3)."""

THRESHOLDS = {
    # Certification cycle (PRD §3.2): initial 12 years, VISUAL recert +5, HYDROSTATIC +7
    "INITIAL_CERT_YEARS": 12,
    "VISUAL_RECERT_YEARS": 5,
    "HYDROSTATIC_RECERT_YEARS": 7,
    # Refill (PRD §3.4): 0.42 fill factor, 0.10 lbs tare tolerance
    "PROPANE_FILL_FACTOR": 0.42,
    "TARE_TOLERANCE_LBS": 0.10,
    # Commission (PRD §3.7): $250.00 leak penalty, 62-day max period
    "LEAK_PENALTY_CENTS": 25000,
    "MAX_STATEMENT_PERIOD_DAYS": 62,
    # Reconciliation (PRD §3.8): 500-cent inclusive cash-variance flag threshold
    "VARIANCE_TOLERANCE_CENTS": 500,
    # Restock forecast (PRD §3.6): trailing 14-day half-open window
    "FORECAST_WINDOW_DAYS": 14,
    # DOT payload weights (PRD §3.6)
    "FULL_CYLINDER_LBS": 37,
    "EMPTY_CYLINDER_LBS": 17,
    # Reorder floor ratio (PRD §2.8): par_level_full * 0.5 rounded up
    "PAR_FLOOR_RATIO": 0.5,
}

# Standard pricing policy P used across tests:
# swap 2499, deposit 3500, tax 825bps, refill tiers 349/299 with 15.00 lbs breakpoint,
# effective 2026-05-01 (the startup logical date).
POLICY_P = {
    "swap_price_cents": 2499,
    "core_deposit_cents": 3500,
    "tax_rate_bps": 825,
    "refill_tier1_cents_per_lb": 349,
    "refill_tier1_max_lbs": 15.00,
    "refill_tier2_cents_per_lb": 299,
    "effective_from": "2026-05-01",
}

# Derived standard money figures under POLICY_P (PRD §3.3/§3.4 math):
# swap with return: tax = round_half_up(2499 * 825 / 10000) = 206; total = 2705
SWAP_WITH_RETURN_TAX_CENTS = 206
SWAP_WITH_RETURN_TOTAL_CENTS = 2705
# swap without return: subtotal 5999; tax = round_half_up(5999 * 825 / 10000) = 495; total 6494
SWAP_NO_RETURN_TAX_CENTS = 495
SWAP_NO_RETURN_TOTAL_CENTS = 6494
# refill of 18.50 lbs: tier1 15.00*349 = 5235; tier2 round_half_up(3.50*299) = 1047;
# charge 6282; with hazmat 75 -> total 6357
REFILL_18_50_CHARGE_CENTS = 6282
# max fill of a WC=47.60 cylinder: round_half_up(47.60 * 0.42, 2) = 19.99
MAX_FILL_47_60_LBS = 19.99

TEST_DEFAULTS = {
    "OPENING_FLOAT_CENTS": 20000,
    "CAGE_CAPACITY": 20,
    "PAR_LEVEL_FULL": 12,
    "COMMISSION_RATE_BPS": 1000,
    "WATER_CAPACITY_LBS": 47.60,
    "TARE_WEIGHT_LBS": 17.00,
    "MANUFACTURE_DATE": "2020-01-15",
    "STARTUP_DATE": "2026-05-01",
    "STARTUP_ISO": "2026-05-01T00:00:00Z",
}
