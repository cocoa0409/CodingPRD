"""In-memory data store. Starts empty on every boot — NO seeding.

Each entity collection is a dict keyed by id. Common-field bookkeeping
(created_at / updated_at / version) is handled by insert()/touch().
"""
from util import new_id, now_iso


class Store:
    def __init__(self):
        self.festivals = {}
        self.zones = {}
        self.stages = {}
        self.parking_lots = {}
        self.camping_areas = {}
        self.tickets = {}
        self.wristbands = {}
        self.wallet_txns = {}
        self.vendor_applications = {}
        self.vendors = {}
        self.performances = {}
        self.addons = {}
        self.gate_events = {}
        self.refunds = {}
        self.incidents = {}
        # monotonic sequence so list ordering by created_at is stable even when
        # multiple rows share the same millisecond timestamp.
        self._seq = 0
        # server "now" pinned via /_clock/set_current_utc (None => real time)
        self.clock_iso = None

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def insert(collection, fields, common=True):
    """Create a row with system fields. Returns the stored dict."""
    rec = dict(fields)
    rec["id"] = new_id()
    ts = now_iso()
    rec["created_at"] = ts
    rec["_seq"] = db.next_seq()
    if common:
        rec["updated_at"] = ts
        rec["version"] = 1
    collection[rec["id"]] = rec
    return rec


def touch(rec):
    """Record a mutation: refresh updated_at and bump version (PRD §2.4)."""
    rec["updated_at"] = now_iso()
    if "version" in rec:
        rec["version"] += 1
    return rec
