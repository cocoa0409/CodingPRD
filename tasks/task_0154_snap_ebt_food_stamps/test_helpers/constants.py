"""Domain thresholds and constant tables for SNAP/EBT (from PRD §3.2-§3.9)."""

# State codes (PRD §2.11)
VALID_STATE_CODES = ["CA", "TX", "NY", "FL", "IL", "PA", "OH", "GA", "NC", "MI"]

# Net-income calculation constants (PRD §3.2)
# Standard deduction table — cents, indexed by household_size (size 1-3 same; cap at 6)
STANDARD_DEDUCTION_TABLE = {1: 19300, 2: 19300, 3: 19300, 4: 20600, 5: 24100, 6: 27600}
DEPENDENT_CARE_CAP_CENTS = 25000
EXCESS_SHELTER_CAP_CENTS = 67200

# Monthly allotment constants (PRD §3.3)
MAX_ALLOTMENT_TABLE = {1: 29100, 2: 53500, 3: 76600, 4: 97300, 5: 115500, 6: 138600}
MINIMUM_BENEFIT_CENTS = 2300

# Gross / net income limit tables (PRD §3.3)
GROSS_INCOME_LIMIT_TABLE = {
    1: 162200, 2: 218800, 3: 275400, 4: 332000, 5: 388600, 6: 445200,
}
NET_INCOME_LIMIT_TABLE = {
    1: 124800, 2: 168300, 3: 211800, 4: 255400, 5: 298900, 6: 342400,
}

# Emergency Allotment floor (PRD §3.9)
EA_FLOOR_CENTS = 9500

# Fraud-score window (PRD §3.7)
ROLLING_WINDOW_DAYS = 30
FRAUD_SUBSTANTIATE_THRESHOLD = 0.70
FRAUD_WEIGHT_A = 0.50
FRAUD_WEIGHT_B = 0.30
FRAUD_WEIGHT_C = 0.20

# Time windows (PRD §3.5, §3.7, §3.8)
TRANSACTION_REVERSAL_WINDOW_HOURS = 24
FRAUD_APPEAL_WINDOW_DAYS = 90
CERTIFICATION_PERIOD_MONTHS = 12

# Pagination (PRD §2.3)
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_LIMIT = 10

# Transaction line items (PRD §2.11)
MIN_LINE_ITEMS = 1
MAX_LINE_ITEMS = 50

# EA accepted max_allotment_table_version values (PRD §3.9)
ALLOWED_EA_TABLE_VERSIONS = {1, 2, 3}
