"""Domain thresholds — numeric constants from PRD calculations (§2.6, §3.2, §3.3, §3.9)."""

THRESHOLDS = {
    "WAGE_REPLACEMENT_RATE": 0.6667,     # §3.3 weekly benefit replacement rate
    "WEEKLY_MAX_CENTS": 120000,          # §3.3 weekly benefit cap ($1,200.00)
    "FILING_DEADLINE_DAYS": 365,         # §3.2 filing window, inclusive at boundary
    "APPEAL_WINDOW_DAYS": 30,            # §3.9 appeal window, day 30 open / day 31 expired
}

# Server startup logical clock (§2.6): reads exactly this until explicitly set.
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"

# A canonical program payload used across the suite (§3.1).
STANDARD_PROGRAM = {
    "name": "VS Fund",
    "fiscal_year": 2026,
    "total_budget_cents": 10000000,
    "overall_case_cap_cents": 5000000,
    "medical_cap_cents": 3000000,
    "lost_wage_cap_cents": 2000000,
    "funeral_cap_cents": 1000000,
    "mental_health_cap_cents": 1000000,
}
