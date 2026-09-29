"""Named literals drawn from the PRD's domain-requirement sections.

Nothing here is computed by the helpers: the constants exist so tests can
reference the published thresholds by name instead of repeating magic numbers.
"""

# --------------------------------------------------------------------------
# Logical clock (PRD §2.7)
# --------------------------------------------------------------------------
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------
# Water chemistry: habitat target bands (PRD §3.1)
# key -> (temp target, temp band, salinity target, salinity band,
#         ph target, ph band, oxygen warn, oxygen critical)
# --------------------------------------------------------------------------
HABITAT_TARGETS = {
    "COLD_MARINE": {
        "temperature_target": 12.0,
        "temperature_band": 1.5,
        "salinity_target": 33.0,
        "salinity_band": 1.0,
        "ph_target": 8.1,
        "ph_band": 0.2,
        "oxygen_warn": 7.0,
        "oxygen_critical": 5.5,
    },
    "TROPICAL_MARINE": {
        "temperature_target": 25.0,
        "temperature_band": 1.5,
        "salinity_target": 35.0,
        "salinity_band": 1.0,
        "ph_target": 8.2,
        "ph_band": 0.2,
        "oxygen_warn": 6.0,
        "oxygen_critical": 4.5,
    },
    "FRESHWATER": {
        "temperature_target": 22.0,
        "temperature_band": 2.0,
        "salinity_target": 0.5,
        "salinity_band": 0.5,
        "ph_target": 7.2,
        "ph_band": 0.3,
        "oxygen_warn": 6.5,
        "oxygen_critical": 5.0,
    },
    "TOUCH_POOL": {
        "temperature_target": 14.0,
        "temperature_band": 1.0,
        "salinity_target": 33.0,
        "salinity_band": 1.0,
        "ph_target": 8.1,
        "ph_band": 0.2,
        "oxygen_warn": 7.5,
        "oxygen_critical": 6.0,
    },
}

AMMONIA_WARN = 0.02
AMMONIA_CRITICAL = 0.05
NITRITE_WARN = 0.1
NITRITE_CRITICAL = 0.25

WQI_SUM_WEIGHT = 6.0
WQI_MAX_WEIGHT = 15.0
WQI_TOUCH_POOL_CONTACT_WEIGHT = 10.0
WQI_TOUCH_POOL_AMMONIA_PIVOT = 0.5

SEVERITY_WARNING_RATIO = 1.0
SEVERITY_CRITICAL_RATIO = 2.0

BREACH_PARAMETER_ORDER = [
    "temperature_c",
    "salinity_ppt",
    "ph",
    "dissolved_oxygen_mg_l",
    "ammonia_mg_l",
    "nitrite_mg_l",
]

# Alarm hysteresis (PRD §3.1)
ALARM_CLEAR_NORMAL_READINGS = 3
ALARM_DEESCALATE_NORMAL_READINGS = 2

# --------------------------------------------------------------------------
# Exhibits (PRD §3.2)
# --------------------------------------------------------------------------
BIOLOAD_PRESSURE_PCT = 95.00
INTERACTION_AUTO_DISABLE_THRESHOLD = 2

# --------------------------------------------------------------------------
# Sustainability scoring (PRD §3.5)
# --------------------------------------------------------------------------
RATING_POINTS = {"GREEN": 40.0, "YELLOW": 24.0, "RED": 8.0}
SOURCE_POINTS = {
    "CAPTIVE_BRED": 35.0,
    "RESCUE_STRANDING": 30.0,
    "INSTITUTIONAL_TRANSFER": 22.0,
    "WILD_COLLECTION": 10.0,
}
INSTITUTION_WELFARE_WEIGHT = 0.25
NO_INSTITUTION_POINTS = 20.0
PROTECTION_PENALTY = {
    "UNLISTED": 0.0,
    "CITES_APPENDIX_II": 6.0,
    "CITES_APPENDIX_I": 14.0,
    "ESA_LISTED": 18.0,
}
PERMIT_BONUS = 5.0
QUOTA_PRESSURE_WEIGHT = 20.0
MIN_CLEARANCE_SCORE = 40.00

# --------------------------------------------------------------------------
# Quarantine protocol (PRD §3.6)
# --------------------------------------------------------------------------
TAXON_MULTIPLIER = {
    "ELASMOBRANCH": 1.5,
    "TELEOST": 1.0,
    "INVERTEBRATE": 0.5,
    "MARINE_MAMMAL": 2.0,
    "REPTILE": 1.25,
    "BIRD": 1.25,
}
WILD_SURCHARGE_DAYS = 14
NON_ACCREDITED_SURCHARGE_DAYS = 10
PROVISIONAL_SURCHARGE_DAYS = 5
HIGH_TIER_TAXON_DAYS = 45
HIGH_TIER_EXTRA_DAYS = 7
QUARANTINE_MAX_EXTENSIONS = 2
CLEARANCE_EXAMS_REQUIRED = 2

# --------------------------------------------------------------------------
# Welfare scoring (PRD §3.7)
# --------------------------------------------------------------------------
BASE_WELFARE = 40.0
APPETITE_WEIGHT = 8.0
BEHAVIOR_POINTS = {
    "NORMAL": 10.0,
    "LETHARGIC": 4.0,
    "AGGRESSIVE": 2.0,
    "ABNORMAL_SWIM": 0.0,
}
OPEN_TREATMENT_PENALTY = 6.0
MISSING_DAY_PENALTY = 3.0
ROLLING_WINDOW_SIZE = 5
AUDIT_WINDOW_DAYS = 14

# --------------------------------------------------------------------------
# Permits and transfers (PRD §3.4, §3.8)
# --------------------------------------------------------------------------
PERMIT_MAX_ROUNDS = 3
PERMIT_DEADLINE_DAYS = 30
PERMIT_MAX_VALIDITY_DAYS = 730
TRANSFER_MAX_COUNTERS = 2
MIN_RECEIVER_WELFARE_SCORE = 70.00

# --------------------------------------------------------------------------
# Interaction sessions (PRD §3.9)
# --------------------------------------------------------------------------
SESSION_BUFFER_MINUTES = 30

# --------------------------------------------------------------------------
# Accreditation readiness (PRD §3.9)
# --------------------------------------------------------------------------
DOMAIN_WEIGHTS = {
    "LIFE_SUPPORT": 0.30,
    "ANIMAL_HEALTH": 0.25,
    "RECORDS": 0.20,
    "PERMITS": 0.15,
    "PUBLIC_SAFETY": 0.10,
}
REDUNDANCY_PENALTY = 10.00
OFFLINE_PENALTY = 25.00
RECORD_GAP_PENALTY = 5.00
PERMIT_GAP_PENALTY = 20.00
SUSPENSION_PENALTY = 15.00
DISABLED_EXHIBIT_PENALTY = 25.00
BLOCKING_PENALTY = 4.00
AUDIT_PASS_SCORE = 85.00
AUDIT_CONDITIONAL_SCORE = 70.00

# --------------------------------------------------------------------------
# Pagination (PRD §2.5)
# --------------------------------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100
