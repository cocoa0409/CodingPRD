"""In-memory data store. All dicts keyed by id. Store starts empty on every boot."""

import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


class Store:
    def __init__(self):
        self.operations = {}          # GrowerOperation
        self.baselines = {}           # ProductionBaseline
        self.policies = {}            # InsurancePolicy
        self.plans = {}               # MarketingPlan
        self.price_targets = {}       # PriceTarget
        self.recommendations = {}     # HedgeRecommendation
        self.positions = {}           # BrokeragePosition
        self.margin_accounts = {}     # MarginAccount
        self.buyers = {}              # Buyer
        self.contracts = {}           # SalesContract
        self.tickets = {}             # DeliveryTicket
        self.storage_lots = {}        # StorageLot
        self.agreements = {}          # AdvisoryAgreement
        self.market_ticks = {}        # MarketTick


DB = Store()

# Logical clock: default 2026-05-01T00:00:00Z
_CLOCK_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_logical_now = _CLOCK_DEFAULT


def logical_now():
    return _logical_now


def set_logical_now(dt):
    global _logical_now
    _logical_now = dt


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits."""
    dt = logical_now()
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"
