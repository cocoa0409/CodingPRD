"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # Offer lifetime stamped at dispatch: offer_expires_at = offered_at + 30 min.
    "OFFER_TIMEOUT_MINUTES": 30,
    # No-show grace measured from arrived_at.
    "NO_SHOW_WAIT_MINUTES": 15,
    # Cancellation fee tiers (whole minutes of notice).
    "FREE_CANCEL_NOTICE_MINUTES": 1440,
    "LATE_CANCEL_NOTICE_MINUTES": 240,
    "LATE_CANCEL_SHARE_BP": 5000,
    # Credit application cap: basis points of pre-credit charges.
    "MAX_CREDIT_SHARE_BP": 5000,
    # Invoice due_date = period_end + this many days.
    "NET_DAYS": 14,
    # Standing-ride occurrence generation horizon, in days from logical today.
    "GENERATION_HORIZON_DAYS": 14,
    # Buffered window half-width around a ride on a driver's schedule.
    "TRAVEL_BUFFER_MINUTES": 30,
    # Auto-suspension threshold on client no_show_count.
    "NO_SHOW_STRIKE_LIMIT": 3,
    # Default client billing-hold limit when omitted at registration.
    "DEFAULT_BILLING_HOLD_LIMIT_CENTS": 20000,
}

# The standard tariff used by most scenarios: a STANDARD-class card effective
# for all of 2026 with an 18:00 after-hours boundary and a 1.1x multiplier.
STD_CARD = {
    "service_class": "STANDARD",
    "effective_from": "2026-01-01",
    "effective_to": "2027-01-01",
    "hourly_rate_cents": 3000,
    "per_mile_cents": 150,
    "wait_per_minute_cents": 50,
    "included_wait_minutes": 10,
    "minimum_charge_cents": 2501,
    "after_hours_multiplier_bp": 11000,
    "after_hours_start_minute": 1080,
    "wav_surcharge_cents": 0,
}

# The WAV-class tariff: 3600/hr, 175/mile, 3000 minimum, 1200 flat surcharge.
WAV_CARD = {
    "service_class": "WAV",
    "effective_from": "2026-01-01",
    "effective_to": "2027-01-01",
    "hourly_rate_cents": 3600,
    "per_mile_cents": 175,
    "wait_per_minute_cents": 50,
    "included_wait_minutes": 10,
    "minimum_charge_cents": 3000,
    "after_hours_multiplier_bp": 11000,
    "after_hours_start_minute": 1080,
    "wav_surcharge_cents": 1200,
}

TEST_DEFAULTS = {
    "CLIENT": {
        "full_name": "Ada L",
        "mobility_aid": "NONE",
        "assist_level_default": "DOOR_TO_DOOR",
        "home_zone": "north",
        "address": "1 Main St",
    },
    "DRIVER": {
        "full_name": "Dan D",
        "vehicle_class": "SEDAN",
        "assist_certification": "DOOR_THROUGH_DOOR",
        "home_zone": "north",
        "max_daily_service_minutes": 480,
    },
    "DOC_VALID_FROM": "2026-01-01",
    "DOC_VALID_UNTIL": "2027-01-01",
}
