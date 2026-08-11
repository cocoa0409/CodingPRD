"""Domain thresholds and shared fixtures — numeric constants from PRD §2/§3 prose."""

# --- Administrative fee tiers (PRD §3.3) ---
TIER1_CAP_CENTS = 10_000_000        # first $100,000 of cumulative receipts at 8%
TIER2_CAP_CENTS = 50_000_000        # next $400,000 at 6%
MIN_FEE_CENTS = 50                  # per-donation minimum under COMPREHENSIVE
GRANT_FLAT_PERCENT = 3              # flat 3% under PRE_APPROVED_GRANT, no minimum

# --- Mission alignment scorecard (PRD §3.1) ---
MISSION_SCORE_THRESHOLD = 70.00     # ADVANCE requires score >= 70.00, inclusive
# Scorecard yielding exactly 70.00: 16.75 + 13.25 + 21.50 + 18.50
PASSING_SCORECARD = {"purpose_pts": 50, "benefit_pts": 50, "capacity_pts": 100, "risk_pts": 0}

# --- Spendable balance (PRD §2.6) ---
PLEDGE_CREDIT_PERCENT = 80          # forward basis adds 80% of PLEDGED gifts, rounded half up

# --- Disbursement routing (PRD §3.4) ---
HIGH_VALUE_THRESHOLD_CENTS = 1_000_000  # high_value when amount reaches 1,000,000 (inclusive)

# --- Contractor reporting (PRD §3.5) ---
CONTRACTOR_REPORT_THRESHOLD_CENTS = 60_000  # requires_1099 at >= 60,000, inclusive

# --- Risk scoring (PRD §2.8) ---
SEVERITY_WEIGHTS = {"CRITICAL": 40, "HIGH": 20, "MEDIUM": 8, "LOW": 3}
FINDING_WEIGHT = 5
RESTRICTED_BAND = 25                # score >= 25 -> RESTRICTED (inclusive)
SEVERE_BAND = 50                    # score >= 50 -> SEVERE (inclusive)

# --- Exit waterfall (PRD §3.8) ---
RESERVE_PER_OPEN_FINDING_CENTS = 250_000
EXIT_FEE_PERCENT = 2
MIN_EXIT_FEE_CENTS = 50_000

# --- Period close (PRD §3.7) ---
ANNUAL_PLATFORM_FEE_CENTS = 25_000  # grant model, first FINAL close of a receipt-bearing year

# --- Minimum amounts (PRD §3.3 / §3.4) ---
MIN_DONATION_CENTS = 100
MIN_DISBURSEMENT_CENTS = 1

# --- Logical clock (PRD §2.4) ---
DEFAULT_CLOCK_START = "2026-05-01T00:00:00Z"

# --- Well-formed but unknown UUID for 404 probes (PRD §2.11 gate six) ---
UNKNOWN_UUID = "11111111-1111-4111-8111-111111111111"

# --- Canonical operator identities used across setup chains ---
PO_USER = "user_po_1"          # ProgramOfficer
CO_USER = "user_co_1"          # ComplianceOfficer
FO_USER = "user_fo_1"          # FinanceOfficer
SA_USER = "user_sa_1"          # SponsorAdmin
SA_USER_2 = "user_sa_2"        # second SponsorAdmin (distinct signers / SoD)
DONOR_USER = "user_donor_1"    # Donor
