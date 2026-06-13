"""Domain thresholds — numeric constants from PRD calculations."""

THRESHOLDS = {
    # Section 3.5: cumulative excursion strictly exceeding 120 minutes auto-issues a hold.
    "MAX_EXCURSION_MINUTES": 120,
    # Section 2.10: streak reaching three or more suspends the supplier.
    "SUSPEND_STREAK": 3,
    # Section 2.11: storage tolerance defaults to 2 degrees.
    "DEFAULT_STORAGE_TOLERANCE_C": 2,
}
