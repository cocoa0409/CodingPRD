"""In-memory data store. Each table is a dict id -> entity dict."""
import uuid
import threading

from clock import now, iso


# Tables
parking_lots = {}     # id -> ParkingLot
zones = {}            # id -> Zone
spaces = {}           # id -> Space
vehicles = {}         # id -> Vehicle
cards = {}            # id -> Card
sessions_tbl = {}     # id -> Session
reservations = {}     # id -> Reservation
violations = {}       # id -> Violation
fines = {}            # id -> Fine (one per Violation)
payments = {}         # id -> Payment (append-only)
revenue_entries = {}  # id -> RevenueEntry (append-only)
audit_logs = {}       # id -> AuditLog (append-only)
invoices = {}         # id -> Invoice (settlement runs)

# Idempotency index for Payment.external_ref values
external_ref_index = {}  # external_ref -> payment_id


# Insertion order tracking for stable list ordering by created_at ascending
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
    """Stamp a new row: assign id (if missing), created_at, _seq.

    common_fields=True also sets updated_at and version=1.
    """
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


ALL_TABLES = [
    parking_lots, zones, spaces, vehicles, cards, sessions_tbl,
    reservations, violations, fines, payments, revenue_entries,
    audit_logs, invoices,
]


def reset_all() -> None:
    """Reset all data."""
    global _seq
    for tbl in ALL_TABLES:
        tbl.clear()
    external_ref_index.clear()
    with _seq_lock:
        _seq = 0
