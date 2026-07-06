"""Domain thresholds — numeric constants from PRD calculations."""

# Autopsy fee constants (PRD §3.4)
BASE_FEE_CENTS = 150000
BLOCK_FEE_CENTS = 20000
SPECIMEN_FEE_CENTS = 5000
HOMICIDE_MULT = 1.5

# Toxicology interpretation threshold (PRD §3.5)
POSITIVE_THRESHOLD_MG_DL = 80

# Cooler occupancy accounting (PRD §2.9)
SECONDS_PER_DAY = 86400

# A county the office serves (any county other than the unserved ones triages ACCEPTED).
SERVED_COUNTY = "Kings"
# A county not in the served list (drives DECLINED at triage).
UNSERVED_COUNTY = "Elsewhere"
