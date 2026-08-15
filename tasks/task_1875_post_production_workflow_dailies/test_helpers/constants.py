"""Domain thresholds — numeric constants from PRD calculations."""

# Default logical-clock instant (PRD §2.4): before the clock has ever been set
# it reads exactly this instant.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Watermark compliance gates (PRD §3.3)
    "MIN_SCORE_STANDARD": 40,
    "MIN_SCORE_ELEVATED": 60,
    "MIN_SCORE_LOCKDOWN": 90,
    # QC escalation ladder (PRD §3.7)
    "MAX_QC_ATTEMPTS": 3,
    # Watermark score component caps (PRD §3.3)
    "FORENSIC_POINTS": 50,
    "OPACITY_CAP": 40,
    "RECIPIENT_EMAIL_POINTS": 10,
    "DIAGONAL_TILE_BONUS": 10,
    "SCORE_CAP": 100,
}

TEST_DEFAULTS = {
    "FPS": 24,
    "RESOLUTION_WIDTH": 1920,
    "RESOLUTION_HEIGHT": 1080,
    "STORAGE_QUOTA_GB": 100,
    "CAPACITY_HOURS_PER_DAY": 8,
    "DAY_RATE_CENTS": 500000,
    "BID_AMOUNT_CENTS": 1000000,
    "ETA_DAYS": 5,
    "RETENTION_YEARS": 5,
    "GIB": 1073741824,  # 1024^3 — bytes per gibibyte (PRD §2.8)
    "DEFAULT_RECIPIENT": "rcpt@x.com",
    # A generous ingest window straddling the default clock, so window
    # arithmetic is never the reason a setup step fails.
    "INGEST_WINDOW_START": "2026-07-31T00:00:00Z",
    "INGEST_WINDOW_END": "2026-08-31T23:59:59Z",
}
