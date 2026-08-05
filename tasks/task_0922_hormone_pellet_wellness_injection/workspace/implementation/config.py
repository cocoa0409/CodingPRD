"""Declared domain constants (PRD sections 2 and 3).

Every numeric threshold this API compares against lives here, expressed
exactly as the PRD states it.  Money is integer cents; ratios are exact
rationals so that no rounding happens before the single rounding step each
calculation pins.
"""
from fractions import Fraction

# ---------------------------------------------------------------- clock ----
CLOCK_DEFAULT_ISO = "2026-05-01T00:00:00Z"

# ------------------------------------------------------------ envelope -----
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# --------------------------------------------------------------- roles -----
ROLE_CLINIC_ADMIN = "ClinicAdmin"
ROLE_PHYSICIAN = "Physician"
ROLE_NURSE_INJECTOR = "NurseInjector"
ROLE_INVENTORY_MANAGER = "InventoryManager"
ROLE_FRONT_DESK = "FrontDesk"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_PATIENT = "Patient"

ALL_ROLES = (
    ROLE_CLINIC_ADMIN,
    ROLE_PHYSICIAN,
    ROLE_NURSE_INJECTOR,
    ROLE_INVENTORY_MANAGER,
    ROLE_FRONT_DESK,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_PATIENT,
)

# Roles whose X-User-ID names a persisted row (validation rung 8).
PROVIDER_BACKED_ROLES = (ROLE_PHYSICIAN, ROLE_NURSE_INJECTOR)

# ----------------------------------------------------------- enum sets -----
SEX_AT_BIRTH = ("MALE", "FEMALE")
PROVIDER_TYPES = ("PHYSICIAN", "NURSE_INJECTOR")
HORMONE_TYPES = ("TESTOSTERONE", "ESTRADIOL")
ANALYTES = ("TOTAL_TESTOSTERONE", "ESTRADIOL", "HEMATOCRIT")
INJECTION_TYPES = ("B12", "LIPOTROPIC", "VITAMIN_D", "GLUTATHIONE")
PROCEDURE_TYPES = ("INITIAL", "REDOSE")
MEMBERSHIP_TIERS = ("BASIC", "PLUS", "ELITE")
AE_INPUT_SEVERITIES = ("MILD", "MODERATE", "SEVERE")
AE_DISPOSITIONS = ("CLOSED", "ESCALATED")
RECALL_SEVERITY_CLASSES = ("CLASS_I", "CLASS_II")
HOLD_KINDS = ("CLINICAL", "FINANCIAL")
HOLD_ACTIONS = ("SET", "CLEAR")
RECALL_IMPACT_VARIANTS = ("PROJECTION", "ACTUAL")

# ------------------------------- Seam 1: dose -> pellet-count conversion ----
PELLET_LADDER_TESTOSTERONE_MG = (200, 100)          # [large, small]
PELLET_LADDER_ESTRADIOL_MG = (25, 10)
PELLET_LADDER = {
    "TESTOSTERONE": PELLET_LADDER_TESTOSTERONE_MG,
    "ESTRADIOL": PELLET_LADDER_ESTRADIOL_MG,
}
MAX_DOSE_PER_PROCEDURE_MG = {"TESTOSTERONE": 2000, "ESTRADIOL": 150}
ROLLING_MG_WINDOW_DAYS = 365
ROLLING_MG_CAP = {"TESTOSTERONE": 4800, "ESTRADIOL": 400}

# ------------------------------- Seam 2: two ranges on one number ----------
# (ref_low, ref_high, opt_low, opt_high, critical_high, unit)
ANALYTE_BANDS = {
    "TOTAL_TESTOSTERONE": (264, 916, 600, 900, 1500, "ng/dL"),
    "ESTRADIOL": (30, 400, 80, 200, 500, "pg/mL"),
    "HEMATOCRIT": (38.0, 50.0, 40.0, 46.0, 54.0, "percent"),
}
HEMATOCRIT_SAFETY_CEILING = 52.0
LAB_MAX_AGE_DAYS = 45

# The hormone's primary analyte, for re-dose factor five.
PRIMARY_ANALYTE = {"TESTOSTERONE": "TOTAL_TESTOSTERONE", "ESTRADIOL": "ESTRADIOL"}

# ------------------------------- Seam 3: re-dose eligibility gate ----------
MIN_REDOSE_INTERVAL_DAYS = {"TESTOSTERONE": 84, "ESTRADIOL": 70}
TROUGH_WINDOW_OPEN_DAYS = {"TESTOSTERONE": 70, "ESTRADIOL": 56}
TROUGH_WINDOW_CLOSE_DAYS = {"TESTOSTERONE": 98, "ESTRADIOL": 84}
REDOSE_MIN_SYMPTOM_SCORE = 40

