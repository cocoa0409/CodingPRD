"""In-memory data store.

All state lives in module-level dicts keyed by entity id. The store starts
empty on every process boot — no seeding, no preloading, no persistence to
disk. The test harness re-launches the server before every test, which wipes
all state simply because the process is fresh.
"""

import uuid
from datetime import datetime, timezone


# One dict per entity type, keyed by id.
clients = {}
skills = {}
candidates = {}
job_orders = {}
submissions = {}
interviews = {}
placements = {}
timesheets = {}
invoices = {}
invoice_line_items = {}
conversion_fees = {}


def new_id():
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
