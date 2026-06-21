"""In-memory data store. Starts empty on every boot. No seeding.

Per-test-server isolation: every test invokes `bash start.sh`, which spawns a
fresh Python process; this module is re-imported and `store` is reconstructed
empty. No file persistence anywhere.
"""
from datetime import datetime, timezone


def utc_now_iso() -> str:
    """ISO 8601 UTC with millisecond precision (3 fractional digits), e.g.
    2025-05-24T10:30:00.123Z.
    """
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class Store:
    """Pure in-memory dict store keyed by id."""

    def __init__(self):
        self.guests = {}                       # id -> Guest
        self.restaurants = {}                  # id -> Restaurant
        self.park_sessions = {}                # id -> ParkSession
        self.dining_plans = {}                 # id -> DiningPlan
        self.reservations = {}                 # id -> Reservation
        self.allergy_meals = {}                # id -> AllergyMeal
        self.lightning_lane_addons = {}        # id -> LightningLaneAddOn
        self.no_show_fee_assessments = {}      # id -> NoShowFeeAssessment (append-only)
        self.credit_ledger_entries = {}        # id -> CreditLedgerEntry (append-only)
        # Server logical clock, an ISO 8601 UTC string. Defaults to real wall
        # clock; mutated by POST /v1/_clock/set_current_utc.
        self.current_utc = utc_now_iso()


# Module-level singleton (per process). Re-created on every process boot.
store = Store()
