"""In-memory data store.

Every collection starts EMPTY on every boot.  Nothing is seeded, preloaded or
hardcoded here: all rows are created by callers through the declared endpoints.
"""

from datetime import datetime, timezone

# --- entity collections (keyed by id) ---------------------------------------
speakers = {}
clients = {}
inquiries = {}
proposals = {}
options = {}
engagements = {}
contracts = {}
holds = {}
grants = {}
expenses = {}
invoices = {}
remittances = {}
feedbacks = {}
claims = {}

# --- monotonic insertion sequence -------------------------------------------
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


# --- logical clock ----------------------------------------------------------
# PRD §2.5: the value at startup is exactly 2026-08-01T00:00:00Z and wall clock
# time is never consulted for any temporal rule.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
clock = {"now": CLOCK_DEFAULT}


def now_utc():
    return clock["now"]


def set_now_utc(dt):
    clock["now"] = dt
