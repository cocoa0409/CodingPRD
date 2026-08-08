"""Domain thresholds — numeric constants from PRD calculations."""

# Vehicle readiness threshold (PRD §3.2)
MIN_READY_SOC_PCT = 80

# Charger temporal-conflict cooldown buffer in minutes (PRD §3.3)
COOLDOWN_BUFFER_MINUTES = 30

# Logical clock startup default (PRD §2.6)
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"

CONNECTOR_TYPES = ["CCS", "CHADEMO", "J1772", "NACS"]

# A four-window Time-of-Use tariff that partitions the 24h UTC day, used by the
# dual-variant / TOU-allocation cost tests.
TOU_WINDOWS_FOUR = [
    {"period": "OFF_PEAK", "start_hour_utc": 0, "end_hour_utc": 6, "rate_cents_per_kwh": 10},
    {"period": "MID", "start_hour_utc": 6, "end_hour_utc": 16, "rate_cents_per_kwh": 20},
    {"period": "PEAK", "start_hour_utc": 16, "end_hour_utc": 21, "rate_cents_per_kwh": 40},
    {"period": "NIGHT", "start_hour_utc": 21, "end_hour_utc": 24, "rate_cents_per_kwh": 10},
]

# A single flat window (rate 20 c/kWh) covering the whole day.
FLAT_WINDOWS = [{"period": "FLAT", "start_hour_utc": 0, "end_hour_utc": 24, "rate_cents_per_kwh": 20}]

TEST_DEFAULTS = {
    "MAX_LOAD_KW": 500,
    "CONTRACTED_CAPACITY_KW": 300,
    "DEMAND_RATE": 1000,
    "OVERAGE_RATE": 2500,
    "REIMBURSEMENT_BUDGET_CENTS": 100000,
    "BATTERY_KWH": 100,
    "EFFICIENCY_KWH_PER_KM": 0.2,
    "HOME_TARIFF": 15,
}
