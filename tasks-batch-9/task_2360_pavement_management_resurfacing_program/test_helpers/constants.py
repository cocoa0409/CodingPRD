"""Business constants for the Pavement Management & Resurfacing Program API.

Every value here is taken from the PRD: the logical clock default, the condition
band thresholds, the deterioration table, the unit-cost tables, the reusable
segment and observation profiles the test suite builds its scenarios from, and
the pre-computed money literals those profiles produce.
"""

# ----------------------------------------------------------------------
# Roles
# ----------------------------------------------------------------------
ROLE_PAVEMENT_ENGINEER = "PavementEngineer"
ROLE_BUDGET_OFFICER = "BudgetOfficer"
ROLE_UTILITY_COORDINATOR = "UtilityCoordinator"
ROLE_INSPECTOR = "Inspector"
ROLE_CONTRACTOR = "Contractor"
ROLE_RESIDENT = "Resident"

ALL_ROLES = [
    ROLE_PAVEMENT_ENGINEER,
    ROLE_BUDGET_OFFICER,
    ROLE_UTILITY_COORDINATOR,
    ROLE_INSPECTOR,
    ROLE_CONTRACTOR,
    ROLE_RESIDENT,
]

# ----------------------------------------------------------------------
# Logical clock
# ----------------------------------------------------------------------
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
CLOCK_2026_09_15 = "2026-09-15T00:00:00Z"
CLOCK_2026_10_01 = "2026-10-01T00:00:00Z"
CLOCK_2027_08_01 = "2027-08-01T00:00:00Z"
CLOCK_2028_09_30 = "2028-09-30T00:00:00Z"
CLOCK_2028_10_01 = "2028-10-01T00:00:00Z"

# ----------------------------------------------------------------------
# A syntactically perfect UUID that names no row in any collection
# ----------------------------------------------------------------------
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"

# ----------------------------------------------------------------------
# Condition bands and the deterioration model
# ----------------------------------------------------------------------
BAND_GOOD = "GOOD"
BAND_FAIR = "FAIR"
BAND_POOR = "POOR"
BAND_FAILED = "FAILED"

BAND_GOOD_FLOOR = 70.0
BAND_FAIR_FLOOR = 50.0
BAND_POOR_FLOOR = 25.0

DECAY_TABLE = {
    "ARTERIAL": (2.2, 1.6),
    "COLLECTOR": (1.8, 1.3),
    "LOCAL": (1.4, 1.0),
}
DECAY_KNEE_YEARS = 8

SOURCE_MODEL_PROJECTED = "MODEL_PROJECTED"
SOURCE_SURVEY_MEASURED = "SURVEY_MEASURED"

# ----------------------------------------------------------------------
# Treatments
# ----------------------------------------------------------------------
CRACK_SEAL = "CRACK_SEAL"
MILL_AND_OVERLAY = "MILL_AND_OVERLAY"
RECONSTRUCTION = "RECONSTRUCTION"

TREATMENT_FLOOR_CRACK_SEAL = 70.0
TREATMENT_FLOOR_MILL = 40.0

UNIT_RATE_CENTS = {
    CRACK_SEAL: {"LOCAL": 350, "COLLECTOR": 420, "ARTERIAL": 500},
    MILL_AND_OVERLAY: {"LOCAL": 2800, "COLLECTOR": 3300, "ARTERIAL": 4100},
    RECONSTRUCTION: {"LOCAL": 9500, "COLLECTOR": 11000, "ARTERIAL": 13500},
}

MOBILIZATION_CRACK_SEAL_CENTS = 250000
MOBILIZATION_OTHER_CENTS = 850000

SERVICE_LIFE_YEARS = {CRACK_SEAL: 5, MILL_AND_OVERLAY: 15, RECONSTRUCTION: 30}
PCI_GAIN_CAP = {CRACK_SEAL: 8.0, MILL_AND_OVERLAY: 45.0, RECONSTRUCTION: 100.0}
MORATORIUM_YEARS = {CRACK_SEAL: 1, MILL_AND_OVERLAY: 3, RECONSTRUCTION: 5}

