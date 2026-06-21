"""In-memory data store.

All state lives in plain dicts keyed by id. The store starts EMPTY on every
process boot — nothing is seeded, preloaded, or hardcoded. The per-test-server
harness re-launches the process before each test, so a fresh boot wipes all state.
"""
import threading
import uuid
from datetime import datetime, timezone


# One dict per entity collection, keyed by string id.
facilities = {}
master_formulation_records = {}
ingredient_lots = {}
environmental_logs = {}
prescriptions = {}
compounding_batches = {}
batch_ingredient_usages = {}
quality_control_tests = {}
finished_preparations = {}
dispenses = {}
anticipatory_ledgers = {}
recalls = {}

# Global write lock — keeps multi-step cascades atomic under Flask's threaded server.
lock = threading.RLock()


def reset():
    for d in (
        facilities, master_formulation_records, ingredient_lots, environmental_logs,
        prescriptions, compounding_batches, batch_ingredient_usages,
        quality_control_tests, finished_preparations, dispenses,
        anticipatory_ledgers, recalls,
    ):
        d.clear()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Wall-clock server timestamp (created_at/updated_at), ISO 8601, 3 fractional digits."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"
