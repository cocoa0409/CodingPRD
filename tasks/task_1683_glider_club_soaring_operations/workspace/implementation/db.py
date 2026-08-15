"""In-memory data store and logical clock.

State lives only in module-level dicts keyed by id. The process restart that
`start.sh` performs before every test wipes everything; nothing is persisted.
"""

from datetime import datetime, timezone

# Logical clock: before any call it reads exactly 2026-08-01T00:00:00Z.
CLOCK = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}

# Entity stores: id -> record dict.
STORE = {
    "tiers": {},
    "members": {},
    "aircraft": {},
    "duty_slots": {},
    "availability": {},
    "reservations": {},
    "flights": {},
    "tow_slots": {},
    "maintenance": {},
    "progress": {},
    "retrieves": {},
}

# Insertion sequence for stable created_at ordering.
SEQ = {"n": 0}

# UTC calendar months ("YYYY-MM") for which dues have already been posted.
POSTED_MONTHS = set()


def next_seq():
    SEQ["n"] += 1
    return SEQ["n"]


def now():
    return CLOCK["now"]


def today_start():
    n = CLOCK["now"]
    return n.replace(hour=0, minute=0, second=0, microsecond=0)
