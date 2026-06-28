"""Domain thresholds — numeric constants drawn from the PRD calculations (§3).

Generic NON_EXISTENT_UUID comes from the framework.
"""

# A non-existent UUID literal used by several design instances for FK/path
# not-found checks.
NONEXISTENT_UUID = "00000000-0000-0000-0000-000000000000"

THRESHOLDS = {
    "DEFAULT_CLOCK_HOURS_PER_CREDIT": 37.5,   # PRD §3.1 default divisor
    "SAP_PACE_THRESHOLD_PCT": 67.00,          # PRD §3.2 pace passing bar (inclusive)
    "READY_THRESHOLD": 80,                     # PRD §3.7 exam readiness bar
    "R2T4_EARNED_CEILING_PCT": 60.00,         # PRD §3.6 R2T4 100%-earned ceiling (strict >)
    "DEFAULT_ADMIN_FEE_CAP_CENTS": 15000,     # PRD §3.1 default admin fee cap
    "DEFAULT_CLINIC_DISCOUNT_PCT": 0.50,      # PRD §3.3 default clinic discount
    "CLINIC_TURNOVER_BUFFER_MINUTES": 15,     # PRD §3.3 turnover buffer
    "EXAM_HOURS_GATE_FRACTION": 0.90,         # PRD §3.7 90%-of-total-hours gate
}

# Common payload values reused across fixtures / tests.
TEST_DEFAULTS = {
    "PROGRAM_TOTAL_CLOCK_HOURS": 1500,
    "PROGRAM_TUITION_CENTS": 1200000,
    "PROGRAM_KIT_FEE_CENTS": 150000,
    "PROGRAM_LAB_FEE_CENTS": 50000,
    "PROGRAM_CLINIC_PHASE_START_HOUR": 300,
    "ENROLLED_ON_ISO": "2026-04-01T00:00:00Z",
}
