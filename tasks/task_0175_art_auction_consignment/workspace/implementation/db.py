"""In-memory data store.

All state lives in module-level dicts keyed by id. Every process boot starts
EMPTY — there is no seeding, preloading, or hardcoded data anywhere. The
per-test-server harness relaunches start.sh before every test, which wipes all
state by virtue of being a fresh process.
"""
import threading
import uuid

from response import now_iso

# A single coarse lock makes each request handler atomic, which is what the
# concurrency / OCC semantics in the PRD assume (immediate consistency).
LOCK = threading.RLock()

# One dict per entity type, keyed by id.
premium_schedules = {}
sellers = {}
bidders = {}
auction_sales = {}
consignments = {}
lots = {}
paddle_registrations = {}
bids = {}
invoices = {}
resale_royalties = {}
seller_statements = {}
payouts = {}

# Monotonic sequence to break created_at ties deterministically (creation order).
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


def new_common(with_version=True):
    """Common system fields applied at creation time."""
    ts = now_iso()
    fields = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "_seq": next_seq(),
    }
    if with_version:
        fields["version"] = 1
    return fields


def touch(record):
    """Bump version + updated_at for a mutation (including cascaded ones)."""
    record["version"] = record.get("version", 1) + 1
    record["updated_at"] = now_iso()
