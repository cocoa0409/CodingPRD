"""Domain thresholds and rates — numeric constants stated in the PRD."""

# PRD section 2.4: logical clock startup value.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# PRD section 2.5: posture derivation risk bands (strict-below thresholds).
RISK_FREEZE_THRESHOLD = 40
RISK_RESTRICT_THRESHOLD = 70

# PRD section 2.6: risk score bounds and event deltas.
RISK_SCORE_FLOOR = 0
RISK_SCORE_CEILING = 100
RISK_INITIAL = 100
MOCKUP_FAIL_DELTA = -25
FIELD_TEST_FAIL_DELTA = -25
VERIFY_DELTAS = {
    "CRITICAL": -15,
    "HIGH": -10,
    "MEDIUM": -5,
    "LOW": -2,
}
REMEDIATION_RECOVERY = 10

# PRD section 3.2: design review fee schedule (integer cents).
REVIEW_TIER1_MAX_DRAWINGS = 5
REVIEW_TIER1_BASE_CENTS = 250000
REVIEW_TIER2_MARGINAL_CENTS = 30000
REVIEW_TIER2_MAX_DRAWINGS = 15
REVIEW_TIER3_MARGINAL_CENTS = 20000
REVIEW_EXTRA_BARRIER_CENTS = 40000
REVIEW_REVISION_SURCHARGE_PCT = 0.10

# PRD section 3.3: mock-up testing fee specimen surcharge.
SPECIMEN_SURCHARGE_PCT = 0.05

# PRD section 3.4: field test reference pressure.
REFERENCE_PRESSURE_PA = 75

# PRD section 3.5: imaging survey minimum thermal contrast.
IMAGING_MIN_DELTA_T_C = 3.0

# PRD section 3.7: remediation cost schedule (integer cents).
SEVERITY_COST_CENTS = {
    "LOW": 500000,
    "MEDIUM": 1500000,
    "HIGH": 4000000,
    "CRITICAL": 9000000,
}
CONTINGENCY_PCT = 0.20
MOBILIZATION_PER_SECTION_CENTS = 125000

# PRD section 3.8: manufacturer response window.
MANUFACTURER_RESPONSE_DAYS = 30

# PRD section 3.9: invoice volume discount tier.
VOLUME_TIER_THRESHOLD_CENTS = 2000000
VOLUME_TIER_MIN_DISCOUNT_PCT = 10
