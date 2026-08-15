"""Domain thresholds and shared payload values from PRD §2 and §3."""

# ─── Calculation constants (PRD §3) ──────────────────────────────────────────
WEIGHT_ELEMENTARY = 1.00   # band weight for weighted pupils (§3.1)
WEIGHT_MIDDLE = 1.05
WEIGHT_HIGH = 1.15

RATIO_ELEMENTARY = 20      # staffing ratio pupils-per-FTE (§3.3)
RATIO_MIDDLE = 22
RATIO_HIGH = 25
SMALL_BAND_THRESHOLD = 40  # fewer than 40 pupils -> exactly 1.0 FTE (§3.3)
FTE_STEP = 0.5

AVG_SALARY = 62000         # district average salary (§3.3)
BENEFIT_LOAD = 1.34        # salary x 1.34 loads 34 percent benefits (§3.3)

FOUNDATION_PER_PUPIL = 7600      # state-aid foundation amount (§3.4)
LOCAL_CAPACITY_RATE = 0.023      # 2.3 percent of the EAV basis (§3.4)
PTELL_CPI_MAX = 0.05             # lesser of cpi_rate and 5 percent (§3.4)
OPERATING_RATE_CAP = 1.8400      # operating-rate cap (§3.4)

DEBT_LIMIT_PCT = 0.069           # 6.9 percent of eav_current (§3.6)
RETAINAGE_PCT = 0.10             # ten percent retainage on disbursement (§3.9)

NOTICE_LEAD_DAYS = 10            # hearing notice window (§3.5)
ADOPTION_DELAY_DAYS = 7          # adoption no earlier than hearing+7 (§3.5)
CERTIFICATION_LEAD_DAYS = 61     # certification <= election-61 (§3.7)
CAMPAIGN_WINDOW_DAYS = 30        # campaign restriction window (§3.7)
BALLOT_WORD_LIMIT = 200          # ballot-language word cap (§3.7)
SITE_BUFFER_DAYS = 14            # construction-window buffer (§3.6)
AUTHORIZATION_MONTHS = 36        # sale_date <= passed_at + 36 months (§3.8)

# ─── Shared fiscal-year fixture (FY2028) ─────────────────────────────────────
# PTELL cap = 9,000,000 * (1 + min(cpi, 0.05)); bond capacity = 34,500,000.
FY_A_PAYLOAD = {
    "label": "FY2028",
    "start_date": "2027-07-01",
    "end_date": "2028-06-30",
    "eav_current": 500000000,
    "eav_prior": 480000000,
    "prior_year_extension": 9000000,
    "outstanding_debt_principal": 4500000,
    "fte_ceiling": 200,
}

# Standard revenue-estimate inputs: PTELL cap 9,306,000 does not bind the
# 8,500,000 request; with three projections (1200/800/1000) total_revenue is
# 23,404,000.00 on the provisional variant.
REVENUE_ESTIMATE_DEFAULT = {
    "operating_levy_request": 8500000,
    "debt_service_levy": 1200000,
    "other_revenue": 500000,
    "cpi_rate": 0.034,
}

# ─── Calendar anchors ────────────────────────────────────────────────────────
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"   # logical-clock startup value (§2.5)
NOTICE_DATE = "2027-03-01"               # clock date when hearings are noticed
HEARING_DATE = "2027-03-20"              # notice + 19 days (satisfies the 10-day rule)
HEARING_DAY_CLOCK = "2027-03-20T09:00:00Z"
ADOPTION_DAY_CLOCK = "2027-03-27T09:00:00Z"   # hearing_held_date + 7 days
ELECTION_DATE = "2027-11-02"             # first Tuesday of November 2027
CERTIFY_SAFE_CLOCK = "2027-08-15T00:00:00Z"   # before the 2027-09-02 deadline
CANVASS_DAY_CLOCK = "2027-11-03T00:00:00Z"    # strictly after election day
SALE_DATE = "2027-12-01"
SALE_DAY_CLOCK = "2027-12-01T12:00:00Z"

MONEY_ABS_TOL = 0.005    # half a cent — money is round_half_up to 2dp (§2.7)
RATE_ABS_TOL = 0.00005   # half a ten-thousandth — rates round to 4dp (§2.7)
