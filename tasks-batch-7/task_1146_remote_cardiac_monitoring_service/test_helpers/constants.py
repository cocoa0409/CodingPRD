"""Domain thresholds and fee constants from the PRD (§2.5, §3.4, §3.5, §3.7, §3.8)."""

# Logical clock startup default (PRD §2.5).
CLOCK_START = "2026-05-01T00:00:00Z"

# Billing fee schedule in integer cents per 30 days, per monitor type (PRD §3.8).
TC_FEE_CENTS = {"HOLTER": 18075, "EVENT": 54915, "IMPLANTABLE": 90000}
PC_FEE_CENTS = {"HOLTER": 2425, "EVENT": 5205, "IMPLANTABLE": 12000}
BILLING_WINDOW_DAYS = 30
MIN_BILLABLE_DAYS = 10

# Activation baseline signal gate (PRD §3.3): >= 40 succeeds, < 40 fails.
BASELINE_SIGNAL_MIN = 40

# Transmission signal quality gate (PRD §3.4): >= 30 PROCESSED, < 30 FAILED.
SIGNAL_QUALITY_PROCESSED_MIN = 30

# Transmission gap detection threshold in hours (PRD §3.4).
GAP_HOURS = 48

# Notification SLA base minutes per severity (PRD §3.5).
SLA_MINUTES = {"CRITICAL": 15, "URGENT": 60, "ROUTINE": 1440}
BUSINESS_HOURS_START = "08:00"
BUSINESS_HOURS_END = "20:00"

# Fatigue thresholds on the load ratio (PRD §3.5).
FATIGUE_AT_RISK_THRESHOLD = 0.60
FATIGUE_FATIGUED_THRESHOLD = 0.80

# FINAL report turnaround SLA in hours (PRD §3.7).
FINAL_REPORT_SLA_HOURS = 72

# Device refurbishment buffer in hours (PRD §3.2, §3.9).
REFURBISHMENT_BUFFER_HOURS = 48

# Return shipment timing (PRD §3.9).
RETURN_DUE_DAYS = 10
RETURN_LOST_DAYS_AFTER_DUE = 20

# Strike mapping (PRD §3.6).
STRIKES_WATCH_MAX = 2
STRIKES_SUSPEND_MIN = 3

TEST_DEFAULTS = {
    "PRESCRIBED_DAYS": 30,
    "MONITOR_TYPE": "EVENT",
    "BASELINE_SIGNAL_QUALITY": 90,
    "SHIFT_CAPACITY": 5,
    "EDUCATION_METHOD": "VIDEO",
}
