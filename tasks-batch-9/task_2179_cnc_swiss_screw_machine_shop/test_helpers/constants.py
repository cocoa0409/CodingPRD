"""Domain thresholds and shared literals drawn from the PRD narrative."""

# Identifier that names nothing, used for 404 probes.
MISSING_UUID = "00000000-0000-4000-8000-000000000000"

# The logical clock's reading before it is ever set.
LOGICAL_CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# Quote pricing (PRD section 3.3).
PRICING = {
    "SCRAP_ALLOWANCE_PCT": 0.02,
    "ATTENDED_RATE_CENTS_PER_HOUR": 9500,
    "LIGHTS_OUT_RATE_CENTS_PER_HOUR": 6200,
    "SETUP_RATE_CENTS_PER_HOUR": 11000,
    "SECONDARY_RATE_CENTS_PER_HOUR": 7400,
    "LIGHTS_OUT_MAX_FRACTION": 0.60,
    "MATERIAL_MARKUP_PCT": 0.18,
    "MARGIN_PCT": 0.22,
    "QUOTE_VALID_DAYS": 30,
}

# Blanket order rebate tiers (PRD section 3.4).
REBATE_TIERS = {
    "TIER_1_MIN_CENTS": 500_000,
    "TIER_2_MIN_CENTS": 2_000_000,
    "TIER_3_MIN_CENTS": 10_000_000,
    "TIER_0_PCT": 0.00,
    "TIER_1_PCT": 0.03,
    "TIER_2_PCT": 0.06,
    "TIER_3_PCT": 0.09,
}

# Bar length arithmetic (PRD sections 3.3 and 3.5).
BAR = {
    "PART_OFF_KERF_MM": 2.0,
    "SETUP_SCRAP_LENGTH_MM": 300,
    "BAR_REMNANT_MM": 150,
}

# Capability indices (PRD section 3.8 / 3.9).
CAPABILITY = {
    "D2_SUBGROUP_3": 1.693,
    "D2_SUBGROUP_5": 2.326,
    "CPK_MIN_DEFAULT": 1.33,
    "PPK_MIN_ACCEPT": 1.00,
}

# Tool wear (PRD section 3.7).
TOOL = {"DRIFT_LIMIT_UM_DEFAULT": 8}

# Gauge R&R gates (PRD section 3.8).
GAUGE_GRR = {"MAX_IN_SERVICE_PCT": 10, "RETIRE_ABOVE_PCT": 30}

# Chip / coolant / reclamation (PRD sections 3.7).
RECLAMATION = {
    "COOLANT_LITERS_PER_MACHINE_HOUR": 0.35,
    "COOLANT_COST_CENTS_PER_LITER": 420,
    "SCRAP_RATE_CENTS_PER_KG": {
        "303SS": 118,
        "316SS": 132,
        "C360": 465,
        "6061AL": 87,
        "12L14": 41,
    },
}

# Machine occupancy (PRD section 3.5).
SCHEDULING = {"CHANGEOVER_BUFFER_MINUTES": 45}

# Literals reused by the standard shop scenario the tests build.
SCENARIO = {
    "CLOCK": "2026-09-01T00:00:00Z",
    "WINDOW_START": "2026-09-02T06:00:00Z",
    "WINDOW_END": "2026-09-02T14:00:00Z",
    "DUE_AT": "2026-09-10T00:00:00Z",
    "PO_EXPIRES_ON": "2027-06-30T00:00:00Z",
}
