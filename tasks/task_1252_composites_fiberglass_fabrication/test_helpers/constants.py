"""Domain thresholds — numeric constants stated in the PRD."""

THRESHOLDS = {
    # PRD §3.4: pot-life temperature derate parameters.
    "REFERENCE_TEMP_C": 20,
    "HALVING_STEP_C": 10,
    "MIN_POT_LIFE_MINUTES": 5,
    # PRD §3.4: styrene emission constants.
    "STYRENE_CONTENT_POLYESTER": 0.35,
    "STYRENE_CONTENT_VINYL_ESTER": 0.40,
    "STYRENE_CONTENT_EPOXY": 0.0,
    "EMISSION_FACTOR": 0.10,
    # PRD §3.5: cure deviation score constants.
    "TEMP_SLACK_C": 10,
    "TEMP_AUTOREJECT_OVER_C": 8,
    "SOAK_WEIGHT": 1.5,
    "TEMP_WEIGHT": 2.0,
    "RAMP_SLACK": 0.5,
    "PASS_MAX_SCORE": 5.0,
    # PRD §3.6: weight acceptance and inspection disposition.
    "PROTOTYPE_TOLERANCE_PCT": 0.08,
    "PASS_MAX_VOID_PCT": 2.0,
    "REPAIR_MAX_VOID_PCT": 4.0,
    "REPAIR_MAX_DELAM_CM2": 25.0,
    # PRD §3.3: prototype lot-size cap.
    "PROTOTYPE_MAX_QUANTITY": 5,
}

TEST_DEFAULTS = {
    # Standard PN-100 rev A definition: (200 + 300) g/m2 * 2.0 m2 / 0.5.
    "TARGET_PART_WEIGHT_G": 2000.0,
    "DEFAULT_TOLERANCE_PCT": 0.05,
    "DEFAULT_MAX_REPAIR_ATTEMPTS": 2,
    "DEFAULT_WARNING_THRESHOLD_PCT": 0.85,
    "DEFAULT_PERMIT_QUOTA_KG": 50.0,
    # Styrene posted by one 250 g POLYESTER session:
    # round(250 * 0.35 * 0.10 / 1000, 4) == 0.0088 kg (round-half-up).
    "SESSION_STYRENE_250G_POLYESTER_KG": 0.0088,
    # Logical-clock startup default (PRD §2.5).
    "CLOCK_DEFAULT_ISO": "2026-05-01T00:00:00Z",
    "T0": "2026-06-01T10:00:00Z",
}
