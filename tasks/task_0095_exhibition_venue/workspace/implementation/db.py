"""In-memory data store.

Tables keyed by uuid string. Each table is a dict { id: row_dict }.

Also exposes:
- new_id(): UUID generator
- new_qr(): unique QR token generator
- LOCK: a re-entrant lock for atomic mutations (used for first-writer-wins serialization)
"""

import threading
import uuid
import secrets
import string


LOCK = threading.RLock()


def new_id() -> str:
    """Server-minted UUID (no type prefix, per PRD §2.4)."""
    return str(uuid.uuid4())


_qr_seen = set()
_qr_lock = threading.Lock()


def new_qr() -> str:
    """Server-minted unique QR token."""
    alphabet = string.ascii_uppercase + string.digits
    while True:
        token = "QR_" + "".join(secrets.choice(alphabet) for _ in range(16))
        with _qr_lock:
            if token not in _qr_seen:
                _qr_seen.add(token)
                return token


# --- Tables ---
exhibitions: dict = {}
halls: dict = {}
floor_plans: dict = {}
booths: dict = {}
applications: dict = {}
allocations: dict = {}
dock_slots: dict = {}
safety_inspections: dict = {}
work_orders: dict = {}
tickets: dict = {}
entitlements: dict = {}
audit_logs: dict = {}


def reset_all():
    """For testing — drop everything."""
    with LOCK:
        for t in (
            exhibitions, halls, floor_plans, booths, applications, allocations,
            dock_slots, safety_inspections, work_orders, tickets, entitlements,
            audit_logs,
        ):
            t.clear()
        with _qr_lock:
            _qr_seen.clear()
