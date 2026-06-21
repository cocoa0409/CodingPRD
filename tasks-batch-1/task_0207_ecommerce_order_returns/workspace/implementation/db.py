"""In-memory data store. Starts empty on every boot. No seeding, no disk."""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        # one dict per entity collection, keyed by id
        self.customers = {}
        self.warehouses = {}
        self.products = {}
        self.inventory_items = {}
        self.orders = {}
        self.order_lines = {}
        self.reservations = {}
        self.shipments = {}
        self.shipment_lines = {}
        self.return_authorizations = {}
        self.return_lines = {}
        self.refunds = {}
        self.credit_ledger_entries = {}

        # monotonically increasing sequence used as the deterministic
        # creation-order tie-break (so equal created_at timestamps still
        # sort deterministically by insertion order, never by id).
        self._seq = 0

        # logical UTC clock (PRD §2.10). Defaults to real wall clock until
        # explicitly set by the test-driving endpoint.
        self.current_clock = datetime.now(timezone.utc)

    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_id(self):
        return str(uuid.uuid4())

    def stamp_create(self, rec, common_fields=True):
        """Populate system fields on create.

        Timestamps derive from the logical clock (PRD §2.10) so that
        clock-driven tests see created_at follow the clock they set — the
        trailing-window risk score compares Order/Refund.created_at against a
        cutoff derived from the same logical clock.
        """
        rec["id"] = self.new_id()
        rec["_seq"] = self.next_seq()
        ts = self.current_clock_iso()
        rec["created_at"] = ts
        if common_fields:
            rec["updated_at"] = ts
            rec["version"] = 1
        return rec

    def touch(self, rec):
        """Refresh updated_at and bump version on mutation."""
        if "version" in rec:
            rec["version"] += 1
        if "updated_at" in rec:
            rec["updated_at"] = self.current_clock_iso()
        return rec

    def current_clock_iso(self):
        """Logical UTC clock as ISO 8601 with three fractional digits + 'Z'."""
        dt = self.current_clock
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


db = Store()
