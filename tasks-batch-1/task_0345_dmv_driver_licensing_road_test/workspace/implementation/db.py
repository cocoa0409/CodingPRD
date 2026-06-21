"""In-memory data store and domain constants.

All state lives in module-level dicts keyed by id. The store starts EMPTY on
every process boot — no seeding, no preloading. Tests build every entity via
the declared API surface.
"""
import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def now_ts():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Domain constants
# ---------------------------------------------------------------------------
# Point / suspension / revocation
POINT_WINDOW_PERIODS = 730
SUSPENSION_POINT_THRESHOLD = 12
REVOCATION_PRIOR_THRESHOLD = 3

# Knowledge / road test
KNOWLEDGE_PASS_THRESHOLD = 80
ROAD_PASS_THRESHOLD = 80
KNOWLEDGE_VALIDITY_PERIODS = 365
KNOWLEDGE_RETAKE_COOLDOWN = 7

# License
LICENSE_TERM_PERIODS = 1825

# Suspension duration tiers (suspension_duration calc)
TIER1_POINTS = 12
TIER2_POINTS = 16
TIER3_POINTS = 24
TIER1_DAYS = 30
TIER2_DAYS = 90
TIER3_DAYS = 180
MULT_STEP = 0.5
MULT_CAP = 3.0

# renewal_fee calc
CLASS_BASE_FEE_CENTS = {"D": 4000, "M": 3500, "A": 6000, "B": 6000, "C": 5500}
SENIOR_AGE = 65
SENIOR_DISCOUNT_CENTS = 2000
REAL_ID_SURCHARGE_CENTS = 3000
LATE_PER_DAY_CENTS = 100
LATE_CAP_CENTS = 5000
AGE_REFERENCE_YEAR = 2026

# reinstatement_fee calc
BASE_REINSTATEMENT_DOLLARS = "75.00"
PER_POINT_DOLLARS = "8.333"
ADMIN_PCT = "0.075"

LICENSE_CLASSES = {"D", "M", "A", "B", "C"}
ENDORSEMENT_CODES = {"H", "P", "S", "N", "T"}
REAL_ID_CATEGORIES = {"IDENTITY", "RESIDENCY", "SSN"}
FEE_PURPOSES = {"RENEWAL", "REINSTATEMENT", "ROAD_TEST", "KNOWLEDGE_TEST"}
ROLES = {"LicenseClerk", "Examiner", "KnowledgeProctor", "AdjudicationOfficer"}


class Store:
    def __init__(self):
        self.current_period = 0
        self.driver_records = {}
        self.examiners = {}
        self.knowledge_tests = {}
        self.road_test_appointments = {}
        self.licenses = {}
        self.violations = {}
        self.suspensions = {}
        self.cdl_endorsements = {}
        self.medical_cards = {}
        self.fee_payments = {}


db = Store()
