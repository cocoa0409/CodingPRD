"""In-memory data store. Starts empty on every boot — no seeding."""
import threading
import uuid

from response import now_iso

# One dict per entity collection, keyed by id.
sections = {}
seats = {}
accounts = {}
season_plans = {}
subscriptions = {}
seat_assignments = {}
payment_plans = {}
installments = {}
ticket_transfers = {}
parking_zones = {}
parking_addons = {}

# Tracks priority points granted per subscription so cancellation can claw back
# exactly that amount.
points_granted = {}  # subscription_id -> int

lock = threading.RLock()


def new_id():
    return str(uuid.uuid4())


def new_common():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def touch(entity):
    """Mutation bookkeeping: refresh updated_at and bump version by 1."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity["version"] + 1
