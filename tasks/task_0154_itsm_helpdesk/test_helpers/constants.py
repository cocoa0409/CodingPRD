"""Domain thresholds — numeric constants from the PRD's calculation rules.

Generic NON_EXISTENT_UUID comes from the framework. The values here are quoted
verbatim from PRD §2.8, §2.9, §3.4, §3.6, §3.7, and §3.9.
"""

# PRD §3.6: the reopen window of twenty-four hours (1440 minutes).
REOPEN_WINDOW_MINUTES = 1440

# PRD §3.4/§3.6: the reopen penalty, which is sixty minutes for each reopen.
RESOLVE_REOPEN_PENALTY_MINUTES = 60

# PRD §3.7: the CSAT eligibility window of forty-eight hours (2880 minutes).
CSAT_WINDOW_MINUTES = 2880

# PRD §3.5: CAB quorum sized to risk — one for LOW, two for MEDIUM, three for HIGH.
CAB_QUORUM_BY_RISK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}

# PRD §3.5: a single reject is enough — the veto threshold is one.
REJECT_VETO_THRESHOLD = 1

# PRD §3.9: priority weight — eight for P1, four for P2, two for P3, one for P4.
PRIORITY_WEIGHT = {"P1": 8, "P2": 4, "P3": 2, "P4": 1}

# PRD §3.9: divide by three for the per-ticket load term.
LOAD_DIVISOR = 3

# A well-formed UUID that names no resource — used for not-found probes.
MISSING_UUID = "00000000-0000-4000-8000-000000000999"

# A fixed anchor instant used by deterministic clock-driven setups.
CLOCK_ANCHOR = "2026-06-01T00:00:00Z"

# Default SLA policy shape reused across fixtures (PRD §3.1 example multipliers).
DEFAULT_MULTIPLIERS = {"P1": 0.25, "P2": 0.5, "P3": 1.0, "P4": 2.0}
DEFAULT_RESPONSE_TARGET = 60
DEFAULT_RESOLVE_TARGET = 240
DEFAULT_OLA_TARGET = 120
