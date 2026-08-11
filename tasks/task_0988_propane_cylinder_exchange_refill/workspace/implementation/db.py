"""In-memory data store. Everything lives in module-level dicts; a fresh
process start wipes all state. No disk persistence anywhere."""
import uuid
from datetime import datetime, timezone

# Logical clock: startup default is exactly 2026-05-01T00:00:00Z (never wall clock).
_clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

# Wall-clock-free monotonic creation sequence, used to break created_at ties.
_seq = 0

sites = {}
policies = {}
drivers = {}
technicians = {}
cylinders = {}
exchange_orders = {}
refill_tickets = {}
cert_records = {}
leak_reports = {}
restock_runs = {}
commission_statements = {}
recon_sessions = {}

# Per-site monotone sale sequence shared by exchange completions and refill closes.
sale_seq = {}


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


def now_ts():
    """Wall-clock timestamp, ISO 8601 UTC with three fractional digits."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def get_clock():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


def current_date():
    return _clock.date().isoformat()


def new_entity(fields):
    ts = now_ts()
    e = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_created_seq": next_seq(),
    }
    e.update(fields)
    return e


def touch(entity):
    """Every mutation of a row increments version by one and refreshes updated_at."""
    entity["version"] += 1
    entity["updated_at"] = now_ts()


def next_sale_seq(site_id):
    n = sale_seq.get(site_id, 0) + 1
    sale_seq[site_id] = n
    return n
