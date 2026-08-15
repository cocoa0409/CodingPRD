"""Domain thresholds and defaults from the PRD.

The logical clock boots at a fixed default instant (PRD section "The Logical
Clock and Time-Driven Rules"); every policy default below is stated in PRD
section "Setting Up a Property and Its Policies".
"""

# Fixed logical-clock boot value.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Property policy defaults (PRD section 3.1).
PROPERTY_DEFAULTS = {
    "emergency_response_hours": 4,
    "emergency_completion_hours": 24,
    "urgent_response_hours": 24,
    "urgent_completion_hours": 72,
    "routine_response_hours": 72,
    "routine_completion_hours": 168,
    "purchase_auto_approve_threshold_cents": 50000,
    "recall_window_days": 30,
    "vendor_travel_buffer_minutes": 60,
    "entry_notice_min_hours": 24,
}

# Purchase-request pricing constants (PRD section 3.7): handling fee is zero
# when quantity is at least 10, otherwise 8% of the items subtotal rounded
# half-up to the nearest cent.
BULK_HANDLING_FREE_QTY = 10
HANDLING_PCT = 0.08

# Common schedule window used by fixtures (default-clock day).
DEFAULT_WINDOW_START = "2026-08-01T10:00:00Z"
DEFAULT_WINDOW_END = "2026-08-01T12:00:00Z"

# Vendor insurance validity used by fixtures (far future relative to tests).
DEFAULT_INSURANCE_VALID_UNTIL = "2027-01-01T00:00:00Z"
