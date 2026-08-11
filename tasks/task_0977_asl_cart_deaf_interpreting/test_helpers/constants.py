"""Domain thresholds — numeric constants named in the PRD's business rules."""

THRESHOLDS = {
    # PRD §3.3: scheduled_start at least two hours in the future at submit time
    "SUBMIT_LEAD_HOURS": 2,
    # PRD §3.4: at most three offer attempts per request
    "MAX_OFFER_ATTEMPTS": 3,
    # PRD §3.4: response_deadline is the earlier of scheduled start and offer + 24h
    "OFFER_RESPONSE_HOURS": 24,
    # PRD §3.4: interpreter final quality_score must be at least 40 at dispatch
    "QUALITY_OFFER_GATE": 40,
    # PRD §3.5: check-in window opens thirty minutes before scheduled_start
    "CHECK_IN_EARLY_MINUTES": 30,
    # PRD §3.5: thirty-minute travel buffer on each side for double-booking
    "TRAVEL_BUFFER_MINUTES": 30,
    # PRD §3.5: three overlapping VRI sessions allowed; the fourth rejected
    "VRI_MAX_CONCURRENT_SESSIONS": 3,
    # PRD §3.6: mark-no-show only once fifteen minutes past scheduled_start
    "NO_SHOW_GRACE_MINUTES": 15,
    # PRD §3.6: rolling strike window of 365 days, inclusive edge
    "STRIKE_WINDOW_DAYS": 365,
    # PRD §3.6: auto-suspension when the rolling active strike count reaches three
    "STRIKE_SUSPENSION_THRESHOLD": 3,
    # PRD §3.5/§3.7: verify_deadline armed seventy-two hours after actual_end
    "VERIFY_DEADLINE_HOURS": 72,
    # PRD §3.7: travel time capped at 240 minutes
    "TRAVEL_TIME_CAP_MINUTES": 240,
    # PRD §3.7: mileage capped at 200 miles
    "MILEAGE_CAP_MILES": 200,
    # PRD §3.4: flat sixty estimated travel minutes for on-site estimates
    "ESTIMATED_TRAVEL_MINUTES_ONSITE": 60,
    # PRD §3.9: penalty points by severity
    "PENALTY_MINOR": 5,
    "PENALTY_MAJOR": 15,
    "PENALTY_CRITICAL": 30,
    # PRD §3.9: quality score floor
    "QUALITY_FLOOR": 0,
}

# Standard fixture literals shared by the test scenarios:
# clock default 2026-05-01T00:00:00Z; on-site MEDICAL/CERTIFIED card with
# hourly 9000, minimum 120, travel 3000/h, mileage 70/mi, windows 48h/24h,
# late-cancel fraction 0.5, effective 2026-01-01.
TEST_DEFAULTS = {
    "CLOCK_START": "2026-05-01T00:00:00Z",
    "ORG_CREDIT_LIMIT_CENTS": 500000,
    "HOURLY_RATE_CENTS": 9000,
    "MINIMUM_BILLABLE_MINUTES": 120,
    "TRAVEL_RATE_CENTS_PER_HOUR": 3000,
    "MILEAGE_RATE_CENTS_PER_MILE": 70,
    "VRI_PLATFORM_FEE_CENTS_PER_MIN": 0,
    "CANCEL_FULL_REFUND_NOTICE_HOURS": 48,
    "CANCEL_PARTIAL_NOTICE_HOURS": 24,
    "LATE_CANCEL_FEE_PCT": 0.5,
    "EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    # VRI card literals
    "VRI_HOURLY_RATE_CENTS": 4500,
    "VRI_MINIMUM_BILLABLE_MINUTES": 30,
    "VRI_PLATFORM_FEE_PER_MIN": 15,
    # Canonical booking: June 10 14:00-16:30 (150 scheduled minutes), 10 est. miles
    "REQUEST_START": "2026-06-10T14:00:00Z",
    "REQUEST_END": "2026-06-10T16:30:00Z",
    "ESTIMATED_MILEAGE": 10,
    "ONSITE_ADDRESS": "1 Main St",
    # Window spanning all of June
    "AVAILABILITY_START": "2026-06-01T00:00:00Z",
    "AVAILABILITY_END": "2026-07-01T00:00:00Z",
}
