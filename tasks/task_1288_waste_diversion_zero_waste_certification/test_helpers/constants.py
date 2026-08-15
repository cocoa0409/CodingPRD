"""Domain thresholds and shared test defaults (PRD §2.6, §3.7, §3.8)."""

TON_LBS = 2000

# Contamination severity floors (inclusive at floor).
SEVERITY_MAJOR_FLOOR = 5
SEVERITY_CRITICAL_FLOOR = 10

# Certification thresholds (inclusive at boundary).
CERT_THRESHOLDS = {
    "BRONZE": 50.0,
    "SILVER": 70.0,
    "GOLD": 85.0,
    "ZERO_WASTE": 90.0,
}

# Diverted disposal routes.
DIVERTED_ROUTES = ("RECYCLING", "COMPOSTING", "REUSE")

# Shared test fixture defaults (mirror the design-index conventions).
DEFAULT_SITE_PAYLOAD = {
    "name": "Site",
    "landfill_tip_fee_per_ton_cents": 5500,
    "max_rebate_rate_per_ton_cents": 12000,
}
DEFAULT_CONTRACT_TERMS = {
    "material_stream": "MIXED_RECYCLABLES",
    "rebate_per_ton_cents": 10000,
    "contamination_penalty_per_ton_cents": 2000,
    "window_start": "2026-01-01",
    "window_end": "2026-12-31",
}
DEFAULT_PERIOD_WINDOW = {
    "period_start": "2026-08-01",
    "period_end": "2026-09-01",
}
DEFAULT_CLOCK_ISO = "2026-08-10T00:00:00Z"
DEFAULT_TICKET_DATE = "2026-08-05"
