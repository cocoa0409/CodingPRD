"""In-memory data store and logical clock."""
import uuid
from datetime import datetime, timezone, date

# ---------------------------------------------------------------------------
# Logical clock. Default reads exactly 2026-05-01T00:00:00Z until moved.
# ---------------------------------------------------------------------------
_DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": _DEFAULT_CLOCK}

# Monotonic insertion sequence, used as the tie-break for created_at ordering.
_seq = {"n": 0}

# Collections: name -> {id: row}
COLLECTIONS = [
    "advisors", "communities", "inventories", "families", "inquiries",
    "assessments", "matches", "tours", "placements", "invoices",
    "ledger_entries", "guidances", "surveys", "assignments",
]
DB = {name: {} for name in COLLECTIONS}


def reset():
    for name in COLLECTIONS:
        DB[name] = {}
    _clock["now"] = _DEFAULT_CLOCK
    _seq["n"] = 0


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Clock helpers
# ---------------------------------------------------------------------------
def get_now():
    return _clock["now"]


def set_now(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    _clock["now"] = dt


def now_date():
    return _clock["now"].astimezone(timezone.utc).date()


def render_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return render_ts(_clock["now"])
