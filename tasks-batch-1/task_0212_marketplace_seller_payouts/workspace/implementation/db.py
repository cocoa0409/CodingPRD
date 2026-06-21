"""In-memory data store.

Dicts keyed by id. Starts empty on every process boot — NO seeding, NO
preloaded entities. Every entity is created by tests through the declared API
surface.

A logical clock (PRD §3.12) backs maturation, representment windows, and
reserve release. It is driven by /_clock/set_current_utc and /_clock/advance.
"""
import uuid
from datetime import datetime, timezone


class DB:
    def __init__(self):
        # One dict per entity collection, keyed by id.
        self.sellers = {}
        self.payout_methods = {}
        self.fee_schedules = {}
        self.orders = {}
        self.ledger_entries = {}
        self.reserves = {}
        self.refunds = {}
        self.chargebacks = {}
        self.disputes = {}
        self.payouts = {}
        self.tax_forms = {}
        self.balance_statements = {}
        # Logical clock: defaults to real wall-clock UTC until a test sets it.
        self._clock = None

    # ---- ids & timestamps -------------------------------------------------
    @staticmethod
    def new_id():
        return str(uuid.uuid4())

    def now(self):
        """Current logical UTC instant (timezone-aware datetime)."""
        if self._clock is not None:
            return self._clock
        return datetime.now(timezone.utc)

    def now_iso(self):
        dt = self.now()
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"

    def set_clock(self, dt):
        self._clock = dt


db = DB()
