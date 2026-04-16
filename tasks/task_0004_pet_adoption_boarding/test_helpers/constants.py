"""Domain thresholds from scaffold Table 3."""

# Species vaccine requirements (Table 3 — vaccination_compliance)
# adoption variant
SPECIES_VACCINE_MAP = {
    "DOG": ["RABIES", "DHPP"],
    "CAT": ["RABIES", "FVRCP"],
    "RABBIT": ["RHDV"],
    "BIRD": [],
    "OTHER": [],
}
# boarding variant adds BORDETELLA for DOG
SPECIES_VACCINE_MAP_BOARDING = {
    "DOG": ["RABIES", "DHPP", "BORDETELLA"],
    "CAT": ["RABIES", "FVRCP"],
    "RABBIT": ["RHDV"],
    "BIRD": [],
    "OTHER": [],
}

# Home visit scoring (Table 3 — home_visit_scoring)
PASS_THRESHOLD = 70
CONDITIONAL_THRESHOLD = 50
# Standard rubric point weights
HV_YARD_POINTS = 25
HV_SPACE_POINTS = 30
HV_NO_HAZARD_POINTS = 25
HV_PETS_POINTS = 20
# yard_optional variant (CAT, BIRD, RABBIT)
HV_YARD_OPTIONAL_YARD_POINTS = 0
HV_YARD_OPTIONAL_SPACE_POINTS = 55

# Boarding compatibility scoring (Table 3)
BASE_COMPATIBILITY = 100
SPECIES_MISMATCH_PENALTY = 10
AGGRESSIVE_PENALTY = 25
TEMPERAMENT_CLASH_PENALTY = 15
SPECIAL_NEEDS_PENALTY = 5

# Adoption fee calculation (Table 3)
AGE_SENIOR_THRESHOLD_MONTHS = 84  # 7 years
SENIOR_DISCOUNT_RATE = 0.5
LOYALTY_THRESHOLD = 2

# Boarding fee calculation (Table 3)
LONG_STAY_THRESHOLD_DAYS = 14
LONG_STAY_DISCOUNT_RATE = 0.9

# Shelter compliance score (Table 3)
HOLD_PENALTY_POINTS = 5

# Shelter validation ranges (Table 4)
MIN_TAX_RATE = 0.0
MAX_TAX_RATE = 0.30
MIN_BOARDING_CAPACITY = 1

# Pagination defaults
DEFAULT_LIMIT = 20
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
