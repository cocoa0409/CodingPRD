"""Domain thresholds — numeric constants from the Kids Venue Booking PRD calculations."""

THRESHOLDS = {
    # PRD Section 3.12: the free-cancellation cutoff, in hours before the event.
    "FREE_CANCEL_HOURS": 72,
    # PRD Section 3.1: default deposit fraction of the quote.
    "DEFAULT_DEPOSIT_PCT": 0.25,
    # PRD Section 3.1: default venue reschedule lead time in hours.
    "DEFAULT_RESCHEDULE_LEAD_HOURS": 48,
    # PRD Section 3.1: default base event-window length in minutes.
    "DEFAULT_BASE_DURATION_MINUTES": 120,
    # PRD Section 3.1: default room turnover buffer in minutes.
    "DEFAULT_BUFFER_MINUTES": 30,
}
