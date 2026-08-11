"""In-memory data store. Starts empty on every boot — no seeding."""
import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def fmt_wall(dt):
    """Wall-clock timestamps: ISO 8601 UTC with three fractional digits."""
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{dt.microsecond // 1000:03d}' + 'Z'


def now_wall():
    return datetime.now(timezone.utc)


def fmt_logical(dt):
    """Logical-clock timestamps: ISO 8601 UTC, fractional digits only when set."""
    s = dt.strftime('%Y-%m-%dT%H:%M:%S')
    if dt.microsecond:
        s += f'.{dt.microsecond // 1000:03d}'
    return s + 'Z'


class Store:
    def __init__(self):
        self.warehouses = {}
        self.zones = {}
        self.products = {}
        self.lots = {}
        self.customers = {}
        self.orders = {}
        self.order_lines = {}
        self.reservations = {}
        self.shipments = {}
        self.excursions = {}
        self.standing_orders = {}
        self.agreements = {}
        self.consumption_records = {}
        self.recalls = {}
        self.kits = {}
        self.jobs = {}
        self.payments = []  # internal: {customer_id, amount_cents}
        # logical clock: before any client sets it, exactly 2026-05-01T00:00:00Z
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.creation_counter = 0     # per-system creation order (tie-break)
        self.submission_seq_counter = 0  # monotonic order submission sequence

    def next_creation_seq(self):
        self.creation_counter += 1
        return self.creation_counter

    def next_submission_seq(self):
        self.submission_seq_counter += 1
        return self.submission_seq_counter

    def touch(self, kind, rid, touched):
        """Mark a resource mutated in this request: version +1, updated_at refresh.

        A resource is bumped at most once per request, and only when changed.
        ConsumptionRecord has no version/updated_at and is never touched here.
        """
        key = (kind, rid)
        if key in touched:
            return
        touched.add(key)
        rec = getattr(self, kind)[rid]
        rec['version'] = rec.get('version', 0) + 1
        if 'updated_at' in rec:
            rec['updated_at'] = fmt_wall(now_wall())

    def new_common(self):
        ts = fmt_wall(now_wall())
        return {
            'id': new_id(),
            'created_at': ts,
            'updated_at': ts,
            'version': 1,
            '_seq': self.next_creation_seq(),
        }


db = Store()


def reset():
    global db
    db = Store()
    return db
