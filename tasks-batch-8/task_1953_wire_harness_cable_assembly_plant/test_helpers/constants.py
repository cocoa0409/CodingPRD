"""Domain thresholds — numeric constants from the PRD's calculation rules.

PRD §3.2 crimp pull-force minimum: base force by AWG tier, terminal derating,
workmanship-class multiplier, product rounded half-up to one decimal place.
PRD §3.7 hipot class voltage floors and the 0.8 scrap recovery rate.
PRD §2.5 logical clock startup default.
"""

# PRD §3.2 — base pull force by wire gauge tier (newtons).
AWG_TIER_BASE_N = {
    26: 15.0, 25: 15.0, 24: 15.0,
    23: 30.0, 22: 30.0, 21: 30.0, 20: 30.0,
    19: 50.0, 18: 50.0, 17: 50.0, 16: 50.0,
    15: 80.0, 14: 80.0, 13: 80.0, 12: 80.0,
}

# PRD §3.2 — terminal-type derating factor.
TERMINAL_DERATING = {
    "OPEN_BARREL": 1.0,
    "CLOSED_BARREL": 0.9,
}

# PRD §3.2 — workmanship-class multiplier (from the program's linked drawing).
CLASS_MULTIPLIER = {
    "IPC_CLASS_1": 1.0,
    "IPC_CLASS_2": 1.0,
    "IPC_CLASS_3": 1.1,
}

# PRD §3.7 — hipot class voltage floors (volts).
HIPOT_CLASS_MIN_VOLTAGE = {
    "IPC_CLASS_1": 500,
    "IPC_CLASS_2": 1000,
    "IPC_CLASS_3": 1500,
}

# PRD §3.7 — scrap recovery rate applied per BOM line.
RECOVERY_RATE = 0.8

# PRD §2.5 — logical clock startup default (before any set call).
CLOCK_START_DEFAULT = "2026-08-01T00:00:00Z"

# PRD §3.7 — rework completion cap.
REWORK_COUNT_CAP = 2

# Common computed pull-force minima used across tests (round half-up, 1 dp):
#   class3 / AWG22 / CLOSED_BARREL = 30.0 * 0.9 * 1.1 = 29.7
#   class2 / AWG18 / OPEN_BARREL   = 50.0 * 1.0 * 1.0 = 50.0
#   class2 / AWG20 / OPEN_BARREL   = 30.0 * 1.0 * 1.0 = 30.0
#   class3 / AWG18 / CLOSED_BARREL = 50.0 * 0.9 * 1.1 = 49.5
#   class3 / AWG20 / OPEN_BARREL   = 30.0 * 1.0 * 1.1 = 33.0
MIN_PULL_CLASS3_AWG22_CLOSED = 29.7
MIN_PULL_CLASS2_AWG18_OPEN = 50.0
MIN_PULL_CLASS2_AWG20_OPEN = 30.0
MIN_PULL_CLASS3_AWG18_CLOSED = 49.5
MIN_PULL_CLASS3_AWG20_OPEN = 33.0
