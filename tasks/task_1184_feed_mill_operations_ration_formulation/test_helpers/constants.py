"""Domain thresholds and reference values stated in the PRD (§2.5, §3.4-§3.9)."""

# Logical clock startup default (PRD §2.5)
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"

THRESHOLDS = {
    # Optimizer clamp per candidate, percent (PRD §3.4)
    "MAX_INCLUSION_PCT": 70,
    # Per-line mix deviation gate, percent (PRD §3.6)
    "WEIGHMENT_TOLERANCE_PCT": 2.0,
    # Completion released-tonnage tolerance (PRD §3.5)
    "ORDER_QTY_TOLERANCE": 0.02,
    # Minimum flush quantity in tons (PRD §3.7)
    "MIN_FLUSH_TONS": 0.5,
    # Line cleanup buffer in minutes (PRD §3.6)
    "CLEANUP_BUFFER_MINUTES": 45,
    # Margin tiers, cents (PRD §3.5: $5,000.00 and $20,000.00)
    "MARGIN_TIER1_CAP_CENTS": 500000,
    "MARGIN_TIER2_CAP_CENTS": 2000000,
    # Medicated surcharge per ton, cents (PRD §3.5: $15.00 per ton)
    "MEDICATED_SURCHARGE_CENTS_PER_TON": 1500,
    # Delivery fee, cents (PRD §3.5: $75.00 base, $9.00 per ton)
    "DELIVERY_BASE_CENTS": 7500,
    "DELIVERY_PER_TON_CENTS": 900,
}

# Standard catalogue profiles used across scenarios.
INGREDIENT_PROFILES = {
    "CORN": {"code": "CORN", "name": "Yellow corn", "hazard_class": "STANDARD",
             "is_flush_material": False, "crude_protein_pct": 9.0,
             "crude_fiber_pct": 2.2, "metabolizable_energy_kcal_kg": 3300},
    "SBM": {"code": "SBM", "name": "Soybean meal", "hazard_class": "STANDARD",
            "is_flush_material": False, "crude_protein_pct": 44.0,
            "crude_fiber_pct": 7.0, "metabolizable_energy_kcal_kg": 2600},
    "WHEAT": {"code": "WHEAT", "name": "Wheat", "hazard_class": "STANDARD",
              "is_flush_material": False, "crude_protein_pct": 12.0,
              "crude_fiber_pct": 3.0, "metabolizable_energy_kcal_kg": 3200},
    "MED-A": {"code": "MED-A", "name": "Medicated additive base", "hazard_class": "MEDICATED",
              "is_flush_material": False, "crude_protein_pct": 30.0,
              "crude_fiber_pct": 4.0, "metabolizable_energy_kcal_kg": 2800},
    "HULLS": {"code": "HULLS", "name": "Rice hulls flush", "hazard_class": "STANDARD",
              "is_flush_material": True, "crude_protein_pct": 3.0,
              "crude_fiber_pct": 30.0, "metabolizable_energy_kcal_kg": 1000},
}

TEST_DEFAULTS = {
    "CORN_PRICE_CENTS_PER_TON": 30000,
    "SBM_PRICE_CENTS_PER_TON": 52000,
    "WHEAT_PRICE_CENTS_PER_TON": 33000,
    "MED_PRICE_CENTS_PER_TON": 10000,
    "TICK_EFFECTIVE_FROM": "2026-04-01T00:00:00Z",
    "CREDIT_LIMIT_CENTS": 1000000,
    # Reference quote for a 10t corn70/SBM30 order priced at 30000/52000
    # (subtotal 366000, margin 43920, delivery 16500).
    "GROW_10T_QUOTED_TOTAL_CENTS": 426420,
    # Default planned batch window (end strictly after start, after the default clock).
    "BATCH_WINDOW_START": "2026-05-02T10:00:00Z",
    "BATCH_WINDOW_END": "2026-05-02T11:00:00Z",
    # Default trip window.
    "TRIP_DEPARTURE": "2026-05-03T09:00:00Z",
    "TRIP_RETURN": "2026-05-03T15:00:00Z",
}
