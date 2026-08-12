"""Domain thresholds and constants named in the PRD narrative."""

#: The logical clock reads exactly this before an administrator has ever moved it.
CLOCK_DEFAULT_UTC = "2026-05-01T00:00:00Z"
CLOCK_DEFAULT_DATE = "2026-05-01"

#: The reminder ladder rungs and the overdue rung.
REMINDER_OFFSETS_DAYS = [90, 60, 30, 7]
OVERDUE_REMINDER_OFFSET_DAYS = 1
REMINDER_LADDER_SIZE = 5

#: The window inside which an obligation reads DUE_SOON.
DUE_SOON_WINDOW_DAYS = 30

#: The platform's own charge, and the volume discount that can reduce it.
SERVICE_FEE_BASE_CENTS = 4900
VOLUME_DISCOUNT_THRESHOLD_OPEN_OBLIGATIONS = 5
VOLUME_DISCOUNT_BPS = 1500
#: 4900 * 1500 / 10000 rounded half up is exactly 735, so the discounted fee is 4165.
SERVICE_FEE_DISCOUNTED_CENTS = 4165

#: The expedite service halves, by tier.
EXPEDITE_SERVICE_FEE_CENTS = {
    "NONE": 0,
    "STANDARD": 5000,
    "RUSH": 12500,
    "SAME_DAY": 30000,
}

#: The statutory resignation notice period, in calendar days.
AGENT_RESIGNATION_NOTICE_DAYS = 30

#: The refile window and the refile cap.
REFILE_WINDOW_DAYS = 15
MAX_REFILE_ATTEMPTS = 3

#: Service-of-process business-hour budgets.
SOP_ORDINARY_FORWARD_HOURS = 16
SOP_LITIGATION_FORWARD_HOURS = 4
SOP_ACK_DEADLINE_HOURS = 8
SOP_ESCALATION_STEP_HOURS = 4
SOP_MAX_ESCALATION_LEVEL = 3
SOP_DEFERRAL_BUSINESS_HOURS = 8
SOP_RISK_FLAG_THRESHOLD = 2

#: Beneficial-ownership deadline bands.
BOI_PRE_2024_DEADLINE_DATE = "2025-01-01"
BOI_2024_FORMATION_DAYS = 90
BOI_POST_2024_FORMATION_DAYS = 30
BOI_UPDATE_DAYS = 30
COMPANY_APPLICANT_CUTOVER_DATE = "2024-01-01"

#: Delinquency ranks used by every rollup.
RANK_CURRENT = 0
RANK_DUE_SOON = 1
RANK_IN_GRACE = 2
RANK_DELINQUENT = 3
RANK_ADMIN_DISSOLVED = 4

#: The four open obligation statuses.
OPEN_OBLIGATION_STATUSES = ["SCHEDULED", "DUE_SOON", "IN_GRACE", "DELINQUENT"]

#: The business day window, in UTC hours.
BUSINESS_DAY_START_HOUR_UTC = 9
BUSINESS_DAY_END_HOUR_UTC = 17
BUSINESS_HOURS_PER_DAY = 8

#: A well-formed UUID that resolves to nothing.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_UUID_ALT = "00000000-0000-4000-8000-000000000001"
UNKNOWN_UUID_THIRD = "00000000-0000-4000-8000-0000000000aa"
