"""Domain thresholds — numeric constants from the PRD's calculations."""

# Standings points (PRD §3.8)
STANDINGS = {
    "WIN_POINTS": 3,
    "DRAW_POINTS": 1,
    "LOSS_POINTS": 0,
    "FORFEIT_WIN_SCORE": 3,
}

# Conduct / suspension thresholds (PRD §3.9)
SUSPENSION = {
    "WARN_THRESHOLD": 3,
    "SUSPEND_THRESHOLD": 6,
    "BAN_THRESHOLD": 12,
    "SUSPENSION_GAMES": 2,
    "BANNED_GAME_INDEX": 9999,
}

# Conduct severity base point values (PRD §3.9)
CONDUCT_BASE_POINTS = {
    "WARNING": 1,
    "YELLOW": 2,
    "RED": 4,
    "ABUSE": 8,
}

# Pagination bounds (PRD §2.3)
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# Defaults applied server-side (PRD §3.1, §3.5)
DEFAULTS = {
    "REFUND_PARTIAL_PCT": 50,
    "TURNOVER_BUFFER_MINUTES": 30,
    "STANDINGS_TIEBREAKER": "HEAD_TO_HEAD",
    "GAME_STAGE": "REGULAR",
    "ASSIGNMENT_ROLE": "HEAD",
}
