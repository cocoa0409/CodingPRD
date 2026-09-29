"""Program constants and the pinned governing fee schedule payload.

Every literal here is transcribed from the PRD: the program prefix, the logical
clock's startup instant, and the full 33-field fee-schedule creation payload at
the defaults the PRD declares for the governing schedule.
"""
from typing import Any, Dict

API_PREFIX = "/false-alarm-program"

# The logical clock reads exactly this instant before the first set call.
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"

# Convention used throughout the suite: the clock is parked here for
# "present day" scenarios so that the first permit's new-installation grace
# (30 days from a 2026-08-01 issuance) has already elapsed.
CLOCK_PRESENT_UTC = "2026-09-20T00:00:00Z"

# Occurrence date used for the first chargeable incident: strictly after the
# new-installation grace through instant of 2026-08-31.
FIRST_CHARGEABLE_OCCURRED_AT = "2026-09-15T02:00:00Z"

EXEMPT_CAUSE_CODES = [
    "SEVERE_WEATHER",
    "UTILITY_POWER_FAILURE",
    "TELEPHONE_LINE_FAILURE",
    "AUTHORIZED_TEST_WITH_NOTICE",
    "CRIMINAL_OFFENSE_CONFIRMED",
    "NEW_INSTALLATION_GRACE",
]

FEE_TIERS_DEFAULT = [
    {"from_index": 1, "to_index": 2, "base_fee_cents": 0},
    {"from_index": 3, "to_index": 3, "base_fee_cents": 10000},
    {"from_index": 4, "to_index": 4, "base_fee_cents": 25000},
    {"from_index": 5, "to_index": 5, "base_fee_cents": 40000},
    {"from_index": 6, "to_index": None, "base_fee_cents": 75000},
]

OCCUPANCY_MULTIPLIERS_DEFAULT = {
    "RESIDENTIAL": 1.00,
    "COMMERCIAL": 1.50,
    "SCHOOL": 1.25,
    "FINANCIAL": 2.00,
    "GOVERNMENT": 1.00,
}

LATE_RENEWAL_TIERS_DEFAULT = [
    {"max_days_late": 15, "fee_cents": 1500},
    {"max_days_late": 30, "fee_cents": 3000},
    {"max_days_late": None, "fee_cents": 6000},
]

# The pinned governing fee schedule: every one of the 33 creation inputs at the
# value the PRD declares for it.
FEE_SCHEDULE_DEFAULTS: Dict[str, Any] = {
    "schedule_code": "FS-2507-BASE",
    "effective_from": "2026-08-01T00:00:00Z",
    "counting_window_mode": "ROLLING_365",
    "free_alarm_allowance": 2,
    "fee_tiers": FEE_TIERS_DEFAULT,
    "occupancy_multipliers": OCCUPANCY_MULTIPLIERS_DEFAULT,
    "non_ecv_surcharge_pct": 0.20,
    "unpermitted_multiplier": 2.00,
    "suspension_period_aggravation_cents": 50000,
    "per_incident_fee_cap_cents": 100000,
    "probation_threshold_count": 4,
    "suspension_threshold_count": 6,
    "appeal_filing_days": 20,
    "permit_term_days": 365,
    "renewal_grace_days": 30,
    "new_installation_grace_days": 30,
    "permit_issue_fee_cents": 5000,
    "permit_renewal_fee_cents": 3000,
    "late_renewal_tiers": LATE_RENEWAL_TIERS_DEFAULT,
    "unpermitted_operation_penalty_cents": 20000,
    "reinstatement_base_fee_cents": 60000,
    "reinstatement_escalation_pct": 0.50,
    "admin_fee_pct": 0.05,
    "admin_fee_min_cents": 500,
    "admin_fee_max_cents": 5000,
    "invoice_due_days": 30,
    "late_penalty_pct": 0.10,
    "delinquency_days": 90,
    "collections_referral_threshold_cents": 25000,
    "delinquent_balance_block_cents": 50000,
    "exempt_cause_codes": EXEMPT_CAUSE_CODES,
    "company_probation_score_threshold": 0.70,
    "company_suspension_score_threshold": 0.50,
}

# Handy derived amounts for the default schedule.
PERMIT_ISSUE_INVOICE_SUBTOTAL_CENTS = 5000
PERMIT_ISSUE_INVOICE_ADMIN_CENTS = 500          # 0.05 * 5000 = 250, clamped up to the floor
PERMIT_ISSUE_INVOICE_ASSESSED_CENTS = 5500

# Docket geometry: symmetric buffer either side of a session, both arms strict.
DOCKET_BUFFER_MINUTES = 15

# Pagination bounds.
PER_PAGE_MIN = 1
PER_PAGE_MAX = 100
PER_PAGE_DEFAULT = 10
PAGE_DEFAULT = 1
