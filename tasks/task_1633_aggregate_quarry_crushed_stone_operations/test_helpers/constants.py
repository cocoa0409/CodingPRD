"""Domain thresholds and numeric constants from the PRD.

Sources: PRD units/precision section, pricing tiers, tolerances, windows,
and the logical-clock default.
"""

# Units and conversions (PRD: units, precision, and rounding)
ROCK_DENSITY_T_PER_YD3 = 1.6
YD3_PER_FT3 = 27
LBS_PER_TON = 2000

# Logical clock default at server startup (PRD: the logical clock)
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
BLAST_WINDOW_START_HOUR = 8   # inclusive
BLAST_WINDOW_END_HOUR = 17    # exclusive

# Calibration / certification (PRD: scale-house operations)
CALIBRATION_PASS_TOLERANCE_PCT = 0.25
CERTIFICATION_WINDOW_DAYS = 180

# Weigh-out tolerances (PRD: scale-house operations)
TARE_VARIANCE_TOLERANCE_PCT = 2.00
OVER_SHIPMENT_FACTOR = 1.10

# Plant run gates (PRD: plant runs)
OUTPUT_BALANCE_TOLERANCE = 0.03
RECONCILE_TOLERANCE = 0.02
CIRCUIT_COOLDOWN_MINUTES = 30

# Delivered pricing tiers (PRD: freight zones and delivered pricing)
VOLUME_TIER_1_MAX = 100
VOLUME_TIER_2_MAX = 1000
VOLUME_FACTOR_T1 = 1.00
VOLUME_FACTOR_T2 = 0.95
VOLUME_FACTOR_T3 = 0.90
SURCHARGE_TIER_1_MAX = 20.00
SURCHARGE_TIER_2_MAX = 40.00
SURCHARGE_PCT_T1 = 0.08
SURCHARGE_PCT_T2 = 0.12
SURCHARGE_PCT_T3 = 0.15

# Royalty statement payment terms (PRD: royalty statements)
PAYMENT_TERM_DAYS = 30
LATE_PENALTY_PCT = 0.05

# Standard reference data used across tests
DEFAULT_SITE = {
    "name": "Quarry Q1",
    "permitted_acres": 200,
    "bond_rate_per_acre_usd": 12000,
}
DEFAULT_BENCH = {
    "bench_label": "BENCH-1400",
    "elevation_ft": 1400,
    "acreage": 5.0,
}
DEFAULT_SHOT_PLAN = {
    "hole_count": 20,
    "burden_ft": 8,
    "spacing_ft": 10,
    "hole_depth_ft": 40,
    "explosive_per_hole_lbs": 50,
}
# 20*8*10*40 / 27 yd3 x 1.6 t/yd3 = 3792.592... -> 3792.6 (1 dp round half-up)
DEFAULT_SHOT_PLAN_ESTIMATED_TONS = 3792.6
DEFAULT_AGREEMENT = {
    "landowner_name": "LW",
    "base_rate_per_ton": 0.25,
    "tier_threshold_tons": 50,
    "tier_rate_per_ton": 0.40,
    "effective_from": "2026-01-01",
}
DEFAULT_ZONE = {
    "zone_code": "Z-LOCAL",
    "distance_miles": 25,
    "base_freight_per_ton": 6.00,
}
DEFAULT_TRUCK = {
    "certified_tare_lbs": 28000,
    "max_payload_lbs": 70000,
}
