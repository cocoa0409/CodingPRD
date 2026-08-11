"""Domain thresholds — numeric constants stated in the PRD (§2.5, §3)."""

# Physical limits (PRD §2.5)
MAX_ROBOT_WEIGHT_KG = 56.7
MAX_FRAME_PERIMETER_CM = 304

# Field / schedule constants (PRD §2.5, §3.5)
FIELD_RESET_MIN_SECONDS = 300
MIN_TEAMS_FOR_MATCHES = 6
ROUNDS_PER_TEAM = 8

# Alliance selection (PRD §2.5, §3.6)
ALLIANCE_COUNT = 8
MIN_MATCHES_FOR_SEEDING = 1

# Scoring penalties (PRD §3.5)
TECH_FOUL_PENALTY_PER = 5
YELLOW_CARD_PENALTY = 10
RED_CARD_PENALTY = 30

# Ranking points (PRD §3.5)
WIN_RP = 2
TIE_RP = 1
LOSS_RP = 0
AUTO_BONUS_THRESHOLD = 25
ENDGAME_BONUS_THRESHOLD = 20
AUTO_BONUS_RP = 1
ENDGAME_BONUS_RP = 1

# Posture (PRD §2.6)
CRITICAL_FREEZE_THRESHOLD = 3

# Travel reimbursement (PRD §3.8)
TRAVEL_CAPS_CENTS = {
    "AIR": 1_500_000,
    "RAIL": 800_000,
    "BUS": 400_000,
    "SELF_DRIVE": 300_000,
}
TIER1_LIMIT_CENTS = 200_000
TIER1_RATE = 0.80
TIER2_RATE = 0.50

# Screening validity windows, in days (PRD §2.5)
SCREENING_VALIDITY_DAYS = {"MENTOR": 180, "JUDGE": 180, "VOLUNTEER": 90}

# Logical clock default (PRD §2.9)
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"
