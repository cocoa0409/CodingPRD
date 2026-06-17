"""In-memory data store. Starts empty on every boot; nothing is seeded."""
import uuid
from datetime import datetime, timezone, timedelta


class Clock:
    """Server notion of 'now'. Can be overridden via POST /_clock/set_current_utc."""

    def __init__(self):
        self._override = None  # datetime (UTC, tz-aware) or None

    def set(self, dt):
        self._override = dt

    def now(self):
        if self._override is not None:
            return self._override
        return datetime.now(timezone.utc)


class DB:
    def __init__(self):
        # entity collections keyed by id
        self.customers = {}
        self.catalog_products = {}
        self.components = {}
        self.rush_policies = {}
        self.promo_codes = {}
        self.orders = {}
        self.order_lines = {}
        self.proofs = {}
        self.component_allocations = {}
        self.payments = {}
        self.fulfillments = {}
        self.clock = Clock()

    def reset(self):
        self.__init__()


db = DB()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC with three fractional digits, 'Z' suffix."""
    dt = db.clock.now().astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_dt():
    return db.clock.now().astimezone(timezone.utc)
