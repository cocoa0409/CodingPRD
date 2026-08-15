"""Domain thresholds — numeric constants from the PRD (sections 3.2-3.8).

Also provides deterministic opaque operator ids used in segregation-of-duties
scenarios, and the logical-clock startup default.
"""

# PRD 2.5: logical clock startup default.
CLOCK_START_ISO = "2026-08-01T00:00:00Z"

# PRD 3.4 / 3.6 billing constants.
THRESHOLDS = {
    "RACK_FEE_CENTS": 15000,          # PRD 3.6: flat rack fee $150.00
    "FUEL_SURCHARGE_PCT": 0.04,       # PRD 3.6: 4% fuel surcharge
    "LOSS_BASE_GAL": 5.0,             # PRD 3.5: base in-transit allowance
    "LOSS_PER_MILE_GAL": 0.02,        # PRD 3.5: per-mile allowance
    "LOSS_CAP_GAL": 50.0,             # PRD 3.5: flat gallon cap
    "WEIGHT_SUM_TOLERANCE_PCT": 0.03,  # PRD 3.4: 3% sum-consistency bound
    "REFERENCE_TEMP_F": 60,           # PRD 2.6: 60 F reference temperature
    "WASH_VALIDITY_HOURS": {"FLUSH": 48, "DETERGENT_WASH": 96, "CHEMICAL_KOSHER": 168},
    "RETAIN_SAMPLE_DAYS": 90,         # PRD 3.5: retain_until = taken_at + 90 days
    "SPILL_PLAN_VALIDITY_DAYS": 365,  # PRD 3.7: expires 365 days after approval
    "MAJOR_THRESHOLD_GAL": 10,        # PRD 3.7: severity boundary
    "REPORTABLE_THRESHOLD_GAL": 100,  # PRD 3.7: severity boundary
    "REPORTABLE_DEADLINE_HOURS": 12,  # PRD 3.7: regulatory reporting deadline
    "COMMITMENT_FLOOR_PCT": 0.8,      # PRD 3.8: compliance floor fraction
    "SHORTFALL_FEE_PER_LOAD_CENTS": 25000,  # PRD 3.8: $250.00 per missing load
    "FLAG_SUSPEND_THRESHOLD": 2,      # PRD 3.5: counter at 2 suspends agreement
}

TEST_DEFAULTS = {
    "CREDIT_LIMIT_CENTS": 1_000_000_000,
    "RATE_PER_GAL_CENTS": 100,
    "ROUTE_MILES": 100,
    "ORDERED_GALLONS": 1000,
}

# Opaque operator identifiers (PRD 2.1: never compared to any entity id).
OP_METER = "op-meter"    # TerminalOperator who closes the meter
OP_SCALE = "op-scale"    # TerminalOperator who verifies weights (must differ)
OP_SCALE_2 = "op-scale-2"
SO_1 = "so-1"            # SafetyOfficer who closes incidents
SO_2 = "so-2"            # SafetyOfficer who reopens (must differ from closer)
