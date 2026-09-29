"""Canonical literals used across the suite.

Every value here is either declared verbatim by the PRD (thresholds, defaults,
enum members, weights) or is a fixed test input chosen once so that expected
outputs can be pinned exactly.
"""

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
# The PRD: "On startup the logical clock is initialised to a fixed default of
# exactly `2026-08-01T00:00:00Z`."
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"


def iso(day: str) -> str:
    """Return a whole-UTC-day instant for ``day`` given as ``YYYY-MM-DD``."""
    return f"{day}T00:00:00Z"


# ---------------------------------------------------------------------------
# Markets and jurisdictions
# ---------------------------------------------------------------------------
MARKET_CODE = "MKT-NE-01"
OTHER_MARKET_CODE = "MKT-NE-02"

JURISDICTION_NAME = "Northeast Township"
HISTORIC_JURISDICTION_NAME = "Historic Village"

BY_RIGHT_REVIEW_DAYS = 60
CONDITIONAL_USE_REVIEW_DAYS = 90
VARIANCE_REVIEW_DAYS = 150
HEARING_CADENCE_DAYS = 14
MIN_VISUAL_SIMULATIONS = 2
MAX_CONTINUANCES = 2
HISTORICAL_DELAY_FACTOR = 1.20
HISTORIC_DELAY_FACTOR = 1.35
APPEAL_WINDOW_DAYS = 30

# ---------------------------------------------------------------------------
# Search ring
# ---------------------------------------------------------------------------
RING_NAME = "Ring 2276-A"
RING_NAME_B = "Ring 2276-B"
RING_CENTER_LAT = 42.3500
RING_CENTER_LON = -71.0600
RING_RADIUS_M = 800
RING_REQUIRED_AGL_M = 45
RING_OBJECTIVE_TYPE = "COVERAGE_AND_CAPACITY"
RING_TARGET_RSRP_DBM = -95
RING_TARGET_CAPACITY_GBPS = 10
MARKET_BENCHMARK_MONTHLY_RENT_USD = 2400.00
CAPEX_BUDGET_USD = 250000.00

# ---------------------------------------------------------------------------
# Landlord
# ---------------------------------------------------------------------------
LANDLORD_NAME = "Beacon Holdings LLC"
LANDLORD_ENTITY_TYPE = "LLC"
LANDLORD_EMAIL = "asset@beacon.example"
TRIBAL_LANDLORD_NAME = "Riverbend Tribal Authority"
TRIBAL_LANDLORD_ENTITY_TYPE = "TRIBAL_AUTHORITY"
TRIBAL_LANDLORD_EMAIL = "lands@riverbend.example"

# ---------------------------------------------------------------------------
# Candidate
# ---------------------------------------------------------------------------
CANDIDATE_LAT = 42.3510
CANDIDATE_LON = -71.0620
CANDIDATE_DISTANCE_M = 200
CANDIDATE_AGL_M = 60
CANDIDATE_MONTHS_TO_AVAILABILITY = 3
CANDIDATE_RSRP_DBM = -88
CANDIDATE_CAPACITY_GBPS = 10

# The canonical candidate above scores 98.50 under the PRD's RF formula.
CANDIDATE_RF_SCORE = 98.50

# ---------------------------------------------------------------------------
# Lease
# ---------------------------------------------------------------------------
LEASE_BASE_RENT_USD = 2400.00
LEASE_ESCALATION_TYPE = "FIXED_PCT"
LEASE_ESCALATION_PCT = 0.03
LEASE_INITIAL_TERM_YEARS = 5
LEASE_RENEWAL_OPTION_COUNT = 2
LEASE_RENEWAL_TERM_YEARS = 5
LEASE_EXPANSION_SQFT = 120
LEASE_REVENUE_SHARE_PCT = 0.05

# ---------------------------------------------------------------------------
# Structural analysis inputs
# ---------------------------------------------------------------------------
TIA_222_H = "TIA_222_H"
TIA_222_G = "TIA_222_G"

# Baseline loading: 55.0 % existing load, 4 appurtenances, 90 mph wind, no ice.
BASE_EXISTING_LOAD_PCT = 55.0
BASE_APPURTENANCE_COUNT = 4
BASE_WIND_SPEED_MPH = 90
BASE_ICE_THICKNESS_IN = 0
BASE_UTILIZATION_PCT = 71.70

# Heavier loading that lands just under the PASS ceiling.
HEAVY_EXISTING_LOAD_PCT = 70.0
HEAVY_APPURTENANCE_COUNT = 6
HEAVY_WIND_SPEED_MPH = 105
HEAVY_ICE_THICKNESS_IN = 0.5
HEAVY_UTILIZATION_H_PCT = 99.70
HEAVY_UTILIZATION_G_PCT = 94.72

# Loading that fails outright.
FAIL_EXISTING_LOAD_PCT = 88.0
FAIL_APPURTENANCE_COUNT = 8
FAIL_WIND_SPEED_MPH = 120
FAIL_ICE_THICKNESS_IN = 1.0
FAIL_UTILIZATION_PCT = 136.86

# ---------------------------------------------------------------------------
# Permit
# ---------------------------------------------------------------------------
PERMIT_TYPE_BUILDING = "BUILDING"
PERMIT_VALID_DAYS_DEFAULT = 180

# ---------------------------------------------------------------------------
# Backhaul
# ---------------------------------------------------------------------------
PROVIDER_NAME = "Bay State Power"
SINGLE_CREW_PROVIDER_NAME = "Single Crew Fiber"

__all__ = [name for name in dir() if not name.startswith("_")]
