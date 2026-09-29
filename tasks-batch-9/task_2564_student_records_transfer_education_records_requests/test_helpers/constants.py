"""Domain thresholds and numeric constants stated by the PRD."""

# The logical clock reads exactly this instant before any clock-setting call.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_MS = "2026-08-01T00:00:00.000Z"

THRESHOLDS = {
    # Copy-fee pricing (§3.7)
    "COPY_FEE_CENTS_PER_PAGE": 7.5,
    "COPY_SURCHARGE_RATE": 0.0825,
    "CERTIFICATION_FEE_TIER_1_FLOOR_CENTS": 2000,
    "CERTIFICATION_FEE_TIER_1_CENTS": 500,
    "CERTIFICATION_FEE_TIER_2_FLOOR_CENTS": 10000,
    "CERTIFICATION_FEE_TIER_2_CENTS": 1500,
    # Packet page count (§3.6)
    "DISCIPLINE_SUMMARY_PAGE_THRESHOLD": 500,
    "DISCIPLINE_SUMMARY_PAGES": 3,
    # Statutory response window (§3.5)
    "UNACCOMPANIED_YOUTH_DAY_CAP": 5,
    "SPED_EXTENSION_DAYS": 10,
    # Inspection window (§3.7)
    "INSPECTION_DUE_CALENDAR_DAYS": 45,
    "ROOM_BUFFER_MINUTES": 15,
    # Hearing scheduling (§3.8)
    "OFFICER_DAILY_CAP_MINUTES": 240,
    # Component page bounds (§3.3)
    "COMPONENT_MAX_PAGE_COUNT": 5000,
}

# Pagination contract (§2.3)
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# Fixed orders the PRD pins for arrays.
COMPONENT_TYPE_ORDER = ["ACADEMIC", "HEALTH", "DISCIPLINE", "SPECIAL_EDUCATION"]
DIRECTORY_CATEGORY_ORDER = [
    "NAME",
    "ADDRESS",
    "PHONE",
    "PHOTO",
    "HONORS",
    "SPORTS_PARTICIPATION",
]

# Statutory parameter sets used across the suite. Each is a complete state rule
# payload; tests override individual parameters where a rule is under test.
STATE_RULE_PRESETS = {
    "CA": {
        "state_code": "CA",
        "transfer_response_days": 10,
        "discipline_inclusion_mode": "SUSPENSIONS_AND_EXPULSIONS",
        "discipline_min_days_removed": 10,
        "include_pending_investigations": False,
        "sped_requires_consent": True,
        "amendment_hearing_days": 30,
        "destruction_min_age_years": 5,
        "directory_optout_grace_days": 14,
        "notification_wait_days": 7,
    },
    "TX": {
        "state_code": "TX",
        "transfer_response_days": 30,
        "discipline_inclusion_mode": "ALL_INCIDENTS",
        "discipline_min_days_removed": 10,
        "include_pending_investigations": True,
        "sped_requires_consent": False,
        "amendment_hearing_days": 45,
        "destruction_min_age_years": 7,
        "directory_optout_grace_days": 10,
        "notification_wait_days": 3,
    },
    "NY": {
        "state_code": "NY",
        "transfer_response_days": 20,
        "discipline_inclusion_mode": "EXPULSIONS_ONLY",
        "discipline_min_days_removed": 10,
        "include_pending_investigations": False,
        "sped_requires_consent": True,
        "amendment_hearing_days": 30,
        "destruction_min_age_years": 5,
        "directory_optout_grace_days": 14,
        "notification_wait_days": 7,
    },
}

TEST_DEFAULTS = {
    "SENDING_DISTRICT_CODE": "SEND01",
    "RECEIVING_DISTRICT_CODE": "RECV01",
    "SECOND_RECEIVING_DISTRICT_CODE": "RECV02",
    "ROOM_CODE": "ROOM-A",
    "ROOM_SEATS": 4,
    "GUARDIAN_USER_ID": "guardian-1",
    "OFFICER_ONE": "officer-1",
    "OFFICER_TWO": "officer-2",
    "CLERK_USER_ID": "clerk-1",
    "STUDENT_DOB": "2012-05-14",
    "GRADE_LEVEL": 9,
}
