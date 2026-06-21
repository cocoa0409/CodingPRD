"""Domain thresholds — numeric constants from PRD calculations (PRD §3.5–§3.7)."""

# PRD §3.5: NEONATE override for potassium → PANIC at or above 6.50 or at or below 2.50.
NEONATE_K_PANIC_HIGH: float = 6.50
NEONATE_K_PANIC_LOW: float = 2.50

# PRD §3.5: NEONATE override for glucose → PANIC at or below 40.00 mg/dL.
NEONATE_GLUCOSE_PANIC_LOW: float = 40.00

# PRD §3.7: ack_deadline_at = sent_at + 30 minutes (PHONE) / 60 minutes (SMS).
PHONE_ACK_DEADLINE_MINUTES: int = 30
SMS_ACK_DEADLINE_MINUTES: int = 60

# PRD §3.3: Phlebotomist collection rate limit — five-minute spacing window.
COLLECTOR_BUSY_WINDOW_MINUTES: int = 5

# PRD §3.4: Default qc_buffer_minutes when not supplied.
DEFAULT_QC_BUFFER_MINUTES: int = 5
QC_BUFFER_MIN: int = 0
QC_BUFFER_MAX: int = 60

# PRD §2.4: numeric_value precision — two decimal places.
NUMERIC_VALUE_DECIMAL_PLACES: int = 2

# PRD §2.3: pagination defaults.
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
