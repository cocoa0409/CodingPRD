"""Business constants declared by the CMBS Special Servicing PRD.

Only values the PRD states literally are recorded here; nothing is inferred.
"""

# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# Pinned non-working days used by the business-day deadline convention.
PINNED_HOLIDAYS = ["2026-09-07", "2026-11-26", "2026-12-25"]

# --------------------------------------------------------------------------
# Trust boarding defaults
# --------------------------------------------------------------------------
DEFAULT_SPECIAL_SERVICING_FEE_ANNUAL_PCT = 0.25
DEFAULT_WORKOUT_FEE_RATE_PCT = 1.0
DEFAULT_LIQUIDATION_FEE_RATE_PCT = 1.0
DEFAULT_ADVANCE_INTEREST_RATE_PCT = 5.0
DEFAULT_FEE_BASIS_CONVENTION = "STATED_PRINCIPAL"
DEFAULT_CONSULTATION_RESPONSE_BUSINESS_DAYS = 10

# --------------------------------------------------------------------------
# Appraisal reduction
# --------------------------------------------------------------------------
APPRAISAL_CREDIT_PCT = 0.90
GROSS_APPRAISED_BASIS = "GROSS_APPRAISED_BASIS"
NET_LIQUIDATION_BASIS = "NET_LIQUIDATION_BASIS"

# --------------------------------------------------------------------------
# Controlling class control test
# --------------------------------------------------------------------------
CONTROL_TERMINATION_PCT = 0.25

# --------------------------------------------------------------------------
# Servicing standard
# --------------------------------------------------------------------------
ABSOLUTE_MARGIN_FLOOR_USD = 50000.00
RELATIVE_MARGIN_PCT = 0.005

# --------------------------------------------------------------------------
# Borrower request deposit floors
# --------------------------------------------------------------------------
DEPOSIT_FLOOR_MODIFICATION = 25000.00
DEPOSIT_FLOOR_ASSUMPTION = 15000.00
DEPOSIT_FLOOR_LEASE_APPROVAL = 5000.00
DEPOSIT_FLOORS = {
    "MODIFICATION": DEPOSIT_FLOOR_MODIFICATION,
    "ASSUMPTION": DEPOSIT_FLOOR_ASSUMPTION,
    "LEASE_APPROVAL": DEPOSIT_FLOOR_LEASE_APPROVAL,
}

# --------------------------------------------------------------------------
# Fees
# --------------------------------------------------------------------------
MONTHS_PER_YEAR = 12
MONTHLY_FEE_FLOOR_USD = 500.00
FEE_CAP_USD = 1000000.00

# --------------------------------------------------------------------------
# Advances
# --------------------------------------------------------------------------
DAY_COUNT_BASIS = 360

# --------------------------------------------------------------------------
# Cycle / counter caps
# --------------------------------------------------------------------------
INFO_REQUEST_LIMIT = 2
REVISION_LIMIT = 3
REQUIRED_TIMELY_PAYMENTS = 3

# --------------------------------------------------------------------------
# Calendar conventions
# --------------------------------------------------------------------------
APPRAISAL_DUE_DAYS = 60
ASSET_BUSINESS_PLAN_DUE_DAYS = 60
REMIC_DISPOSITION_YEARS = 3
TRANSFER_EVENT_QUALIFYING_DELINQUENCY_DAYS = 60

# --------------------------------------------------------------------------
# Money precision
# --------------------------------------------------------------------------
MONEY_DECIMALS = 2
ARA_PERCENTAGE_DECIMALS = 4
RATE_PCT_DECIMALS = 6
MONEY_TOLERANCE = 0.005
PERCENTAGE_TOLERANCE = 0.00005
RATE_TOLERANCE = 0.0000005

# --------------------------------------------------------------------------
# Pagination
# --------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
TRANSFER_EVENT_CODES = [
    "MONETARY_DEFAULT_60D",
    "IMMINENT_DEFAULT",
    "BANKRUPTCY",
    "RECEIVERSHIP",
    "MATURITY_DEFAULT",
    "OTHER_MATERIAL_DEFAULT",
]
LOAN_SERVICING_STATUSES = [
    "MASTER_SERVICING",
    "SPECIAL_SERVICING",
    "IN_WORKOUT",
    "CORRECTED",
    "REO",
    "LIQUIDATED",
    "WRITTEN_OFF",
]
LOAN_PAYMENT_STATUSES = [
    "CURRENT",
    "DELINQUENT_30",
    "DELINQUENT_60",
    "DELINQUENT_90_PLUS",
    "MATURED_UNPAID",
    "PAID_OFF",
]
REQUEST_TYPES = ["MODIFICATION", "ASSUMPTION", "LEASE_APPROVAL"]
APPRAISAL_TYPES = ["FULL_NARRATIVE", "UPDATE", "INTERNAL_VALUATION"]
ALTERNATIVE_TYPES = ["MODIFICATION", "DEED_IN_LIEU", "NOTE_SALE", "FORECLOSURE"]
ALTERNATIVE_TYPE_ORDINALS = {
    "MODIFICATION": 1,
    "DEED_IN_LIEU": 2,
    "NOTE_SALE": 3,
    "FORECLOSURE": 4,
}
NPV_BASES = ["CONTRACTUAL", "DELAY_STRESSED"]
FEE_TYPES = ["SPECIAL_SERVICING_FEE", "WORKOUT_FEE", "LIQUIDATION_FEE"]
ADVANCE_TYPES = [
    "PI_ADVANCE",
    "TAX_INSURANCE_ADVANCE",
    "PROPERTY_PROTECTION_ADVANCE",
]
REPORT_TYPES = [
    "DELINQUENT_LOAN_STATUS",
    "REO_STATUS",
    "FINAL_ASSET_DISPOSITION",
]
RECIPIENT_VALUES = [
    "TRUSTEE",
    "RATING_AGENCIES",
    "CERTIFICATE_HOLDERS",
    "CONTROLLING_CLASS_REPRESENTATIVE",
]
FEE_BASIS_CONVENTIONS = ["STATED_PRINCIPAL", "ARA_ADJUSTED"]
CONTROL_STATUSES = ["CONTROLLING", "CONSULTING_ONLY"]
RIGHTS_TYPES = ["CONSENT_RIGHT", "CONSULTATION_ONLY"]
ACQUISITION_TYPES = ["FORECLOSURE", "DEED_IN_LIEU"]
SERVICING_STANDARD_CONCLUSIONS = [
    "SERVICING_STANDARD_MET",
    "SERVICING_STANDARD_NOT_MET",
]

