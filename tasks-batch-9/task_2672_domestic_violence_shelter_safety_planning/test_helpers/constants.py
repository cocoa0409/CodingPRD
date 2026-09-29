"""Domain constants for the Domestic Violence Shelter & Safety Planning API.

Every value here is transcribed from the PRD narrative (sections 2.x and 3.x)
so that tests never hard-code a magic number whose provenance is unclear.
"""

# --- Roles (PRD 2.1: the six recognised roles, spelled exactly) ---
ROLE_HOTLINE_ADVOCATE = "HotlineAdvocate"
ROLE_SHELTER_MANAGER = "ShelterManager"
ROLE_LEGAL_ADVOCATE = "LegalAdvocate"
ROLE_HOUSING_SPECIALIST = "HousingSpecialist"
ROLE_PRIVACY_OFFICER = "PrivacyOfficer"
ROLE_AGENCY_ADMIN = "AgencyAdmin"

ALL_ROLES = (
    ROLE_HOTLINE_ADVOCATE,
    ROLE_SHELTER_MANAGER,
    ROLE_LEGAL_ADVOCATE,
    ROLE_HOUSING_SPECIALIST,
    ROLE_PRIVACY_OFFICER,
    ROLE_AGENCY_ADMIN,
)

# --- Logical clock (PRD 2.4) ---
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"

# --- Lethality scoring (PRD 3.1) ---
WEAPON_ACCESS_POINTS = 25
STRANGULATION_POINTS = 20
SEPARATION_POINTS = 15
THREATS_TO_KILL_POINTS = 18
STALKING_POINTS_PER_EVENT = 2
STALKING_CAP = 7
CORROBORATION_POINTS_PER_FACT = 6
MULTIPLIER_BOTH_COFACTORS = 1.25
MULTIPLIER_ONE_COFACTOR = 1.10
MULTIPLIER_NO_COFACTOR = 1.00
DANGER_SCORE_CEILING = 100.0
BAND_IMMINENT_MIN = 75.0
BAND_ELEVATED_MIN = 50.0
BAND_MODERATE_MIN = 25.0

VARIANT_INTAKE_SNAPSHOT = "INTAKE_SNAPSHOT"
VARIANT_CORROBORATED_REVIEW = "CORROBORATED_REVIEW"

# --- Safety plan coverage (PRD 3.2) ---
COMPONENT_BASE_WEIGHT = {
    "RELOCATION": 30,
    "COMMUNICATION": 25,
    "TECHNOLOGY": 25,
    "WORKPLACE_NOTIFICATION": 20,
}
IMMINENT_UPLIFT_FACTOR = 1.2
IMMINENT_UPLIFT_TYPES = ("RELOCATION", "TECHNOLOGY")
COMPONENT_STATUS_FACTOR = {
    "IMPLEMENTED": 1.000,
    "DRAFT": 0.350,
    "REVIEW_REQUIRED": 0.175,
    "BLOCKED": 0.000,
}
COVERAGE_SCORE_MAX = 11.10

# --- Shelter capacity (PRD 3.3) ---
NEAR_CAPACITY_FRACTION = 0.20

# --- Staff wellness (PRD 3.4) ---
DISTRESS_POINTS_PER_UNIT = 6
EXPOSURE_POINTS_PER_HOUR = 0.5
DEBRIEF_MITIGATION_FACTOR = 0.70
CASELOAD_POINTS = 2.5
DECAY_FULL_MAX_DAYS = 7
DECAY_PARTIAL_MAX_DAYS = 30
DECAY_PARTIAL_FACTOR = 0.6
TRAUMA_INDEX_CEILING = 100.0
POSTURE_FROZEN_MIN = 70.0
POSTURE_RESTRICTED_MIN = 40.0
WAITLIST_EXPIRY_DAYS = 14

# --- Landlord engagement (PRD 3.8) ---
TIER_PLATINUM_MIN = 60.0
TIER_GOLD_MIN = 30.0
TIER_SILVER_MIN = 10.0
TIER_MULTIPLIER = {
    "PLATINUM": 1.50,
    "GOLD": 1.25,
    "SILVER": 1.10,
    "BASE": 1.00,
}
RAPID_REHOUSING_BONUS_CENTS = 15000

# --- Protective orders (PRD 3.7) ---
TRAVEL_BUFFER_MINUTES = 60
REFILE_LIMIT = 2

# --- Disclosure projection (PRD 3.9) ---
KEY_VOCABULARY = (
    "client_code",
    "legal_name",
    "household_size",
    "minor_children_count",
    "program_type",
    "entry_date",
    "planned_exit_date",
    "shelter_unit_label",
    "shelter_street_address",
    "hotline_call_transcript",
)
HMIS_EXPORT_ALLOWED = (
    "client_code",
    "household_size",
    "minor_children_count",
    "program_type",
    "entry_date",
)
COURT_SUBPOENA_DENIED = ("shelter_unit_label", "shelter_street_address")
PARTNER_AGENCY_DENIED = ("hotline_call_transcript",)
MANDATED_REPORT_DEADLINE_HOURS = 24

# --- Test defaults (shared literals used across fixtures) ---
TEST_DEFAULTS = {
    "NIGHTLY_RATE_CENTS": 8500,
    "WEEKEND_SURCHARGE_CENTS": 2500,
    "CHILD_SUPPLEMENT_CENTS": 1200,
    "BED_CAPACITY": 4,
    "MAX_CASELOAD": 10,
    "BASE_INCENTIVE_CENTS": 40000,
    "UNITS_PLEDGED": 4,
    "ENTRY_DATE": "2026-08-07",
    "PLANNED_EXIT_DATE": "2026-08-12",
}
