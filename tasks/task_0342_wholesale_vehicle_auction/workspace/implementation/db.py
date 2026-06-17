"""In-memory data store. Starts empty on every boot; no seeding."""
import itertools
import threading
import uuid
from datetime import datetime, timezone

# One dict per entity collection, keyed by id.
sales = {}
lanes = {}
sellers = {}
buyers = {}
consignments = {}
condition_reports = {}
lots = {}              # RunListEntry
bids = {}
arbitration_claims = {}
settlements = {}
gate_passes = {}
carriers = {}
transport_orders = {}

# Global lock so each request mutates state atomically.
lock = threading.RLock()

# Monotonic counter so created_at ordering is stable even within the same ms.
_seq = itertools.count()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(now.microsecond // 1000)


def next_seq():
    return next(_seq)
