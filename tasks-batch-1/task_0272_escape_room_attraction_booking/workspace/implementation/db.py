"""In-memory data store. Starts EMPTY on every boot. No seeding."""
import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def now_iso():
    # ISO 8601 UTC with millisecond (3 fractional-digit) precision.
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.venues = {}
        self.rooms = {}
        self.pricing_rules = {}
        self.game_masters = {}
        self.time_slots = {}
        self.customers = {}
        self.bookings = {}
        self.participants = {}
        self.gift_cards = {}
        self.gift_card_entries = {}


# Single global store instance; recreated fresh per process boot.
db = Store()
