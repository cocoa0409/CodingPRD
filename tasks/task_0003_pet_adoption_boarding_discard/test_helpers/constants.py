"""Domain thresholds from scaffold Table 3."""

# Vaccination compliance
SPECIES_VACCINE_MAP = {
    "DOG": ["RABIES", "DHPP", "BORDETELLA"],
    "CAT": ["RABIES", "FVRCP"],
    "RABBIT": ["RHDV"],
    "BIRD": [],
    "OTHER": [],
}

# Boarding requires BORDETELLA for all species except BIRD
BOARDING_EXTRA_VACCINE = "BORDETELLA"
BOARDING_EXEMPT_SPECIES = ["BIRD"]

# Home visit scoring
HOME_VISIT_PASS_THRESHOLD = 70
HOME_VISIT_CONDITIONAL_THRESHOLD = 50
HOME_VISIT_WEIGHTS = {
    "yard_adequate": 25,
    "space_adequate": 30,
    "safety_hazards_found": 25,  # 0 if hazards found, 25 if not
    "existing_pets_compatible": 20,
}
HOME_VISIT_NO_YARD_WEIGHTS = {
    "yard_adequate": 0,
    "space_adequate": 45,
    "safety_hazards_found": 25,
    "existing_pets_compatible": 20,
}
NO_YARD_SPECIES = ["CAT", "BIRD", "RABBIT"]

# Boarding compatibility scoring
SPECIES_MISMATCH_PENALTY = 10
AGGRESSIVE_PENALTY = 25
TEMPERAMENT_CLASH_PENALTY = 15
SPECIAL_NEEDS_PENALTY = 5

# Adoption fee calculation
AGE_SENIOR_THRESHOLD = 84  # months (7 years)
SENIOR_DISCOUNT_RATE = 0.5
LOYALTY_THRESHOLD = 2  # adoption_history_count >= 2

# Boarding fee calculation
LONG_STAY_THRESHOLD = 14  # days
LONG_STAY_DISCOUNT_RATE = 0.9

# Shelter compliance scoring
HOLD_PENALTY_POINTS = 5

# Test defaults for fee schedule amounts
DEFAULT_ADOPTION_BASE_FEE = 150.00
DEFAULT_BOARDING_DAILY_RATE = 35.00
DEFAULT_SPECIAL_NEEDS_SURCHARGE = 25.00
DEFAULT_LOYALTY_DISCOUNT_RATE = 0.10  # 10%
DEFAULT_TAX_RATE = 0.08  # 8%
