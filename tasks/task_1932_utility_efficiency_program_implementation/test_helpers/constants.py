"""Domain thresholds — numeric constants named in PRD prose (sections 2.5, 3.3-3.9)."""

# Logical clock default before any set call (PRD 2.5).
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

# Incentive rate structure (PRD 3.4, 3.7):
# first 2,000 kWh at 25 cents/kWh, above that 12 cents/kWh, 80,000-cent cap,
# measure-cost baseline 500,000 cents for the final-variant cost adjustment.
TIER1_KWH = 2000
TIER1_RATE_PER_KWH_CENTS = 25
TIER2_RATE_PER_KWH_CENTS = 12
INCENTIVE_CAP_CENTS = 80000
MEASURE_COST_BASELINE_CENTS = 500000

# Contractor quality scoring (PRD 3.2, 3.6):
# rolling window of 10 most recent recorded inspections; a freshly registered
# contractor starts at 10,000 bps; auto-suspension below 5,000 bps.
QA_WINDOW_SIZE = 10
QA_INITIAL_BPS = 10000
QA_SUSPENSION_THRESHOLD_BPS = 5000

# Complaint rolling window (PRD 3.8).
COMPLAINT_WINDOW_DAYS = 90

# Cost-effectiveness reporting (PRD 3.9):
# 11 cents/kWh avoided cost, 12-year measure life, 4% discount rate,
# ratio rounded half up to 4 decimals; MARGINAL band is 0.10 below threshold.
AVOIDED_COST_PER_KWH_CENTS = 11
MEASURE_LIFE_YEARS = 12
DISCOUNT_RATE = 0.04
TRC_MARGINAL_BAND = 0.10

TEST_DEFAULTS = {
    "ZIP": "94110",
    "OTHER_ZIP": "10001",
    "BUDGET_CENTS": 500000,
    "KWH_TARGET": 10000,
    "TRC_THRESHOLD": 1.0,
    "CERT_ISSUED_ON": "2026-01-01T00:00:00Z",
    "CERT_EXPIRES_ON": "2027-01-01T00:00:00Z",
    "INSTALL_DATE": "2026-08-02T00:00:00Z",
    "INSTALL_START_CLOCK": "2026-08-02T09:00:00Z",
    "INSPECTION_DATE": "2026-08-03T00:00:00Z",
}
