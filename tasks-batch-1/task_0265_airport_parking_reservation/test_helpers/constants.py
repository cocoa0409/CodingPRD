"""Domain thresholds — numeric constants from PRD calculations and rules.

These are the named magic numbers the PRD prose states explicitly; tests reference
them rather than re-hard-coding the literals.
"""

# Overstay grace and penalty (PRD §3.6)
OVERSTAY_GRACE_MIN = 59
OVERSTAY_RATE_BPS = 15000           # 1.5x the snapshot hourly rate
OVERSTAY_FALLBACK_HOURLY_CENTS = 500  # used when snapshot hourly_cents == 0

# Prepay discount eligibility (PRD §3.4)
PREPAY_MIN_LEAD_HOURS = 24

# No-show settlement and strikes (PRD §3.7, §3.1)
NO_SHOW_RETAIN_BPS = 5000           # retain half of the prepaid quote
NO_SHOW_SUSPEND_THRESHOLD = 3       # strikes that flip the customer to SUSPENDED
NO_SHOW_GRACE_MIN = 30

# Gate timings (PRD §3.5, §3.9)
CHECKIN_EARLY_GRACE_MIN = 120
BOARDING_OPEN_LEAD_MIN = 30

# Time decomposition (PRD §3.4)
MINUTES_PER_DAY = 1440
MINUTES_PER_HOUR = 60

# Basis-points denominator (PRD §2.7)
BPS_DENOMINATOR = 10000

THRESHOLDS = {
    "OVERSTAY_GRACE_MIN": OVERSTAY_GRACE_MIN,
    "OVERSTAY_RATE_BPS": OVERSTAY_RATE_BPS,
    "OVERSTAY_FALLBACK_HOURLY_CENTS": OVERSTAY_FALLBACK_HOURLY_CENTS,
    "PREPAY_MIN_LEAD_HOURS": PREPAY_MIN_LEAD_HOURS,
    "NO_SHOW_RETAIN_BPS": NO_SHOW_RETAIN_BPS,
    "NO_SHOW_SUSPEND_THRESHOLD": NO_SHOW_SUSPEND_THRESHOLD,
    "NO_SHOW_GRACE_MIN": NO_SHOW_GRACE_MIN,
    "CHECKIN_EARLY_GRACE_MIN": CHECKIN_EARLY_GRACE_MIN,
    "BOARDING_OPEN_LEAD_MIN": BOARDING_OPEN_LEAD_MIN,
    "MINUTES_PER_DAY": MINUTES_PER_DAY,
    "MINUTES_PER_HOUR": MINUTES_PER_HOUR,
    "BPS_DENOMINATOR": BPS_DENOMINATOR,
}
