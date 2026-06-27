"""In-memory data store.

The store starts EMPTY on every process boot. Nothing is seeded. Tests build
all preconditions through the declared API surface.

Common system fields (PRD 2.4):
  id          server-minted UUID, no type prefix
  created_at  ISO timestamp (stored as datetime, formatted on read)
  updated_at  refreshed on every mutation
  version     integer, starts at 1, +1 on each mutation

LoyaltyLedger is the sole exception (PRD 2.4): it carries only id and
created_at — no updated_at, no version — because it is an immutable audit
record.
"""
import threading
import uuid

import clock

# Each collection is an ordered dict keyed by id. Python 3.7+ preserves
# insertion order, which gives us created_at-ascending ordering for free as
# long as we never re-insert.
vendors = {}
products = {}
contractor_accounts = {}
sales_orders = {}
order_lines = {}
invoices = {}
rental_assets = {}
rental_agreements = {}
service_stations = {}
service_tickets = {}
special_orders = {}
purchase_orders = {}
loyalty_ledger = {}

# A single coarse lock makes each request handler atomic with respect to the
# others — important for the OCC / cascade / credit-pool invariants.
lock = threading.RLock()

# Monotonic creation sequence so list ordering is stable even if two records
# share the same logical/created timestamp.
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


def new_record(extra):
    """Create a record dict with common system fields populated.

    created_at/updated_at are taken from the logical clock so that temporal
    behaviour is deterministic and test-driven.
    """
    ts = clock.now()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    rec.update(extra)
    return rec


def touch(rec):
    """Mark a record as mutated: refresh updated_at, bump version."""
    rec["updated_at"] = clock.now()
    rec["version"] = rec.get("version", 1) + 1


def new_ledger_record(extra):
    """LoyaltyLedger record: only id + created_at (immutable audit record)."""
    rec = {
        "id": new_id(),
        "created_at": clock.now(),
        "_seq": next_seq(),
    }
    rec.update(extra)
    return rec


def reset():
    """Clear all collections. Used only by tests/boot; never seeds anything."""
    for coll in (
        vendors, products, contractor_accounts, sales_orders, order_lines,
        invoices, rental_assets, rental_agreements, service_stations,
        service_tickets, special_orders, purchase_orders, loyalty_ledger,
    ):
        coll.clear()
    global _seq
    _seq = 0
    clock.reset()
