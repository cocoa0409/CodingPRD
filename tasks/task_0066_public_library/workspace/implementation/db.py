"""In-memory data store."""
import uuid
import threading

from clock import now, iso


# Entity tables: id -> entity dict
book_titles = {}
copies = {}
readers = {}
cards = {}
loans = {}
reservations = {}
fines = {}
ill_requests = {}
acquisition_suggestions = {}
audit_logs = {}

# Idempotency-key registry for fine payments. Maps idempotency_key -> {"fine_id": ..., "consumed": False}
payment_events = {}

# Pending availability events for ILLRequest. Maps ill_request_id -> {"available": bool, "partner_max_days": int}
ill_availability = {}


_seq_lock = threading.Lock()
_seq = 0
_lock = threading.RLock()


def next_seq() -> int:
    global _seq
    with _seq_lock:
        _seq += 1
        return _seq


def lock():
    return _lock


def gen_id() -> str:
    return str(uuid.uuid4())


def stamp_create(d: dict, *, common_fields: bool = True) -> dict:
    ts = iso(now())
    d.setdefault("id", gen_id())
    d["created_at"] = ts
    d["_seq"] = next_seq()
    if common_fields:
        d["updated_at"] = ts
        d["version"] = 1
    return d


def stamp_update(d: dict) -> None:
    if "version" in d:
        d["version"] = d["version"] + 1
    if "updated_at" in d:
        d["updated_at"] = iso(now())


def public(d: dict) -> dict:
    """Strip private fields (those starting with underscore)."""
    return {k: v for k, v in d.items() if not k.startswith("_")}


# Card-number sequence: per-year monotonically increasing
_card_number_counters = {}


def next_card_number(year: int) -> str:
    with _seq_lock:
        n = _card_number_counters.get(year, 0) + 1
        _card_number_counters[year] = n
    return f"LIB-{year:04d}-{n:06d}"


def reset_all() -> None:
    global _seq
    for tbl in [book_titles, copies, readers, cards, loans, reservations,
                fines, ill_requests, acquisition_suggestions, audit_logs,
                payment_events, ill_availability]:
        tbl.clear()
    with _seq_lock:
        _seq = 0
        _card_number_counters.clear()
