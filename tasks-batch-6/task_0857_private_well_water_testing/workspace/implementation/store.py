"""In-memory data store and logical clock for the Private Well Water Testing API.

All state lives in process memory only. Every boot starts empty; the test
harness rebuilds all state through the API surface.
"""
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Domain constants (from PRD §2.8, §3.2, §3.3, §3.5, §3.9, §3.10)
# ---------------------------------------------------------------------------
PERMIT_VALIDITY_DAYS = 365
DRILL_TRAVEL_BUFFER_HOURS = 4
REAL_ESTATE_TEST_VALIDITY_DAYS = 90

NITRATE_MCL_MG_L = 10.0
NITRATE_ADVISORY_MG_L = 5.0
LEAD_ACTION_PPB = 15.0

# permit_fee
DEPTH_TIER1_MAX_FT = 100
DEPTH_TIER2_MAX_FT = 300
DEPTH_TIER1_CENTS = 15000
DEPTH_TIER2_CENTS = 25000
DEPTH_TIER3_CENTS = 40000
USE_MULT = {"DOMESTIC": "1.0", "IRRIGATION": "1.2", "LIVESTOCK": "1.5"}
AQ_SURCHARGE = {"HIGH": 10000, "MODERATE": 5000, "LOW": 0}
EXPEDITE_FEE_CENTS = 20000

# panel_fee
ANALYTE_BASE_CENTS = {"BACTERIA": 3000, "NITRATE": 2500, "LEAD": 4500}
PANEL_REGION_FACTOR = "1.075"

CLOCK_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    """Holds every collection keyed by id, plus the logical clock."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.aquifers = {}
        self.applicants = {}
        self.drillers = {}
        self.wells = {}
        self.construction_permits = {}
        self.driller_logs = {}
        self.water_samples = {}
        self.sample_results = {}
        self.advisories = {}
        self.contamination_cases = {}
        self.abandonment_permits = {}
        self.real_estate_requirements = {}
        self._clock = CLOCK_DEFAULT
        self._seq = 0

    # -- logical clock -----------------------------------------------------
    def now(self):
        return self._clock

    def set_clock(self, dt):
        self._clock = dt

    # -- monotonic insertion sequence (stable tie-break for ordering) ------
    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()