# ----------------------------------------------------------------------
# Reusable segment profiles
#
# All are created while the logical clock reads 2026-08-01T00:00:00Z. The four
# segments that supply last_treatment_date 2016-08-01 are exactly ten whole
# years old, two of them past the eight-year knee.
# ----------------------------------------------------------------------
SEG_MAPLE = {
    "street_name": "Maple St",
    "from_node": "1st Ave",
    "to_node": "2nd Ave",
    "geo_zone": "Z1",
    "functional_class": "LOCAL",
    "surface_type": "ASPHALT",
    "length_ft": 1000.0,
    "width_ft": 30.0,
    "baseline_condition_index": 92.0,
    "last_treatment_date": "2016-08-01T00:00:00Z",
}
SEG_GRAND = {
    "street_name": "Grand Blvd",
    "from_node": "1st Ave",
    "to_node": "2nd Ave",
    "geo_zone": "Z1",
    "functional_class": "ARTERIAL",
    "surface_type": "ASPHALT",
    "length_ft": 2000.0,
    "width_ft": 60.0,
    "baseline_condition_index": 100.0,
    "last_treatment_date": "2016-08-01T00:00:00Z",
}
SEG_OAK = {
    "street_name": "Oak St",
    "from_node": "1st Ave",
    "to_node": "2nd Ave",
    "geo_zone": "Z1",
    "functional_class": "LOCAL",
    "surface_type": "ASPHALT",
    "length_ft": 3517.5,
    "width_ft": 30.0,
    "baseline_condition_index": 92.0,
    "last_treatment_date": "2016-08-01T00:00:00Z",
}
SEG_CEDAR = {
    "street_name": "Cedar St",
    "from_node": "1st Ave",
    "to_node": "2nd Ave",
    "geo_zone": "Z1",
    "functional_class": "LOCAL",
    "surface_type": "ASPHALT",
    "length_ft": 1000.0,
    "width_ft": 30.0,
    "baseline_condition_index": 92.0,
    "last_treatment_date": "2016-08-01T00:00:00Z",
}
SEG_BIRCH = {
    "street_name": "Birch St",
    "from_node": "1st Ave",
    "to_node": "2nd Ave",
    "geo_zone": "Z1",
    "functional_class": "LOCAL",
    "surface_type": "ASPHALT",
    "length_ft": 1000.0,
    "width_ft": 30.0,
    "baseline_condition_index": 60.0,
    "last_treatment_date": "2016-08-01T00:00:00Z",
}
SEG_ELM = {
    "street_name": "Elm St",
    "from_node": "1st Ave",
    "to_node": "2nd Ave",
    "geo_zone": "Z3",
    "functional_class": "LOCAL",
    "surface_type": "ASPHALT",
    "length_ft": 1001.0,
    "width_ft": 30.0,
    "baseline_condition_index": 92.0,
    "last_treatment_date": "2016-08-01T00:00:00Z",
}
SEG_PINE = {
    "street_name": "Pine St",
    "from_node": "1st Ave",
    "to_node": "2nd Ave",
    "geo_zone": "Z3",
    "functional_class": "LOCAL",
    "surface_type": "ASPHALT",
    "length_ft": 1004.0,
    "width_ft": 30.0,
    "baseline_condition_index": 92.0,
    "last_treatment_date": "2016-08-01T00:00:00Z",
}

# Areas each profile publishes (length_ft * width_ft / 9, two decimals).
AREA_MAPLE = 3333.33
AREA_GRAND = 13333.33
AREA_OAK = 11725.00
AREA_ELM = 3336.67
AREA_PINE = 3346.67

# Model-projected index each profile publishes at 2026-08-01.
PCI_MAPLE_MODEL = 76.0
PCI_GRAND_MODEL = 76.0
PCI_BIRCH_MODEL = 44.0
PCI_UNTREATED_MODEL = 92.0

# ----------------------------------------------------------------------
# Reusable distress-observation measurement profiles
#
# Each profile is calibrated for one segment geometry, because the alligator,
# longitudinal and patching terms are expressed as percentages of the segment's
# own area or length.
# ----------------------------------------------------------------------
# Maple St (1000.00 x 30.00): deduct 30.90 -> measured index 69.1 (FAIR).
OBS_MILL = {
    "alligator_cracking_sqft": 3000.0,
    "longitudinal_cracking_lf": 500.0,
    "rutting_depth_in": 0.55,
    "patching_sqft": 1500.0,
    "iri_in_per_mi": 155.0,
    "sample_coverage_pct": 100.0,
}
OBS_MILL_DEDUCT = 30.90
OBS_MILL_INDEX = 69.1

# Grand Blvd (2000.00 x 60.00): deduct 70.00 -> measured index 30.0 (POOR).
OBS_RECON = {
    "alligator_cracking_sqft": 24000.0,
    "longitudinal_cracking_lf": 2000.0,
    "rutting_depth_in": 1.25,
    "patching_sqft": 12000.0,
    "iri_in_per_mi": 117.5,
    "sample_coverage_pct": 100.0,
}
OBS_RECON_DEDUCT = 70.00
OBS_RECON_INDEX = 30.0

# Rutting-only profile: deduct 25.00 -> measured index 75.0 on ANY geometry.
OBS_CS75 = {
    "alligator_cracking_sqft": 0.0,
    "longitudinal_cracking_lf": 0.0,
    "rutting_depth_in": 0.875,
    "patching_sqft": 0.0,
    "iri_in_per_mi": 95.0,
    "sample_coverage_pct": 100.0,
}
OBS_CS75_DEDUCT = 25.00
OBS_CS75_INDEX = 75.0

# Maple-geometry profile landing exactly on the 70.0 crack-seal floor.
OBS_70 = {
    "alligator_cracking_sqft": 3000.0,
    "longitudinal_cracking_lf": 500.0,
    "rutting_depth_in": 0.55,
    "patching_sqft": 1500.0,
    "iri_in_per_mi": 143.75,
    "sample_coverage_pct": 100.0,
}
OBS_70_DEDUCT = 30.00
OBS_70_INDEX = 70.0

