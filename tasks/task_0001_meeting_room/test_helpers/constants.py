"""Domain thresholds from scaffold Table 3 and PRD business rules."""

# Calculation constants
MINUTES_PER_HOUR = 60

# No-show grace period in minutes
NO_SHOW_GRACE_MINUTES = 15

# Booking duration limits
MIN_BOOKING_MINUTES = 15
MAX_BOOKING_HOURS = 8
MAX_BOOKING_MINUTES = MAX_BOOKING_HOURS * MINUTES_PER_HOUR  # 480

# Check-in window: 15 minutes before start_time through end_time
CHECKIN_EARLY_MINUTES = 15

# Pagination defaults
DEFAULT_LIMIT = 20
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# Test defaults for room creation
TEST_DEFAULTS = {
    "ROOM_NAME": "Test Room",
    "CAPACITY": 10,
    "FLOOR": 1,
    "TIER_STANDARD": "STANDARD",
    "TIER_PREMIUM": "PREMIUM",
    "HOURLY_RATE_CENTS": 6000,
    "PEAK_MULTIPLIER": 1.5,
    "PEAK_HOURS_START": "09:00",
    "PEAK_HOURS_END": "17:00",
    "ATTENDEE_COUNT": 5,
    "BOOKING_TITLE": "Test Meeting",
    "DURATION_MINUTES": 60,
}