# ------------------------------- Seam 10: scheduling friction --------------
PROCEDURE_DURATION_MINUTES = 45
INJECTION_DURATION_MINUTES = 15
PROVIDER_SLOT_BUFFER_MINUTES = 20
POST_INSERTION_RESTRICTION_DAYS = 14
LATE_CANCEL_TIER1_LEAD_HOURS = 48
LATE_CANCEL_TIER2_LEAD_HOURS = 24
LATE_CANCEL_TIER1_FEE_CENTS = 5000
LATE_CANCEL_TIER2_FEE_CENTS = 12500
NO_SHOW_FEE_CENTS = 20000

# ------------------------------- Pricing -----------------------------------
INSERTION_BASE_FEE_CENTS = 25000
PELLET_PRICE_CENTS_PER_MG = {
    "TESTOSTERONE": Fraction(43, 2),        # 21.5
    "ESTRADIOL": Fraction(705, 4),          # 176.25
}
FACILITY_FEE_BASE_CENTS = 7500
FACILITY_FEE_WAIVER_THRESHOLD_CENTS = 42625
INJECTION_LIST_PRICE_CENTS = {
    "B12": 3500,
    "LIPOTROPIC": 4500,
    "VITAMIN_D": 5500,
    "GLUTATHIONE": 8500,
}

# ------------------------------- Seam 7: membership + series ---------------
MEMBERSHIP_FEE_CENTS = {"BASIC": 4900, "PLUS": 9900, "ELITE": 19900}
MEMBERSHIP_DISCOUNT_PCT = {
    "BASIC": Fraction(0, 1),
    "PLUS": Fraction(1, 10),
    "ELITE": Fraction(1, 5),
}
MEMBERSHIP_DISCOUNT_PCT_OUT = {"BASIC": 0.0, "PLUS": 0.1, "ELITE": 0.2}
MEMBERSHIP_INCLUDED_VISITS = {"BASIC": 0, "PLUS": 2, "ELITE": 4}
MEMBERSHIP_PERIOD_DAYS = 30
MAX_PAUSE_DAYS_PER_YEAR = 90
SERIES_PACK_VISITS = 8
SERIES_PACK_DISCOUNT_PCT = Fraction(15, 100)
SERIES_ENROLLMENT_FEE_CENTS = 2500
SERIES_VALIDITY_DAYS = 365

# ------------------------------- Seam 8: self-pay + financing --------------
FINANCING_MIN_DOWN_PAYMENT_PCT = Fraction(1, 5)
FINANCING_MAX_INSTALLMENTS = 12
FINANCING_MIN_INSTALLMENTS = 2
FINANCING_INSTALLMENT_INTERVAL_DAYS = 30
FINANCING_GRACE_PERIOD_DAYS = 10
FINANCING_DEFAULT_MISSED_THRESHOLD = 3
FINANCING_LATE_FEE_CENTS = 2500

# ------------------------------- Seams 5 & 9: recall + adverse event -------
RECALL_NOTIFICATION_DUE_DAYS = 7
MODERATE_REVIEW_DUE_DAYS = 14
SEVERE_REVIEW_DUE_HOURS = 24
STANDING_ORDER_MAX_VALIDITY_DAYS = 365

# ------------------------------- terminal state sets (rung 11) -------------
TERMINAL_STATES = {
    "Procedure.status": ("CANCELLED", "VOIDED"),
    "PelletLot.sterility_status": ("RECALLED",),
    "StandingOrder.status": ("REVOKED",),
    "SeriesPack.status": ("EXPIRED", "REFUNDED"),
    "InjectionVisit.status": ("CANCELLED", "VOIDED"),
    "Membership.status": ("CANCELLED",),
    "FinancingPlan.status": ("DEFAULTED", "PAID_OFF", "CANCELLED"),
    "AdverseEvent.status": ("CLOSED",),
    "PatientNotification.status": ("ACKNOWLEDGED",),
}

# Allocation statuses that count toward Procedure.pellets_allocated.
ALLOCATED_STATUSES = ("RESERVED", "OPENED", "CONSUMED", "WASTED", "RECALL_FLAGGED")

# Statuses that occupy a provider / a room (rungs 27 and 28).
OCCUPYING_PROCEDURE_STATUSES = ("SCHEDULED", "CONSENTED", "SUPPLY_OPENED", "COMPLETED")
OCCUPYING_VISIT_STATUSES = ("SCHEDULED", "ADMINISTERED")
