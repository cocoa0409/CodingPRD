"""Domain thresholds — numeric constants from PRD rules."""

THRESHOLDS = {
    # PRD §2.7: posture WATCH at ceil(0.8 * capacity_kg) available mass
    "CAPACITY_WATCH_PCT": 0.8,
    # PRD §2.7: rolling complaint window in days
    "COMPLAINT_WINDOW_DAYS": 14,
    # PRD §2.8: credit time-to-live in days before ops-run expiry
    "CREDIT_TTL_DAYS": 365,
    # PRD §3.4: WATCH posture accepts drops of at most 5 kg gross
    "WATCH_MAX_DROP_KG": 5.0,
    # PRD §3.7: complaint SLA in hours
    "COMPLAINT_SLA_HOURS": 72,
    # PRD §3.7: complaint reopen lifetime limit
    "COMPLAINT_REOPEN_LIMIT": 2,
    # PRD §3.3: third suspension is permanent
    "MAX_SUSPENSIONS": 3,
}

# Server-startup logical clock default per PRD §2.4
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "FISCAL_YEAR": 2026,
    "SITE_CAPACITY_KG": 10000,
    "BUCKET_QUOTA": 5,
    "TERM_START": "2026-01-01T00:00:00Z",
    "TERM_END": "2027-01-01T00:00:00Z",
    "GRANT_EXPIRES_AT": "2027-01-01T00:00:00Z",
    # PRD §3.4: occurred_at must not be after the logical clock, which starts
    # at 2026-08-01T00:00:00Z (PRD §2.4); keep the default within the default
    # agreement term [2026-01-01, 2027-01-01).
    "DROP_OCCURRED_AT": "2026-07-01T10:00:00Z",
    "YIELD_RATIO": 0.5,
    "REJECT_THRESHOLD_PCT": 25.0,
    "INTAKE_CAPACITY_KG_PER_DAY": 10000,
    "VEHICLE_CAPACITY_KG": 5000,
    "ROUTE_START": "2026-08-02T08:00:00Z",
    "ROUTE_END": "2026-08-02T12:00:00Z",
    "REPORT_PERIOD_START": "2026-08-01T00:00:00Z",
    "REPORT_PERIOD_END": "2026-09-01T00:00:00Z",
    "MATERIAL_START_MD": "01-01",
    "MATERIAL_END_MD": "12-31",
}
