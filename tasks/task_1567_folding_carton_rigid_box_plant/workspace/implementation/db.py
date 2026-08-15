"""In-memory data store. Starts empty on every boot; no seeding (per skill contract).

The plant logical clock starts at exactly 2026-08-01T00:00:00Z and never falls
back to wall-clock time (PRD §2.9).
"""

import threading

from util import new_id, now_iso, parse_dt

lock = threading.RLock()

_seq_counter = [0]


def next_seq():
    _seq_counter[0] += 1
    return _seq_counter[0]


def new_record():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


# Entity tables: id -> record dict
customers = {}
color_standards = {}
jobs = {}
design_revisions = {}
imposition_plans = {}
press_approvals = {}
presses = {}
press_bookings = {}
finishing_lines = {}
finishing_bookings = {}
board_stocks = {}
kit_orders = {}
retail_audits = {}
invoices = {}

# Plant logical clock (raw string echoed verbatim; dt used for comparisons)
clock = {
    "raw": "2026-08-01T00:00:00Z",
    "dt": parse_dt("2026-08-01T00:00:00Z"),
}
