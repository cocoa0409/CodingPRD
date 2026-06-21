"""Domain thresholds — numeric constants stated in the PRD."""

# PRD §3.2 — Filing fee constants (whole cents).
BASE_FEE_CENTS = {
    "I-130": 56_000,
    "I-485": 142_000,
    "I-765": 41_000,
    "I-131": 63_000,
}
BIOMETRICS_SURCHARGE_CENTS = 8_500
CHILD_DISCOUNT_PCT = 0.25  # I-485 under-14 discount

# PRD §3.6 — RFE deadline.
RFE_DEADLINE_DAYS = 87
MAX_RFE_ROUNDS = 2

# PRD §3.3 / §3.5 — appointment lead time.
APPT_LEAD_DAYS = 7
APPT_WINDOW_MINUTES = 60
NO_SHOW_GRACE_HOURS = 24

# PRD §3.8 — workload weights.
STATUS_WEIGHTS = {
    "FILED": 1,
    "BIOMETRICS_SCHEDULED": 2,
    "BIOMETRICS_COMPLETED": 3,
    "UNDER_REVIEW": 4,
    "RFE_PENDING": 2,
    "INTERVIEW_SCHEDULED": 5,
    "INTERVIEW_COMPLETED": 5,
}
WORKLOAD_MULTIPLIER_DAYS_PER_UNIT = 365
WORKLOAD_MULTIPLIER_CAP = 2.0

# Receipt number / alien number regex (PRD §2.6).
RECEIPT_NUMBER_PATTERN = r"^(NBC|MSC|SRC|EAC|WAC|LIN|YSC|NSC|VSC|TSC)\d{10}$"
ALIEN_NUMBER_PATTERN = r"^A\d{9}$"

# Service center prefixes (PRD §2.6).
SERVICE_CENTER_PREFIXES = ["NBC", "MSC", "SRC", "EAC", "WAC", "LIN", "YSC", "NSC", "VSC", "TSC"]

# Pagination defaults (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
