"""In-memory data store.

Every collection starts empty on process boot. Nothing is seeded here — tests
build all preconditions via the declared API surface.
"""

import uuid
from datetime import datetime, timezone


# Server logical UTC clock. Default per PRD §3.9 / scaffold: 2026-03-01T00:00:00Z.
LOGICAL_CLOCK_DEFAULT = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
current_utc: datetime = LOGICAL_CLOCK_DEFAULT


def get_now() -> datetime:
    return current_utc


def set_now(dt: datetime):
    global current_utc
    current_utc = dt


# Entity stores keyed by id
customers: dict = {}
designers: dict = {}
paper_stocks: dict = {}
finish_options: dict = {}
event_packages: dict = {}
designs: dict = {}
proofs: dict = {}
orders: dict = {}
line_items: dict = {}
addressing_jobs: dict = {}
work_orders: dict = {}
shipments: dict = {}


def new_id() -> str:
    return str(uuid.uuid4())


def iso_now() -> str:
    return format_iso(get_now())


def format_iso(dt: datetime) -> str:
    # ISO 8601 UTC with three fractional digits, e.g. 2025-05-24T10:30:00.123Z
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def parse_iso(s: str) -> datetime:
    """Parse ISO 8601 UTC timestamp (accepts trailing Z)."""
    if not isinstance(s, str):
        raise ValueError("timestamp must be a string")
    st = s.strip()
    if st.endswith("Z"):
        st = st[:-1] + "+00:00"
    dt = datetime.fromisoformat(st)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def reset_all():
    """Clear all in-memory state (used only if called explicitly; not on boot)."""
    global current_utc
    customers.clear()
    designers.clear()
    paper_stocks.clear()
    finish_options.clear()
    event_packages.clear()
    designs.clear()
    proofs.clear()
    orders.clear()
    line_items.clear()
    addressing_jobs.clear()
    work_orders.clear()
    shipments.clear()
    current_utc = LOGICAL_CLOCK_DEFAULT
