"""Domain thresholds — numeric constants from the PRD billing rules."""

# Contamination fee constants (PRD §3.9 — The contamination fee).
CONTAMINATION = {
    "TIRES_FLAT_CENTS": 7500,
    "APPLIANCES_FLAT_CENTS": 12000,
    "HAZMAT_FLAT_CENTS": 50000,
    "HAZMAT_SURCHARGE_CENTS_PER_LB": 15,
}

# Pagination (PRD §2.3).
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# Reusable container-type pricing profiles used across fixtures
# (literals pinned to match the design-index conventions).
YD30 = {
    "size_code": "YD30",
    "base_rate_cents": 50000,
    "included_days": 7,
    "overage_day_cents": 1500,
    "included_tonnage_lbs": 4000,
    "overage_rate_cents_per_lb": 9,
}
YD20 = {
    "size_code": "YD20",
    "base_rate_cents": 40000,
    "included_days": 7,
    "overage_day_cents": 1200,
    "included_tonnage_lbs": 3000,
    "overage_rate_cents_per_lb": 8,
}
YD10 = {
    "size_code": "YD10",
    "base_rate_cents": 30000,
    "included_days": 7,
    "overage_day_cents": 1000,
    "included_tonnage_lbs": 2000,
    "overage_rate_cents_per_lb": 7,
}
YD40 = {
    "size_code": "YD40",
    "base_rate_cents": 60000,
    "included_days": 7,
    "overage_day_cents": 1800,
    "included_tonnage_lbs": 5000,
    "overage_rate_cents_per_lb": 10,
}
