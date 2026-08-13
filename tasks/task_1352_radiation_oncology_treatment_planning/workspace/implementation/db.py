"""In-memory data store. Starts completely empty on every boot — the harness
relaunches the server per test, and no entity is ever seeded at startup."""
import threading

from timeutil import DEFAULT_CLOCK, now_iso


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.seq = 0
        self.clock = DEFAULT_CLOCK
        self.patients = {}
        self.courses = {}
        self.simulations = {}
        self.contours = {}
        self.plans = {}
        self.constraints = {}
        self.checks = {}
        self.machines = {}
        self.sessions = {}
        self.interruptions = {}
        self.reviews = {}
        self.claims = {}
        self.lines = {}

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()


def new_entity(common=True):
    """Base field set. `common` resources carry updated_at + version; the
    immutable record kinds (physics check, chart review, charge line) do not."""
    e = {"_seq": store.next_seq(), "created_at": now_iso()}
    if common:
        e["updated_at"] = e["created_at"]
        e["version"] = 1
    return e


def touch(entity):
    """Refresh updated_at and bump version after a mutation (incl. cascades)."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 0) + 1


def sorted_all(items):
    """Default list ordering: created_at ascending (insertion order breaks ties)."""
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