# Maple-geometry profile landing one tenth below the crack-seal floor.
OBS_699 = {
    "alligator_cracking_sqft": 3000.0,
    "longitudinal_cracking_lf": 500.0,
    "rutting_depth_in": 0.55,
    "patching_sqft": 1500.0,
    "iri_in_per_mi": 145.0,
    "sample_coverage_pct": 100.0,
}
OBS_699_DEDUCT = 30.10
OBS_699_INDEX = 69.9

QC_ACCEPT_NOTE = "LCMS pass reviewed"

# ----------------------------------------------------------------------
# Pre-computed money literals for the standard profiles (all in cents)
# ----------------------------------------------------------------------
# Maple St measured 69.1 -> MILL_AND_OVERLAY
MAPLE_LINE_COST = 9893323
MAPLE_CANDIDATE_COST = 10743323          # line + 850000 mobilization
MAPLE_BUNDLE_BASE = 10743323
MAPLE_CONTINGENCY = 1074332              # 10% tier
MAPLE_TOTAL = 11817655
MAPLE_UTILITY_SHARE = 322300             # 3% of the bundle base
MAPLE_TOTAL_WITH_UTILITY = 12139955

# Grand Blvd measured 30.0 -> RECONSTRUCTION
GRAND_LINE_COST = 236249941
GRAND_CANDIDATE_COST = 237099941

# A Maple-geometry segment measured at exactly 70.0 -> CRACK_SEAL
FLOOR_70_LINE_COST = 1236665
FLOOR_70_CANDIDATE_COST = 1486665        # line + 250000 mobilization

# Oak St measured 75.0 -> CRACK_SEAL
OAK_LINE_COST = 4349975
OAK_CANDIDATE_COST = 4599975
OAK_BUNDLE_BASE = 4599975
OAK_CONTINGENCY = 689996                 # 15% tier
OAK_TOTAL = 5289971

# Elm St measured 75.0 -> CRACK_SEAL
ELM_LINE_COST = 1237905
ELM_CANDIDATE_COST = 1487905
ELM_BUNDLE_BASE = 1487905
ELM_CONTINGENCY = 223186
ELM_TOTAL = 1711091

# Pine St measured 75.0 -> CRACK_SEAL
PINE_LINE_COST = 1241615
PINE_CANDIDATE_COST = 1491615

# Elm + Pine crack-seal bundle
ELM_PINE_AREA = 6683.34
ELM_PINE_BASE = 2729520
ELM_PINE_CONTINGENCY = 409428
ELM_PINE_TOTAL = 3138948

# Maple + Oak mixed bundle
MAPLE_OAK_AREA = 15058.33
MAPLE_OAK_BASE = 15093298
MAPLE_OAK_CONTINGENCY = 1509330
MAPLE_OAK_TOTAL = 16602628

# Funding levels
FUNDING_STANDARD = 20000000
FUNDING_LARGE = 250000000
UNCOMMITTED_AFTER_MAPLE_AWARD = 8182345

# Cut-permit fee literals for a 100.00 sqft non-emergency application
CUT_FEE_BASE = 45000
CUT_FEE_MULT_1_0 = 45000
CUT_FEE_TIER_1_5 = 127500
CUT_FEE_TIER_2_0 = 170000
CUT_FEE_TIER_3_0 = 510000
CUT_FEE_TIER_2_5 = 425000

# ----------------------------------------------------------------------
# Utility roster and coordination
# ----------------------------------------------------------------------
UTILITY_ROSTER = ["WATER", "SEWER", "FRANCHISE_GAS", "FRANCHISE_TELECOM"]

# ----------------------------------------------------------------------
# Pay factors and contractor performance
# ----------------------------------------------------------------------
DENSITY_PASS = 96.0
SMOOTHNESS_BEST = 60.0
STANDING_GOOD_FLOOR = 80.0
STANDING_WATCH_FLOOR = 60.0

# ----------------------------------------------------------------------
# Service requests
# ----------------------------------------------------------------------
SLA_HOURS = {"HIGH": 72, "MEDIUM": 168, "LOW": 720}

# ----------------------------------------------------------------------
# Standard payload defaults
# ----------------------------------------------------------------------
SURVEY_YEAR = 2026
COLLECTION_AUTOMATED = "AUTOMATED_LCMS"
COLLECTION_MANUAL = "MANUAL_WALK"
STRATEGY_WORST_FIRST = "WORST_FIRST"
SCENARIO_NAME = "FY27 program"
HORIZON_YEARS = 10
CONTRACTOR_NAME = "Ace Paving LLC"
PROJECT_START = "2026-09-01T00:00:00Z"
PROJECT_END = "2026-09-30T00:00:00Z"
WORK_WINDOW_START = "2026-09-01T00:00:00Z"
WORK_WINDOW_END = "2026-09-15T00:00:00Z"
DESIGN_THICKNESS_IN = 2.0
