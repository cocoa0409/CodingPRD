"""Every declared constant of the scaffold / PRD.  No value here is invented."""

CLOCK_DEFAULT_UTC = "2026-05-01T00:00:00Z"

# --- calendar ---------------------------------------------------------------
OBSERVED_HOLIDAYS = frozenset(
    [
        "2026-01-01",
        "2026-05-25",
        "2026-07-03",
        "2026-09-07",
        "2026-11-26",
        "2026-12-25",
        "2027-01-01",
        "2027-05-31",
        "2027-07-05",
        "2027-09-06",
        "2027-11-25",
        "2027-12-24",
        "2028-01-03",
        "2028-05-29",
        "2028-07-04",
        "2028-09-04",
        "2028-11-23",
        "2028-12-25",
        "2029-01-01",
        "2029-05-28",
        "2029-07-04",
        "2029-09-03",
        "2029-11-22",
        "2029-12-25",
    ]
)
BUSINESS_DAY_START_HOUR_UTC = 9
BUSINESS_DAY_END_HOUR_UTC = 17
BUSINESS_HOURS_PER_DAY = 8

# --- calendar windows -------------------------------------------------------
DUE_SOON_WINDOW_DAYS = 30
LATE_FEE_MONTH_BLOCK_DAYS = 30
REMINDER_OFFSETS_DAYS = [90, 60, 30, 7]
OVERDUE_REMINDER_OFFSET_DAYS = 1

# --- service pricing --------------------------------------------------------
SERVICE_FEE_BASE_CENTS = 4900
EXPEDITE_SERVICE_FEE_CENTS = {
    "NONE": 0,
    "STANDARD": 5000,
    "RUSH": 12500,
    "SAME_DAY": 30000,
}
VOLUME_DISCOUNT_THRESHOLD_OPEN_OBLIGATIONS = 5
VOLUME_DISCOUNT_BPS = 1500

# --- agent of record --------------------------------------------------------
AGENT_RESIGNATION_NOTICE_DAYS = 30

# --- filing / refile --------------------------------------------------------
REFILE_WINDOW_DAYS = 15
MAX_REFILE_ATTEMPTS = 3

# --- service of process (business hours) ------------------------------------
SOP_ORDINARY_FORWARD_HOURS = 16
SOP_LITIGATION_FORWARD_HOURS = 4
SOP_ACK_DEADLINE_HOURS = 8
SOP_ESCALATION_STEP_HOURS = 4
SOP_MAX_ESCALATION_LEVEL = 3
SOP_DEFERRAL_BUSINESS_HOURS = 8
SOP_RISK_FLAG_THRESHOLD = 2

# --- BOI --------------------------------------------------------------------
BOI_PRE_2024_DEADLINE_DATE = "2025-01-01"
BOI_2024_BAND_START_DATE = "2024-01-01"
BOI_2025_BAND_START_DATE = "2025-01-01"
BOI_2024_FORMATION_DAYS = 90
BOI_POST_2024_FORMATION_DAYS = 30
BOI_UPDATE_DAYS = 30
COMPANY_APPLICANT_CUTOVER_DATE = "2024-01-01"

# --- delinquency ranks ------------------------------------------------------
RANK_CURRENT = 0
RANK_DUE_SOON = 1
RANK_IN_GRACE = 2
RANK_DELINQUENT = 3
RANK_ADMIN_DISSOLVED = 4

RANK_TO_STATUS = {
    0: "CURRENT",
    1: "DUE_SOON",
    2: "IN_GRACE",
    3: "DELINQUENT",
    4: "ADMIN_DISSOLVED",
}

OPEN_OBLIGATION_STATUSES = ("SCHEDULED", "DUE_SOON", "IN_GRACE", "DELINQUENT")
OBLIGATION_LADDER = ["SCHEDULED", "DUE_SOON", "IN_GRACE", "DELINQUENT"]
OBLIGATION_RANK = {
    "SCHEDULED": RANK_CURRENT,
    "DUE_SOON": RANK_DUE_SOON,
    "IN_GRACE": RANK_IN_GRACE,
    "DELINQUENT": RANK_DELINQUENT,
}

# --- roles ------------------------------------------------------------------
ROLES = ("PlatformAdmin", "ComplianceOfficer", "FilingAgent", "SopHandler", "ClientContact")

# --- declared enum member sets ---------------------------------------------
ENTITY_TYPES = ("LLC", "CORP", "LP", "LLP", "NONPROFIT")
BOI_EXEMPT_CLASSES = ("NONE", "LARGE_OPERATING", "PUBLICLY_TRADED", "BANK", "TAX_EXEMPT")
OWNER_STATUSES = ("ACTIVE", "REMOVED")
ANNUAL_REPORT_BASES = ("ANNIVERSARY_MONTH_DAY", "FIXED_CALENDAR_DATE", "FISCAL_YEAR_END_OFFSET")
FRANCHISE_TAX_BASES = ("FLAT", "AUTHORIZED_SHARES_TIERS", "ASSUMED_PAR_VALUE", "GROSS_RECEIPTS_BRACKETS")
GRACE_BASES = ("CALENDAR_DAYS", "BUSINESS_DAYS")
LATE_FEE_STYLES = ("FLAT", "PER_MONTH", "PERCENT_CAPPED")
OBLIGATION_TYPES = ("ANNUAL_REPORT", "FRANCHISE_TAX", "BOI_INITIAL", "BOI_UPDATE", "FINAL_REPORT")
FILING_KINDS = (
    "ANNUAL_REPORT",
    "FRANCHISE_TAX",
    "FOREIGN_QUALIFICATION",
    "WITHDRAWAL",
    "DISSOLUTION",
    "REINSTATEMENT",
    "FINAL_REPORT",
)
EXPEDITE_TIERS = ("NONE", "STANDARD", "RUSH", "SAME_DAY")
SOP_CLASSES = ("ORDINARY", "LITIGATION")
REPORT_KINDS = ("INITIAL", "UPDATED")
NAME_CLEARANCE_RESULTS = ("PENDING", "AVAILABLE", "CONFLICT")
OUTCOMES = ("ACCEPTED", "REJECTED")
