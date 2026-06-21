"""In-memory data store. Starts empty on every boot — no seeding."""
import threading
import uuid
from datetime import datetime, timezone

# A single global lock to keep state mutations atomic across requests.
LOCK = threading.RLock()


class Store:
    def __init__(self):
        self.projects = {}
        self.segments = {}
        self.estimates = {}
        self.permits = {}
        self.material_orders = {}
        self.weather_readings = {}
        self.crews = {}
        self.equipment = {}
        self.crew_assignments = {}
        self.change_orders = {}
        self.draws = {}
        self.warranties = {}
        # Logical clock: defaults to real wall-clock UTC until set explicitly.
        self._logical_clock = None
        # Monotonic counter to provide a stable secondary sort / tie-break that
        # mirrors insertion order even when created_at timestamps collide.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        """Real wall-clock UTC, used for created_at / updated_at minting."""
        return datetime.now(timezone.utc)

    def logical_now(self):
        """Current logical UTC instant used for cure-window / completion checks."""
        if self._logical_clock is not None:
            return self._logical_clock
        return datetime.now(timezone.utc)

    def set_logical_clock(self, dt):
        self._logical_clock = dt


db = Store()


def new_id():
    return str(uuid.uuid4())
