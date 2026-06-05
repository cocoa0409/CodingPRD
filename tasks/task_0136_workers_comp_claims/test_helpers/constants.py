"""Domain thresholds — numeric constants from the PRD's calculations and rules.

NON_EXISTENT_UUID comes from the framework (re-exported via the barrel).
"""

# TTD weekly rate (PRD §3.5)
TTD_RATE = 0.6667            # statutory replacement fraction
SAWW_CENTS = 120000         # state average weekly wage (cap basis)
MAX_COMP_PCT = 1.00         # maximum-compensation percentage
MIN_TTD_CENTS = 15000       # statutory minimum weekly rate (floor)

# Indemnity payment (PRD §3.6)
WAITING_DAYS = 7            # 7-day waiting period
RETRO_DAYS = 14            # 14-day retroactive threshold
TPD_RATE = 0.6667          # partial replacement fraction
PPD_WEEKS_PER_PCT = 3.0    # weeks of award per impairment percentage point

# Medical reserve tiers (PRD §3.4)
MED_TIER_MINOR_CENTS = 250000
MED_TIER_MODERATE_CENTS = 1500000
MED_TIER_SEVERE_CENTS = 7500000

# Experience mod (PRD §3.12)
PRIMARY_SPLIT_CENTS = 1700000
MOD_FLOOR = 0.75
MOD_CEILING = 2.00

# Statutory time windows (PRD §3.2, §3.11)
SOL_DAYS = 730             # statute-of-limitations filing window (two years)
REOPEN_LIMIT_DAYS = 1825   # reopening window (five years)

# Return-to-work buffer (PRD §3.10)
RTW_BUFFER_DAYS = 7

# A non-existent but well-formed UUID for not-found tests.
NON_EXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
