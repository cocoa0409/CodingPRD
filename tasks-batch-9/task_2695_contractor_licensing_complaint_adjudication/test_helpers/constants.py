"""Domain thresholds and constants stated in the PRD.

Every value here is quoted from PRD prose; nothing is invented. Where the PRD
spells a figure in words ("forty-eight months"), the integer form is used.
"""

# --- API surface -------------------------------------------------------------
API_PREFIX = "/licensing"
CLOCK_ENDPOINT = "/_clock/set_current_utc"

# The clock reads exactly this instant before any client sets it (PRD §2.4).
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# --- Pagination (PRD §2.3) ---------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_OFFSET = 0

# --- Examination currency (PRD §3.2) ----------------------------------------
EXAM_PASS_SCORE = 70
EXAM_VALIDITY_MONTHS = 48

# --- Credited experience (PRD §3.3) -----------------------------------------
EXPERIENCE_CAP_MONTHS = 96
EDU_SUBSTITUTION_SHARE = 0.50
EDU_CREDIT_MONTHS = {
    "NONE": 0,
    "APPRENTICESHIP": 12,
    "TWO_YEAR_DEGREE": 18,
    "FOUR_YEAR_DEGREE": 36,
}

# --- Application cure loop (PRD §3.3) ---------------------------------------
MAX_DEFICIENCY_ROUNDS = 3
AUTO_DENIAL_REASON = "EXCESSIVE_DEFICIENCY_ROUNDS"

# --- Licence term and designation capacity (PRD §3.3, §3.4) -----------------
LICENSE_TERM_MONTHS = 24
MAX_CONCURRENT_QUALIFICATIONS = 2
RMO_MIN_OWNERSHIP_PCT = 10

# --- Continuing education, renewal, reinstatement (PRD §3.6) ----------------
CE_HOURS_TERM_CEILING = 40
CE_SHORTFALL_FEE_CENTS_PER_HOUR = 5000
CE_SHORTFALL_GRACE_HOURS = 4
DELINQUENCY_SURCHARGE_RATE = 0.50
DELINQUENT_GRACE_DAYS = 90
FUND_ASSESSMENT_TIER_THRESHOLD_CENTS = 100000
FUND_ASSESSMENT_RATE_LOW = 0.10
FUND_ASSESSMENT_RATE_HIGH = 0.15

# --- Complaint intake and screening (PRD §3.7) ------------------------------
MIN_JURISDICTIONAL_LOSS_CENTS = 50000
STATUTE_OF_LIMITATIONS_MONTHS = 48
MEDIATION_WINDOW_DAYS = 30
MAX_MEDIATION_ROUNDS = 2

# --- Citation civil penalty (PRD §3.8) --------------------------------------
APPEAL_WINDOW_DAYS = 15
SEVERITY_BASE_CENTS = {"MINOR": 50000, "SERIOUS": 250000, "EGREGIOUS": 750000}
SUBJECT_MULTIPLIER = {"LICENSED": 1.0, "UNLICENSED": 2.0}
HAZARD_STEP = 0.25
PRIOR_STEP = 0.20
PRIOR_COUNT_CAP = 3
MITIGATION_CREDIT_RATE = 0.25
STATUTORY_MAX_PENALTY_CENTS = 1500000

# --- Sanction ladder (PRD §3.8) ---------------------------------------------
SEVERITY_POINTS = {"MINOR": 1, "SERIOUS": 3, "EGREGIOUS": 6}
PRIOR_POINTS_PER_CITATION = 2
POSTURE_POINTS = {"COMPLIANT": 0, "CONDITIONAL": 1, "NON_COMPLIANT": 2}
UNLICENSED_POINTS = 3
RECOVERY_DEBT_POINTS = 2
SANCTION_LADDER = (
    (2, "LETTER_OF_REPRIMAND"),
    (5, "PROBATION"),
    (8, "SUSPENSION_30"),
    (11, "SUSPENSION_90"),
)
SANCTION_TIER_TOP = "REVOCATION"
DISCIPLINARY_SUSPENSION_DAYS = {"SUSPENSION_30": 30, "SUSPENSION_90": 90}

# --- Recovery fund (PRD §3.9) -----------------------------------------------
JUDGMENT_RIPENING_DAYS = 90
AGGREGATE_CAP_DENIAL_REASON = "AGGREGATE_CAP_EXHAUSTED"

# --- Reference data used across the composite fixtures ----------------------
# A tier-3 electrical trade that requires mediation before enforcement.
C10 = {
    "code": "C-10",
    "name": "Electrical",
    "hazard_tier": 3,
    "min_experience_months": 48,
    "min_net_worth_cents": 250000,
    "required_bond_amount_cents": 1500000,
    "required_ce_hours": 8,
    "renewal_base_fee_cents": 45000,
    "mediation_required": True,
}

# A tier-2 HVAC trade whose complaints go straight to investigation.
C20 = {
    "code": "C-20",
    "name": "HVAC",
    "hazard_tier": 2,
    "min_experience_months": 48,
    "min_net_worth_cents": 250000,
    "required_bond_amount_cents": 1000000,
    "required_ce_hours": 8,
    "renewal_base_fee_cents": 45000,
    "mediation_required": False,
}

# A tier-3 fire-protection trade whose complaints go straight to investigation.
C30 = {
    "code": "C-30",
    "name": "Fire Protection",
    "hazard_tier": 3,
    "min_experience_months": 48,
    "min_net_worth_cents": 250000,
    "required_bond_amount_cents": 1500000,
    "required_ce_hours": 8,
    "renewal_base_fee_cents": 45000,
    "mediation_required": False,
}
