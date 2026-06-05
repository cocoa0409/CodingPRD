"""Domain thresholds and standard test inputs from the PRD calculations (Section 3)."""

# Pinned numeric constants named by the PRD calculations.
THRESHOLDS = {
    # Meal per-diem first/last day proration factor (PRD §3.6).
    "FIRST_LAST_DAY_FACTOR": 0.75,
    # Trip out-of-policy budget multiple (PRD §3.2): budget > 2 * baseline * nights.
    "OOP_BUDGET_MULTIPLE": 2,
}

# Standard policy inputs used across most fixtures. These mirror the values the
# design indices use so the literal expected values stay consistent.
STD_POLICY = {
    "name": "Std",
    "max_economy_fare_cents": 50000,
    "business_class_min_hours": 6,
    "advance_purchase_days": 14,
    "cdw_daily_cap_cents": 3000,
    "mileage_rate_milli_cents": 67000,
    "receipt_required_threshold_cents": 7500,
}

# Standard CA per-diem rate used across most fixtures.
STD_CA_RATE = {
    "state_code": "CA",
    "lodging_cap_cents": 20000,
    "mie_cents": 8000,
}
