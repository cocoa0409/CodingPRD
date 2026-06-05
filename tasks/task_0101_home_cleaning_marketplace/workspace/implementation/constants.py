"""Domain constants drawn from scaffold §1.3 calculations."""

HOME_SIZES = ["STUDIO", "ONE_BR", "TWO_BR", "THREE_BR", "FOUR_PLUS_BR"]
ADDON_CODES = ["DEEP_CLEAN", "MOVE_OUT"]
CADENCES = ["WEEKLY", "BIWEEKLY"]
SUPPLIES = ["CUSTOMER", "CLEANER"]

# visit_window: visit duration in minutes by home_size.
VISIT_MINUTES = {
    "STUDIO": 90,
    "ONE_BR": 120,
    "TWO_BR": 150,
    "THREE_BR": 180,
    "FOUR_PLUS_BR": 240,
}
TRAVEL_BUFFER_MIN = 30
RECLEAN_WINDOW_HOURS = 72

# price_quote constants.
MOVE_OUT_MINIMUM_CENTS = 20000

# reschedule_or_cancel_fee constants.
FREE_CANCEL_HOURS = 48
LATE_CANCEL_HOURS = 12
RESCHEDULE_FEE_CENTS = 1500
LATE_CANCEL_PCT = 0.25
NOSHOW_CANCEL_PCT = 0.50

# cleaner_payout constant.
PAYOUT_PCT = 0.70

# Cadence step in days.
CADENCE_DAYS = {"WEEKLY": 7, "BIWEEKLY": 14}


def loyalty_tier_pct(count):
    """Loyalty discount rate keyed off lifetime_booking_count.

    count<5 -> 0.00; 5<=count<15 -> 0.05; 15<=count<40 -> 0.10; count>=40 -> 0.15
    """
    if count < 5:
        return 0.00
    if count < 15:
        return 0.05
    if count < 40:
        return 0.10
    return 0.15
