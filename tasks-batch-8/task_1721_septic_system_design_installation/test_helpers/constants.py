"""Domain thresholds and numeric constants named in the PRD (section 3 rules)."""

# Design sizing (PRD section on system design derivations)
GPD_PER_BEDROOM = 150                 # book flow per bedroom per day
GPD_PER_BEDROOM_REDUCED = 120         # absorption-area leg under an APPROVED AREA_REDUCTION variance
HIGH_WATER_SURCHARGE = 1.5            # multiplier when site.high_water_table is true

SOIL_APPLICATION_RATES = {
    "SAND": 1.20,
    "LOAM": 0.80,
    "CLAY_LOAM": 0.50,
    "CLAY": 0.30,
}
MIN_LIMITING_LAYER_INCHES = 24        # strictly-less-than triggers the shallow-layer penalty
SHALLOW_LAYER_MULTIPLIER = 1.25

TANK_RETENTION_DAYS = 2.0
TANK_CATALOG_SIZES = [750, 1000, 1250, 1500, 2000, 2500, 3000, 4000, 5000]

RESERVE_FRACTION = 1.0                # reserve area = post-ceil absorption area * 1.0

# Permits (PRD section on permits)
PERMIT_VALIDITY_PERIODS = 6           # inclusive window: issued_period .. issued_period + 5

# Science freshness (PRD section on authority review)
SCIENCE_MAX_AGE_PERIODS = 24          # age exactly 24 still valid; strictly greater is stale

# Materials (PRD section on installation execution)
MATERIAL_BUDGET_PER_SQFT_CENTS = 900  # ceiling = pinned area (sqft) * 900 cents

# Repair replacement estimation (PRD section on repair cases)
REPLACEMENT_COST_PER_GPD_CENTS = 4200

# Maintenance contracts (PRD section on maintenance contracts)
PERIODS_PER_YEAR = 12

# Narrative minimums (PRD sections on decisions and repair cases)
MIN_NOTE_LENGTH = 20

# Standard field ranges (PRD sections on soil science and design)
BEDROOM_COUNT_MIN = 1
BEDROOM_COUNT_MAX = 12
LIMITING_LAYER_MIN = 1
LIMITING_LAYER_MAX = 240
MINUTES_PER_INCH_MIN = 0.5
MINUTES_PER_INCH_MAX = 240.0
TEST_PIT_COUNT_MIN = 2
TEST_PIT_COUNT_MAX = 12

TEST_DEFAULTS = {
    "COUNTY_CODE": "WH",
    "COUNTY_CODES": ["WH"],
    "LEGAL_NAME": "Clearwater Onsite LLC",
    "COMPANY_LICENSE": "CW-100",
    "DESIGNER_NAME": "Dana Designer",
    "DESIGNER_LICENSE": "DSGN-1",
    "OFFICER_NAME": "Harriet Officer",
    "OFFICER_BADGE": "HO-1",
    "MANAGER_NAME": "Pat Manager",
    "MANAGER_EMPLOYEE": "PM-1",
    "SCIENTIST_NAME": "Sam Scientist",
    "SCIENTIST_LICENSE": "SS-1",
    "INSPECTOR_NAME": "Irene Inspector",
    "INSPECTOR_LICENSE": "INS-1",
    "CUSTOMER_NAME": "Olive Owner",
    "CUSTOMER_EMAIL": "olive@example.com",
    "CUSTOMER_PHONE": "555-0100",
    "PARCEL_ID": "P-1",
    "ADDRESS_LINE": "1 Meadow Ln",
    "CREW_LEAD": "Carl Crew",
}
