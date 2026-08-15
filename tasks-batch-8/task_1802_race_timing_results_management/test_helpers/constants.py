"""Domain thresholds — numeric constants stated in the PRD's prose.

Only constants a PRD reader can actually derive appear here. The PRD names
`WAVE_GAP_MINUTES` symbolically without assigning it a value, so no wave-gap
constant exists here and no test may depend on one.
"""

THRESHOLDS = {
    # PRD §3.5: "a minimum pace of two minutes per kilometer"
    "MIN_PACE_SEC_PER_KM": 120,
    # PRD §1 / §3.6: "a thirty-minute protest window" / "thirty minutes later"
    "PROTEST_WINDOW_MINUTES": 30,
    # PRD §3.6: "places 1 through 3 receive an award"
    "AWARD_DEPTH": 3,
    # PRD §3.2: five-year brackets; under-20 open bracket; 80+ masters bracket
    "BRACKET_WIDTH": 5,
    "MIN_OPEN_BRACKET_AGE": 20,
    "MASTERS_BRACKET_AGE": 80,
}

TEST_DEFAULTS = {
    # PRD §2.4: "At startup the logical clock reads exactly 2026-08-01T00:00:00Z."
    "STARTUP_CLOCK": "2026-08-01T00:00:00Z",
    "RACE_DATE": "2026-08-01T00:00:00Z",
    # Default pre-race logical time for setup traffic
    "SETUP_CLOCK": "2026-08-01T06:00:00Z",
    # Default mat deployment window on race day
    "DEPLOY_AT": "2026-08-01T05:00:00Z",
    "TEARDOWN_AT": "2026-08-01T12:00:00Z",
}
