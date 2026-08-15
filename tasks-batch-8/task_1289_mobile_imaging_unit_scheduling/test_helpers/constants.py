"""Domain thresholds and shared constants from the PRD (§2.4, §3.2, §3.3, §3.7, §3.8, §3.9)."""

# Logical clock startup default (PRD §2.4): the server never reads the wall clock.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Default planning geometry: week of Monday 2026-08-03, service day 2026-08-04.
DEFAULT_WEEK_START = "2026-08-03"
DEFAULT_SERVICE_DATE = "2026-08-04"
DEFAULT_ARRIVAL = "07:00"
DEFAULT_FIRST_PATIENT = "08:30"
DEFAULT_LAST_PATIENT = "16:00"
DEFAULT_DEPARTURE = "17:00"

THRESHOLDS = {
    # PRD §3.3: hard daily dose ceiling for a technologist.
    "TECH_DAILY_DOSE_LIMIT_MSV": 5.0,
    # PRD §3.5: trailing turnover buffer and sedation buffer (minutes).
    "TURNOVER_MINUTES": 10,
    "SEDATION_BUFFER_MINUTES": 15,
    # PRD §3.7: accreditation expiry warning window (days).
    "EXPIRING_WINDOW_DAYS": 30,
    # PRD §3.8: reading-turnaround SLA (minutes).
    "TRANSFER_SLA_MINUTES": 120,
    # PRD §3.2: mileage stipend rate and overnight per diem (cents).
    "MILEAGE_RATE_CENTS": 67,
    "PER_DIEM_CENTS": 15000,
    # PRD §3.9: monthly volume-discount tiers (cents / percent).
    "TIER1_MIN_CENTS": 500000,
    "TIER2_MIN_CENTS": 1000000,
    "TIER1_PCT": 5,
    "TIER2_PCT": 8,
}

# PRD §3.7: diagnostic reference levels per exam type (mSv).
DRL_MSV = {"CT_HEAD": 2.0, "CT_CHEST": 7.0, "PET_ONCO": 10.0}

# PRD §3.8: image transfer budget = floor(measured_uplink_mbps * 7.5) MB.
UPLINK_MB_PER_MBPS = 7.5
