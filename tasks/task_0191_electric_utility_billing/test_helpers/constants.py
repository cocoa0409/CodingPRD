"""Domain thresholds and shared numeric constants for the Electric Utility
Billing API (PRD §2.6, §2.8, §3). NON_EXISTENT_UUID comes from the framework.
"""

# Arrears aging boundary (PRD §2.8): at least 45 whole days past due is
# IN_ARREARS; the 45-day boundary is inclusive.
THRESHOLDS = {
    "ARREARS_DAYS": 45,
}

# A syntactically valid UUID that should never resolve to a real resource.
NONEXISTENT_UUID = "00000000-0000-4000-8000-000000000000"

# The canonical residential TOU tariff used across the difficulty/corner
# scenarios: fixed 1000c, breakpoints [500,1000], rates [12,18,25]c/kWh,
# TOU multipliers 1.5/1.0/0.8, demand 800c/kW, net-metering 10c/kWh.
STANDARD_TARIFF = {
    "fixed_charge_cents": 1000,
    "tier_breakpoints_kwh": [500, 1000],
    "tier_rates_cents_per_kwh": [12, 18, 25],
    "tou_multipliers": {"ON_PEAK": 1.5, "MID_PEAK": 1.0, "OFF_PEAK": 0.8},
    "demand_charge_cents_per_kw": 800,
    "net_metering_credit_cents_per_kwh": 10,
}
