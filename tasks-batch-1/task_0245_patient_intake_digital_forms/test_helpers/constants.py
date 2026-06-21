"""Domain thresholds — numeric constants from PRD calculations (§3.6, §3.8)."""

# Questionnaire risk scoring (PRD §3.8)
REQUIRED_MULTIPLIER = 2
HIGH_RISK_THRESHOLD = 20

# Clinic configuration defaults (PRD §2.6, §3.1)
DEFAULT_FORM_EXPIRATION_HOURS = 72
DEFAULT_QUIET_START_MIN = 1320  # 22:00
DEFAULT_QUIET_END_MIN = 420     # 07:00
DEFAULT_MIN_GAP_MINUTES = 240   # four hours
DEFAULT_COPAY_ROUNDING = "PER_LINE_THEN_SUM"

# The deterministic clock starts at the Unix epoch (PRD §2.6)
EPOCH_UTC = "1970-01-01T00:00:00.000Z"

# A syntactically-valid UUID that does not resolve to any resource.
NON_EXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
