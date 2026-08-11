"""Domain thresholds and statutory schedules (PRD section 3)."""

# PRD section 3.2: statutory cure periods (days) by jurisdiction x notice type.
CURE_DAYS = {
    "CA": {"PAY_OR_QUIT": 3, "CURE_OR_QUIT": 3, "UNCONDITIONAL_QUIT": 0},
    "TX": {"PAY_OR_QUIT": 3, "CURE_OR_QUIT": 5, "UNCONDITIONAL_QUIT": 0},
    "OH": {"PAY_OR_QUIT": 5, "CURE_OR_QUIT": 7, "UNCONDITIONAL_QUIT": 0},
}

# PRD section 3.3: filing-fee base tiers (ceilings in claimed cents -> base cents).
FILING_FEE_TIERS = {
    "CA": [(250000, 24000), (1000000, 32000), (None, 43500)],
    "TX": [(200000, 18500), (800000, 26000), (None, 35000)],
    "OH": [(150000, 15000), (500000, 21000), (None, 30000)],
}
DEFENDANT_SURCHARGE_CENTS = 2500
JURY_FEE_CENTS = 15000
VARIANT_ADJ = {"STANDARD": 750, "ELECTRONIC": -1000}

# PRD section 3.6: prejudgment interest annual rate and appeal window days.
ANNUAL_RATE = {"CA": 0.10, "TX": 0.06, "OH": 0.08}
APPEAL_DAYS = {"CA": 5, "TX": 5, "OH": 10}

# PRD section 3.7: writ fee, hearing lead days, storage schedule, deputy capacity.
WRIT_FEE = {"CA": 4000, "TX": 3500, "OH": 2500}
HEARING_LEAD_DAYS = {"CA": 10, "TX": 8, "OH": 12}
STORAGE_DAILY_FEE = {"CA": 1500, "TX": 1000, "OH": 800}
STORAGE_BILLING_MODE = {
    "CA": "CALENDAR_INCLUSIVE",
    "TX": "ELAPSED_24H",
    "OH": "ELAPSED_24H",
}
STORAGE_DAYS = {"CA": 15, "TX": 14, "OH": 30}
MAX_LOCKOUTS_PER_DEPUTY_DAY = 3

# PRD section 3.9: rental-history report timeliness window (days).
REPORT_WINDOW_DAYS = 30

# Server startup logical-clock default (PRD section 2.5).
CLOCK_START = "2026-05-01T00:00:00Z"

TEST_DEFAULTS = {
    "MONTHLY_RENT_CENTS": 150000,
    "LEASE_START_DATE": "2026-01-01",
    "CLAIMED_AMOUNT_CENTS": 100000,
    "STREET_ADDRESS": "1 A St",
    "UNIT_LABEL": "A",
    "TENANT_NAME": "T A",
    "DEFENDANT_NAME": "Dee A",
    "COURTROOM": "CR-1",
    "CLERK_A": "clerk-a",
    "CLERK_B": "clerk-b",
    "PROCESS_SERVER": "ps-1",
    "DEPUTY": "dep-1",
    "MEDIATOR": "med-1",
}
