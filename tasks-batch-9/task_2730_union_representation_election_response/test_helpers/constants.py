"""Numeric thresholds, calendars and defaults stated by the PRD."""

# Thresholds and bands used by the PRD's calculations.
THRESHOLDS = {
    "RISK_ESCALATION_THRESHOLD": 70,
    "RISK_PROHIBITED_THRESHOLD": 90,
    "SHOWING_OF_INTEREST_THRESHOLD_PCT": 30.00,
    "TRADITIONAL_SHARED_BAND": 65,
    "TRADITIONAL_CONTESTED_BAND": 45,
    "OVERWHELMING_SHARED_BAND": 80,
    "OVERWHELMING_CONTESTED_BAND": 60,
    "ACCRETION_SHARED_BAND": 60,
    "ACCRETION_CONTESTED_BAND": 40,
    "TRAINING_PASS_SCORE": 80,
    "MAX_REVISION_ROUNDS": 3,
    "MAX_LIST_RESUBMISSIONS": 2,
    "MAX_BALLOT_REOPENS": 2,
    "MAX_OBSERVERS_PER_PARTY": 3,
    "VOTER_LIST_BUSINESS_DAYS": 2,
    "OBJECTION_WINDOW_BUSINESS_DAYS": 7,
    "CERTIFICATION_YEAR_DAYS": 365,
    "ELECTION_BAR_DAYS": 365,
    "PEERLESS_PLYWOOD_HOURS": 24,
    "POLL_SESSION_TEARDOWN_MINUTES": 30,
    "PRESENTER_TRAVEL_BUFFER_MINUTES": 60,
    "CURE_HOURS_MINOR_DEFECT": 48,
    "CURE_HOURS_MATERIAL_DEFECT": 24,
}

# The three module codes a training attempt must contain to certify a supervisor.
REQUIRED_TRAINING_MODULES = ["TIPS_BOUNDARIES", "PROHIBITED_CONDUCT", "SOLICITATION_RULES"]

# Business-day calendar: Monday-Friday minus this fixed holiday set.
HOLIDAY_CALENDAR = ["2026-09-07", "2026-11-26", "2026-11-27", "2026-12-25"]

# The logical clock reads exactly this instant before any clock call.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Risk-score base rate per channel.
CHANNEL_BASE_RISK = {
    "EMAIL": 5,
    "LETTER": 5,
    "DIGITAL_POST": 10,
    "SMALL_GROUP_MEETING": 20,
    "CAPTIVE_AUDIENCE_MEETING": 30,
}

# Community-of-interest weights under the TRADITIONAL standard.
TRADITIONAL_WEIGHTS = {
    "supervision_overlap": 0.325,
    "skills_overlap": 0.225,
    "functional_integration": 0.175,
    "interchange_rate": 0.125,
    "work_conditions_overlap": 0.100,
    "wage_proximity": 0.050,
}

# Convenient defaults for building test data.
TEST_DEFAULTS = {
    "CLOCK": "2026-08-03T09:00:00Z",
    "FILED_DATE": "2026-08-03",
    "PAYROLL_PERIOD_END": "2026-08-14",
    "UNION_NAME": "United Plant Workers Local 812",
    "UNIT_DESCRIPTION": "All full-time and regular part-time production and maintenance employees at Plant 1",
    "ELECTION_DATE": "2026-09-01",
    "POLLS_OPEN_AT": "2026-09-01T08:00:00Z",
    "POLLS_CLOSE_AT": "2026-09-01T16:00:00Z",
}
