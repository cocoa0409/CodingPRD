"""Domain thresholds — numeric and temporal constants from the PRD.

Sources: PRD sections 2.4 (logical clock default), 2.5 (retention), 2.7
(exposure scoring), 2.8 (deadlines/windows/buffers), 2.9 (severity matrix and
restitution), 3.8 (statistics hierarchy).
"""

# PRD 2.4: server startup logical clock.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# PRD 2.5 / 2.8: retention sweep boundary.
RETENTION_YEARS = 7

# PRD 2.7: exposure scoring constants.
CATEGORY_BASE = {
    "SEXUAL_ASSAULT": 40,
    "DATING_VIOLENCE": 35,
    "DOMESTIC_VIOLENCE": 35,
    "STALKING": 30,
    "SEXUAL_HARASSMENT": 25,
    "OTHER_SEX_BASED": 15,
    "NON_TITLE_IX_MISCONDUCT": 0,
}
PRIOR_FINDING_POINTS = 15
NCD_VIOLATION_POINTS = 10
ACTIVE_DIRECTIVE_POINTS = 10
INTERIM_SUSPENSION_THRESHOLD = 70
ROLLING_WINDOW_DAYS = 365

# PRD 3.8: statistics hierarchy priority (higher wins the single bucket).
STAT_HIERARCHY_PRIORITY = {
    "SEXUAL_ASSAULT": 7,
    "DATING_VIOLENCE": 6,
    "DOMESTIC_VIOLENCE": 5,
    "STALKING": 4,
    "SEXUAL_HARASSMENT": 3,
    "OTHER_SEX_BASED": 2,
    "NON_TITLE_IX_MISCONDUCT": 1,
}

# PRD 2.8: procedural windows.
REVIEW_WINDOW_DAYS = 10
APPEAL_WINDOW_DAYS = 5
LEAD_DAYS = {"INTERVIEW": 5, "HEARING": 10}
HEARING_BUFFER_MINUTES = 60
SECONDS_PER_DAY = 86400

# PRD 2.9: severity scoring constants.
SEVERITY_PRIOR_POINTS = 15
SEVERITY_AGGRAVATING_POINTS = 10
SEVERITY_MITIGATING_POINTS = 5
SEVERITY_NCD_POINTS = 10
TIER_BANDS = {
    "TIER_1": (0, 24),
    "TIER_2": (25, 49),
    "TIER_3": (50, 74),
    "TIER_4": (75, None),
}
RESTITUTION_CAP_CENTS = {
    "TIER_1": 0,
    "TIER_2": 0,
    "TIER_3": 50000,
    "TIER_4": 250000,
}
RESTITUTION_POINT_UNIT_CENTS = 100

# Common scheduling instants used across workflows (logical-clock domain).
HEARING_SLOT_ISO = "2026-09-01T10:00:00Z"
HEARING_SLOT_LATER_ISO = "2026-09-20T10:00:00Z"
