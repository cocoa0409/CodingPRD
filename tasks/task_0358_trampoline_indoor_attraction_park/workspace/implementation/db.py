"""In-memory data store. Starts EMPTY on every boot — no seeding."""
import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def now_dt():
    return datetime.now(timezone.utc)


def iso_ms(dt):
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Store:
    """Per-process in-memory store. One dict per entity type, keyed by id."""

    def __init__(self):
        self.parks = {}
        self.slots = {}
        self.participants = {}
        self.waivers = {}
        self.jump_passes = {}
        self.add_ons = {}
        self.members = {}
        self.memberships = {}
        self.rooms = {}
        self.packages = {}
        self.party_bookings = {}
        self.incidents = {}

    def collection_for(self, name):
        return getattr(self, name)


# Single global store, constructed fresh at import time. start.sh relaunches the
# process before every test, so this is wiped to empty on each boot.
db = Store()
