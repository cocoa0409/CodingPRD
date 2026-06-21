"""Domain thresholds — numeric constants from PRD calculations (§2.8, §3.1, §3.6)."""

# Generic NON_EXISTENT_UUID comes from the framework; this is a well-formed UUID
# that resolves to no resource (used for not-found tests).
NON_EXISTENT_UUID = "00000000-0000-4000-8000-000000000000"

THRESHOLDS = {
    "DEFAULT_MIN_DAILY_MINUTES": 240,   # §3.1 minimum_daily_minutes default
    "DEFAULT_SESSION_TOTAL_DAYS": 180,  # §3.1 session_total_days default
    "DEFAULT_MEETING_MINUTES": 50,      # §3.4 section meeting_minutes default
    "DEFAULT_CAPACITY": 30,             # §3.4 section capacity default
    "WEAPON_OSS_DAY_CAP": 10,           # §3.10 WEAPON OSS statutory cap
    "MIN_PERIOD": 1,                    # §3.4 period 1..8
    "MAX_PERIOD": 8,
    "MIN_MASTERY_LEVEL": 1,             # §3.7 mastery_level in [1,4]
    "MAX_MASTERY_LEVEL": 4,
    "MIN_SEVERITY": 1,                  # §3.9 severity in [1,5]
    "MAX_SEVERITY": 5,
}

TEST_DEFAULTS = {
    "STATE_CODE": "CA",
    "SESSION_TOTAL_DAYS": 180,
    "MIN_DAILY_MINUTES": 240,
}
