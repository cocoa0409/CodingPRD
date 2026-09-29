"""Domain thresholds and numeric constants stated by the PRD."""

# Basis-point whole (PRD §2.8)
BPS_WHOLE = 10000

# Logical clock startup value (PRD §2.4)
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"

# Pagination (PRD §2.3)
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# Escalation tiers keyed on the pre-fee subtotal (PRD §3.1)
ESCALATION_TIERS = {
    "TIER_1_MAX_CENTS": 250_000_000,
    "TIER_1_BPS": 150,
    "TIER_2_MAX_CENTS": 500_000_000,
    "TIER_2_BPS": 220,
    "TIER_3_BPS": 300,
}

# Response commitment by service tier (PRD §3.1)
SLA_MINUTES_BY_TIER = {"BASIC": 480, "PREMIUM": 240, "CRITICAL": 60}

# Simulation derates (PRD §3.3 step 2)
MERGE_DERATE_BPS_PER_EXTRA_INPUT = 400
SORTATION_DIVERT_LOSS_BPS = 300
SORTATION_DIVERT_MIN_OUTBOUND = 3

# Factory acceptance testing (PRD §3.4 / §3.5)
FAT_MARGIN_PCT = 105
FAT_MAX_DEFECTS = 2
FAT_MAX_ATTEMPTS = 3

# Commissioning ramp (PRD §3.7)
RAMP_STEP_PCTS = (50, 75, 100)
RAMP_SUSTAIN_MINUTES = {50: 30, 75: 60, 100: 120}

# Acceptance retention and dispute window (PRD §3.7 / §3.9)
RETENTION_BPS = 500
DISPUTE_WINDOW_DAYS = 30

# Liquidated damages and service-response credit (PRD §3.9)
LD_BPS_PER_SHORTFALL_PCT = 50
LD_CAP_BPS = 500
SLA_BREACH_BPS = 25

# Spares coverage factors (PRD §3.9)
COVERAGE_FACTOR_BPS = {"CRITICAL": 10000, "MAJOR": 6000, "MINOR": 0}

# Change-order negotiation bound (PRD §3.8)
CHANGE_ORDER_MAX_ROUNDS = 3

# ---------------------------------------------------------------------------
# Shared numbers of the standard test project used across the suite.
# required_throughput_cph 1250 / contract_base_cents 240000000 / PREMIUM tier:
#   escalation_fee_cents 3600000, contract_value_cents 243600000,
#   response_sla_minutes 240, retention_amount_cents 12180000,
#   fat_target_cph 1313, ramp targets 625 / 938 / 1250.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "REQUIRED_THROUGHPUT_CPH": 1250,
    "CONTRACT_BASE_CENTS": 240_000_000,
    "AUTHORIZED_CEILING_CENTS": 300_000_000,
    "SPARES_BUDGET_CENTS": 5_000_000,
    "SERVICE_TIER": "PREMIUM",
    "CONTRACT_VALUE_CENTS": 243_600_000,
    "ESCALATION_FEE_CENTS": 3_600_000,
    "RETENTION_AMOUNT_CENTS": 12_180_000,
    "RESPONSE_SLA_MINUTES": 240,
    "FAT_TARGET_CPH": 1313,
    "RAMP_TARGET_50": 625,
    "RAMP_TARGET_75": 938,
    "RAMP_TARGET_100": 1250,
    "DEGRADED_EFFECTIVE_CPH": 1330,
    "DETERMINISTIC_EFFECTIVE_CPH": 1400,
    "BOTTLENECK_SEGMENT_CODE": "TR-02",
    "BOTTLENECK_AVAILABILITY_PCT": 95,
}

# Instants used by the standard cutover chain.
TEST_INSTANTS = {
    "WINDOW_START_UTC": "2026-08-10T19:00:00Z",
    "WINDOW_END_UTC": "2026-08-10T23:00:00Z",
    "WINDOW_DUE_UTC": "2026-08-10T20:00:00Z",
    "OCCUPANCY_START_UTC": "2026-08-02T00:00:00Z",
    "OCCUPANCY_END_UTC": "2026-08-05T00:00:00Z",
}
