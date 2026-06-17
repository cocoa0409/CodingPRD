"""Domain thresholds — numeric constants from the PRD calculations (§3.2, §3.5, §3.6, §3.8)."""

# Fuel volume-tier pricing (§3.2): cumulative-gallon tier ceilings and per-gallon discounts.
TIER1_CEIL = 5_000           # gallon cumulative index < 5000 → no discount
TIER2_CEIL = 20_000          # 5000 <= index < 20000 → TIER2 discount; >= 20000 → TIER3 discount
TIER2_DISCOUNT_CENTS = 5
TIER3_DISCOUNT_CENTS = 12

# Parking / ramp fee (§3.5): per-night cents keyed on aircraft weight class.
RAMP_RATE_CENTS = {"LIGHT": 7_500, "MID": 15_000, "HEAVY": 32_500}
WAIVER_MIN_GAL = 200         # >= 200 delivered Jet-A gallons on a RAMP spot waives the fee

# Into-plane reconciliation tolerance (§3.6).
TOLERANCE_PCT = 2.00         # abs(variance_pct) <= 2.00 reconciles

# De-ice service charge (§3.8).
FLUID_RATE_CENTS = 1_800
DILUTION = {"TYPE_I": 1.0, "TYPE_IV": 1.4}
FREE_HOLDOVER_MIN = 15
HOLDOVER_RATE_CENTS_PER_MIN = 400

# Aircraft weight-class boundaries (§3.1).
WEIGHT_LIGHT_CEIL = 12_500   # mtow_lb < 12500 → LIGHT
WEIGHT_MID_CEIL = 41_000     # 12500 <= mtow_lb < 41000 → MID; >= 41000 → HEAVY

# Pagination defaults (§2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100

# Common timestamps used by setup chains (mirror the design-index literals).
ARRIVAL_UTC = "2026-06-14T08:00:00.000Z"
DEPARTURE_UTC_1_NIGHT = "2026-06-15T08:00:00.000Z"
DEPARTURE_UTC_3_NIGHT = "2026-06-17T08:00:00.000Z"

# Standard contract figures used across setups.
DEFAULT_BASE_PRICE_CENTS_PER_GAL = 520
DEFAULT_TANKERING_FEE_CENTS_PER_GAL = 30
DEFAULT_MTOW_MID = 30_000     # → MID weight class
