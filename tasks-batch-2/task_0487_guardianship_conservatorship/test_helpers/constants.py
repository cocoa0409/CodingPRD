"""Domain thresholds — numeric constants from PRD calculations."""
from prd_bench_local_runner.testing import NON_EXISTENT_UUID  # re-exported for tests

# A syntactically-valid UUID that is never minted by the server.
MISSING_UUID = "00000000-0000-4000-8000-000000000000"

# ---- Expenditure routing threshold (PRD Section 3.6) ----
COURT_APPROVAL_THRESHOLD_CENTS = 1_000_000  # strictly-greater triggers court approval

# ---- Accounting variance tolerance (PRD Section 3.7) ----
VARIANCE_TOLERANCE_CENTS = 500  # abs variance magnitude must be at most 500 to approve

# ---- Bond sizing (PRD Section 3.3) ----
BOND_CORE_CAP_CENTS = 10_000_000  # first slice buffered 1.00x
BOND_FLOOR_CENTS = 500_000  # minimum penal sum
PLENARY_RESERVE_CENTS = 1_000_000  # added for PLENARY cases

# ---- Fiduciary fee tiered schedule (PRD Section 3.7) ----
TIER1_CAP_CENTS = 4_999_990
TIER2_CAP_CENTS = 19_999_990
TIER1_RATE = 0.05
TIER2_RATE = 0.04
TIER3_RATE = 0.03
PUBLIC_AGENCY_FEE_CAP_CENTS = 300_000  # cap for public-agency fiduciaries

# ---- Logical clock (PRD Section 2.10) ----
DEFAULT_CLOCK_ISO = "2026-01-01T00:00:00Z"

# Convenience numeric defaults used widely across fixtures.
BIG_BOND_POST_CENTS = 10_000_000  # comfortably covers the bond floor in test setups
