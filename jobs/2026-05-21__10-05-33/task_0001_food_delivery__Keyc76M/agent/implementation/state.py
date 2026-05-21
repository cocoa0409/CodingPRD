"""In-memory store and clock for the food-delivery platform.

The store is a single mutable container used by every route handler. All
mutations are performed while holding a single re-entrant lock so the
"first-writer-wins" semantics required by the PRD hold under Flask's
threaded request model.
"""

import random
import string
import threading
import uuid
from datetime import datetime, timezone, timedelta


_LOCK = threading.RLock()


class _Store:
    def __init__(self):
        # Entity tables (id -> dict)
        self.restaurants = {}
        self.menu_items = {}
        self.customers = {}
        self.riders = {}
        self.orders = {}
        self.assignments = {}
        self.route_groups = {}
        self.returns = {}
        self.fines = {}
        self.work_orders = {}

        # Logical clock = real_now - start_real + offset
        self._start_real = datetime.now(timezone.utc)
        self.offset_seconds = 0.0

        # Uniqueness indices
        self.customer_phones = set()
        self.rider_phones = set()
        self.restaurant_names_active = {}  # name -> restaurant_id

        # Rider history (offer outcomes and delivery on-time rate, last-30)
        self.rider_offer_history = {}      # rider_id -> list[bool accepted]
        self.rider_delivery_history = {}   # rider_id -> list[bool on_time]
        self.rider_rating_history = {}     # rider_id -> list[float ratings]

    def reset(self):
        self.__init__()


STORE = _Store()


def lock():
    return _LOCK


def now():
    """Return the current logical UTC datetime."""
    return datetime.now(timezone.utc) + timedelta(seconds=STORE.offset_seconds)


def fmt_dt(dt):
    """Format datetime as ISO 8601 UTC with 3 fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (
        dt.strftime("%Y-%m-%dT%H:%M:%S")
        + "."
        + f"{int(dt.microsecond / 1000):03d}Z"
    )


def gen_id():
    return str(uuid.uuid4())


_REQ_ALPHA = string.ascii_uppercase + string.digits


def gen_req_id():
    return "req_" + "".join(random.choices(_REQ_ALPHA, k=20))


def advance_clock(seconds):
    STORE.offset_seconds += float(seconds)
