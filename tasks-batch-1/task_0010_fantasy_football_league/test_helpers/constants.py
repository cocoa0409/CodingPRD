"""Domain thresholds — numeric constants from PRD calculations.

PRD §3.6 pins the injury penalty (4.0 points) as a fixed system constant.
PRD §3.9 pins the keeper-floor round (1) as a fixed system constant.
"""

# Per PRD §3.6 ("an injury penalty of 4.0 points").
INJURY_PENALTY = 4.0

# Per PRD §3.9 ("Every cost is floored at 1, so a player whose prior round
# was 3 and who is the team's fifth keeper still costs round 1, not round -2.
# The floor constant is the keeper-floor round, value 1").
KEEPER_FLOOR_ROUND = 1


# Convenient defaults used by fixtures when the test does not care about
# the specific value. Tests that ARE sensitive to these numbers should pass
# explicit overrides into the relevant factory or fixture.
TEST_DEFAULTS = {
    "FAAB_BUDGET_CENTS": 5000,
    "ROSTER_SIZE": 2,
    "STARTER_SLOT_COUNT": 1,
    "IR_SLOT_COUNT": 0,
    "VETO_THRESHOLD": 1,
    "KEEPER_LIMIT": 0,
    "PLAYOFF_TEAM_COUNT": 2,
    "TIEBREAK_RULE": "STANDARD",
}
