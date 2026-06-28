"""Domain thresholds — numeric constants drawn from the PRD's program parameters and calculations."""

# Program configuration reused across the test suite (matches the values
# the boundary and calculation tests are computed against).
PROGRAM_DEFAULTS = {
    "annual_contribution_cap_cents": 1_900_000,        # federal gift-tax exclusion, in cents
    "able_to_work_fpl_cents": 1_506_000,               # single-person FPL ceiling for ABLE-to-Work
    "ssi_suspension_threshold_cents": 10_000_000,      # $100,000 ABLE disregard ceiling for SSI
    "ssi_resource_limit_cents": 200_000,               # $2,000 SSI countable-resource limit
    "program_fee_bps": 30,                             # 0.30% annual management fee
    "nonqualified_additional_tax_pct": 0.10,           # 10% additional tax on non-qualified earnings
    "max_investment_changes_per_year": 2,
    "disability_onset_max_age": 26,
}

# The logical clock starts at this instant at server startup.
CLOCK_STARTUP_UTC = "2026-01-01T00:00:00Z"
