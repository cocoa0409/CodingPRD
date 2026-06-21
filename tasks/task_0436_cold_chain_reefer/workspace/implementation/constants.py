"""Domain constants read from SCAFFOLD.yaml §1.0–§1.7 and PRD §2–§3.

Every structural name (roles, enums, error ids, calc constants) is pinned here
so the rest of the code references it symbolically rather than by literal.
"""

# ---- Roles (PRD §2.1) ----
ROLES = {"Shipper", "Carrier", "Driver", "ComplianceOfficer", "PlatformAdmin"}

# ---- Logical clock default (PRD §3.6 / endpoint §1.5) ----
CLOCK_DEFAULT_UTC = "2026-01-01T00:00:00Z"

# ---- Pagination (PRD §2.3 / §1.0 pagination_defaults) ----
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# ---- Enum domains ----
REEFER_STATUSES = ["AVAILABLE", "ASSIGNED", "IN_TRANSIT", "RETIRED"]
CARGO_CLASSES = ["FOOD", "PHARMA", "GENERAL"]
SHIPMENT_STATUSES = [
    "TENDERED", "ACCEPTED", "PRECOOLED", "IN_TRANSIT",
    "DELIVERED", "REJECTED", "CANCELLED",
]
POSTURES = ["INTACT", "AT_RISK", "COMPROMISED"]
IMPAIRMENTS = ["NONE", "PARTIAL", "TOTAL_LOSS"]
SPOILAGE_STATUSES = ["SOUND", "IMPAIRED", "SPOILED"]
READING_KINDS = ["TEMP", "DOOR_OPEN", "PRECOOL"]
CLAIM_STATUSES = ["FILED", "UNDER_REVIEW", "APPROVED", "DENIED", "WITHDRAWN"]
STOP_KINDS = ["PICKUP", "DELIVERY"]
STOP_STATUSES = ["SCHEDULED", "ARRIVED", "CLOSED"]

# ---- Defaults (SCAFFOLD §1.1) ----
CARRIER_FSMA_DEFAULT = False
CARRIER_SANITARY_DEFAULT = False
CARRIER_LIABILITY_CAP_DEFAULT = 5_000_000
TEMP_LANE_REGULATED_DEFAULT = True
TEMP_LANE_TOLERANCE_DEFAULT = 30

# ---- Calculation constants (SCAFFOLD §1.3) ----
TOL_PARTIAL_SPAN = 90            # impairment / spoilage partial span (degree-minutes)

# detention_fee
FREE_TIME_MIN = 120
DET_TIER1_MAX = 4
RATE1_CENTS = 5000
RATE2_CENTS = 7500

# lumper_fee
LUMPER_BASE_CENTS = 7500
LUMPER_PER_PALLET_CENTS = 350
LUMPER_MULTITEMP_SURCHARGE_CENTS = 2500

# load_integrity_score
PRECOOL_PENALTY = 30
DOOR_PENALTY = 5
DOOR_FREE = 2
EXC_PER_DEGREE_HOUR = 10

# stop_window_overlap
STOP_SERVICE_MIN = 60
STOP_BUFFER_MIN = 30