# --------------------------------------------------------------------------
# Common-field sets (§2.4)
# --------------------------------------------------------------------------
FULL_COMMON_FIELDS = ["id", "created_at", "updated_at", "version"]
# ServicingTransferEvent is the sole exception: it carries only id + created_at.
IMMUTABLE_COMMON_FIELDS = ["id", "created_at"]

# --------------------------------------------------------------------------
# Worked scenario values the PRD pins by example
# --------------------------------------------------------------------------
# Deficiency base 19,500,000.00 with an UPDATE appraisal at 15,000,000.
ARA_UPDATE_CREDIT = 13500000.00
ARA_UPDATE_AMOUNT = 6000000.00
ARA_UPDATE_PERCENTAGE = 30.7692
# Same deficiency base, FULL_NARRATIVE at 15,000,000 less 900,000 of expenses.
ARA_FULL_NARRATIVE_CREDIT = 12690000.00
ARA_FULL_NARRATIVE_AMOUNT = 6810000.00
ARA_FULL_NARRATIVE_PERCENTAGE = 34.9231
# One cent lower appraised value (14,999,999) on the same deficiency base.
ARA_ONE_CENT_AMOUNT = 6000000.90
ARA_ONE_CENT_CREDIT = 13499999.10

# Monthly special servicing fee at 0.25% annual on the two bases.
FEE_STATED_PRINCIPAL_BASIS = 19500000.00
FEE_STATED_PRINCIPAL_AMOUNT = 4062.50
FEE_ARA_ADJUSTED_BASIS = 13499999.10
FEE_ARA_ADJUSTED_AMOUNT = 2812.50
FEE_MONTHLY_RATE_PCT = 0.020833

# NPV worked example at 9.5%.
NPV_MOD_PERIOD_VALUES = [821917.81, 792310.42, 761653.85, 5965384.26]
NPV_MOD_PV_CONTRACTUAL = 8341266.34
NPV_MOD_NPV_CONTRACTUAL = 8221266.34
NPV_NOTE_NPV_CONTRACTUAL = 8220502.28
NPV_FORECLOSURE_NPV_CONTRACTUAL = 7523307.48
NPV_MOD_PV_DELAY_STRESSED = 7617594.82
NPV_MOD_NPV_DELAY_STRESSED = 7497594.82
NPV_NOTE_NPV_DELAY_STRESSED = 7499499.80
NPV_FORECLOSURE_NPV_DELAY_STRESSED = 6814207.74

# ARA-adjusted P&I advance obligation on a 118,000.00 monthly debt service.
PI_OBLIGATION_NO_ARA = 118000.00
PI_OBLIGATION_WITH_ARA_ONE_CENT = 81692.30
PI_OBLIGATION_WITH_ARA_ROUND = 81692.31

# Liquidation waterfall worked case: gross 7,000,000.00 / expenses 420,000.00.
WATERFALL_GROSS = 7000000.00
WATERFALL_EXPENSES = 420000.00
WATERFALL_LIQUIDATION_FEE = 70000.00
WATERFALL_AVAILABLE = 6510000.00
WATERFALL_REALIZED_LOSS = 4100416.67
WATERFALL_CONTROLLING_NOTIONAL = 3899583.33

# 30/360 advance interest at the pinned clocks.
ADVANCE_A_INTEREST_OCT = 6666.67
ADVANCE_B_INTEREST_OCT = 3750.00
ADVANCE_A_INTEREST_AUG = 5000.00
ADVANCE_B_INTEREST_AUG = 2500.00
ADVANCE_C_INTEREST_AUG = 750.00

# Consultation deadline worked example: issued 2026-09-01, 10 business days.
CONSULTATION_DEADLINE_SEP = "2026-09-16T23:59:59.999Z"

# Control test on an 8,000,000.00 controlling class.
CONTROL_THRESHOLD_SMALL_TRUST = 2000000.00
CONTROL_NOTIONAL_ONE_CENT_BELOW = 1999999.10

# REO disposition scenario: 10,000,000.00 principal, 250,000.00 accrued interest,
# two advances, an UPDATE appraisal at 8,000,000 as of 2026-06-01.
ARA_REO_DEFICIENCY_BASE = 10604583.33
ARA_REO_CREDIT = 7200000.00
ARA_REO_AMOUNT = 3404583.33
ARA_REO_PERCENTAGE = 34.0458
PI_OBLIGATION_REO = 42870.21
TRUST_NOTIONAL_AFTER_REO_ARA = 4595416.67
REO_REMIC_DEADLINE = "2029-09-01T00:00:00Z"
