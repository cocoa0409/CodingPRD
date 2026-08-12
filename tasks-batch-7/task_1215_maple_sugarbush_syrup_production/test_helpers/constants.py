"""Domain thresholds — numeric constants from the PRD (§2.5, §2.9, §3)."""

THRESHOLDS = {
    # Yield conventions (PRD §2.5)
    "RULE_86": 86,
    "RULE_88_2": 88.2,
    # Sap deterioration (PRD §3.6)
    "DETERIORATION_PER_DAY": 0.2,
    "MAX_DETERIORATION": 1.0,
    "BRIX_FLOOR": 0.5,
    # Yield variance auto-hold (PRD §3.6)
    "VARIANCE_HOLD_PCT": 15.0,
    # Grade classification (PRD §3.8)
    "FLAVOR_MIN": 70,
    "T_GOLDEN": 75.0,
    "T_AMBER": 50.0,
    "T_DARK": 25.0,
    # Vacuum leak / repair hysteresis (PRD §3.2)
    "LEAK_DROP": 2.0,
    "REPAIR_HYSTERESIS": 0.5,
    # Freeze-thaw eligibility (PRD §3.3)
    "FREEZE_F": 32.0,
    "THAW_F": 38.0,
    # Legal syrup density minimum (PRD §3.6)
    "LEGAL_BRIX_MIN": 66.0,
    # Cert-audit spacing (PRD §3.10)
    "AUDIT_SPACING_DAYS": 14,
    # Lease share cap (PRD §3.4)
    "MAX_SHARE_PCT": 50,
}

# Container capacities in gallons (PRD §2.9)
CONTAINER_GALLONS = {
    "DRUM_55": 55.0,
    "RETAIL_QUART": 0.25,
    "RETAIL_PINT": 0.125,
}

TEST_DEFAULTS = {
    "YEAR": 2027,
    "OPENS_ON": "2027-02-01",
    "CLOSES_ON": "2027-04-15",
    "PLANNED_TAPS": 10000,
    "TAP_CAPACITY": 5000,
    "VACUUM_TARGET_INHG": 25.0,
    "CLOCK_INIT": "2027-02-15T00:00:00Z",
}
