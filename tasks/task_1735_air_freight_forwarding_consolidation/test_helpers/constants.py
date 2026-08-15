"""Domain thresholds and shared fixture values from the PRD (§2.7-§2.9, §3.5, §3.8)."""

# Rating constants (PRD §3.5)
DIM_FACTOR_M3_PER_KG = 0.006          # IATA volumetric divisor: 1 kg per 6000 cm3
CHARGEABLE_ROUNDING_STEP_KG = 0.5     # chargeable weight always ceils to the next 0.5 kg
SPOT_SURCHARGE_THRESHOLD_PCT = 85.00  # inclusive snapshot utilization threshold

# Claim liability constants (PRD §3.8)
SDR_PER_KG = 22
SDR_TO_USD = 1.35

# Demerit ledger (PRD §3.3): the third rejection suspends a KNOWN shipper
DEMERIT_LIMIT = 3

# Tender window spacing (PRD §3.6)
TENDER_WINDOW_BUFFER_MINUTES = 30

# Logical clock fixed startup default (PRD §2.9)
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Claim filing windows in days from delivered_at_utc (PRD §3.7 filing rules)
CLAIM_FILING_WINDOW_DAYS = {"DAMAGE": 14, "SHORTAGE": 14, "DELAY": 21, "LOSS": 21}

# Standard lane fixture values (SFO -> NRT)
STANDARD_ORIGIN = "SFO"
STANDARD_DESTINATION = "NRT"
STANDARD_DEPARTURE_UTC = "2026-08-10T10:00:00Z"
STANDARD_CUTOFF_UTC = "2026-08-09T10:00:00Z"
STANDARD_TENDER_WINDOW_START = "2026-08-09T12:00:00Z"
STANDARD_TENDER_WINDOW_END = "2026-08-09T13:00:00Z"
STANDARD_AGREEMENT_VALID_FROM = "2026-01-01T00:00:00Z"
STANDARD_AGREEMENT_VALID_TO = "2027-01-01T00:00:00Z"

# Standard weight-break tariff: [0:5.00, 45:4.50, 100:4.00], min 250.00,
# fuel 12.5%, security 25.00, spot 7.5%.
STANDARD_WEIGHT_BREAKS = [
    {"min_weight_kg": 0, "rate_per_kg": 5.00},
    {"min_weight_kg": 45, "rate_per_kg": 4.50},
    {"min_weight_kg": 100, "rate_per_kg": 4.00},
]
STANDARD_MIN_CHARGE = 250.00
STANDARD_FUEL_PCT = 0.125
STANDARD_SECURITY_FEE = 25.00
STANDARD_SPOT_PCT = 0.075

# Milestone timeline used to fly a master waybill to DELIVERED
MILESTONE_DEPARTED_UTC = "2026-08-10T10:00:00Z"
MILESTONE_ARRIVED_UTC = "2026-08-10T22:00:00Z"
MILESTONE_DELIVERED_UTC = "2026-08-11T09:00:00Z"
CLAIM_FILING_CLOCK_UTC = "2026-08-11T12:00:00Z"
