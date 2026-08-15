"""In-memory data store. Starts completely empty on every boot (per skill contract)."""
import uuid

# ---------------------------------------------------------------------------
# Entity tables: dict keyed by id, values are plain dicts (records).
# ---------------------------------------------------------------------------
terminals = {}
supply_contracts = {}
rail_shipments = {}
dealers = {}
dealer_contracts = {}
price_index_publications = {}
freight_zones = {}
trucks = {}
delivery_orders = {}
cold_snap_events = {}
allocation_runs = {}
dealer_payments = {}

# Monotonic per-request sequence to disambiguate created_at ordering when the
# logical clock is identical across records.
_seq_counter = [0]


def new_id():
    return str(uuid.uuid4())


def next_seq():
    _seq_counter[0] += 1
    return _seq_counter[0]
