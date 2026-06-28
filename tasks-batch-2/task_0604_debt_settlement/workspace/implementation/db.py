"""In-memory data store. Starts empty on every boot; no seeding."""
import uuid
from decimal import Decimal, ROUND_HALF_UP

from clock import clock, format_iso8601


def new_id():
    return str(uuid.uuid4())


def round_half_up(value, places=2):
    """Round a numeric/Decimal value to `places` decimals using ROUND_HALF_UP."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    q = Decimal(1).scaleb(-places)  # 10^-places
    return d.quantize(q, rounding=ROUND_HALF_UP)


def money(value):
    """Coerce to a Decimal money value (2 dp)."""
    return round_half_up(value, 2)


def num(d):
    """Convert a Decimal to a JSON-friendly number (int if integral, else float)."""
    if isinstance(d, Decimal):
        if d == d.to_integral_value():
            return int(d)
        return float(d)
    return d


class Store:
    def __init__(self):
        self.clients = {}
        self.programs = {}
        self.accounts = {}
        self.debts = {}
        self.deposits = {}
        self.offers = {}
        self.settlements = {}
        self.fees = {}
        self.lawsuits = {}
        self.tax_events = {}

    def reset(self):
        self.__init__()


store = Store()


def stamp_new(entity):
    """Set common system fields on a freshly created entity."""
    now = format_iso8601(clock.get())
    entity.setdefault("id", new_id())
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    return entity


def touch(entity):
    """Refresh updated_at and bump version on mutation."""
    entity["updated_at"] = format_iso8601(clock.get())
    entity["version"] = entity.get("version", 1) + 1
    return entity
