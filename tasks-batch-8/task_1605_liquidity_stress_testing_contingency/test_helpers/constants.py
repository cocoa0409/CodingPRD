"""Domain thresholds and logical-clock anchors.

Haircut constants come from PRD §3.3 ("zero for LEVEL_1, 1500 basis points
(fifteen percent) for LEVEL_2A, and 2500 basis points (twenty-five percent)
for LEVEL_2B"). The clock anchor comes from PRD §2.4 ("Before the clock has
ever been set, it reads exactly 2026-08-01T00:00:00Z").
"""

# Class haircuts in basis points (PRD §3.3).
HAIRCUT_BPS = {
    "LEVEL_1": 0,
    "LEVEL_2A": 1500,
    "LEVEL_2B": 2500,
}

# Posture ordinal scale (PRD §3.6): NORMAL(0) < HEIGHTENED(1) < SEVERE(2) < CRISIS(3).
POSTURE_ORDINAL = {
    "NORMAL": 0,
    "HEIGHTENED": 1,
    "SEVERE": 2,
    "CRISIS": 3,
}

# Logical clock (PRD §2.4).
CLOCK_ANCHOR_ISO = "2026-08-01T00:00:00Z"

# Shared reading timestamps used by the fixture builders.
READING_T1 = "2026-08-01T00:00:00Z"
READING_T2 = "2026-08-02T00:00:00Z"

# Standard projection as-of date (YYYY-MM-DD, PRD §3.2).
AS_OF_DATE = "2026-08-01"
