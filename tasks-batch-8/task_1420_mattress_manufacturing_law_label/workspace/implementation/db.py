"""In-memory data store. The store starts EMPTY on every boot — no seeding."""
import itertools
import uuid

retailers = {}
credit_adjustments = {}
models = {}
bom_lines = {}
certificates = {}
specs = {}
law_labels = {}
foam_batches = {}
quilt_runs = {}
orders = {}
units = {}
shipments = {}
returns = {}
claims = {}
intakes = {}

# Sequential counters used for mattress-unit serial numbers:
# "<order_seq>-0001" where order_seq is the creation sequence of the order.
order_seq = itertools.count(1)

# Global insertion sequence. The logical clock can stay frozen across many
# creations, so created_at ties are broken by this monotonic counter to keep
# "sorted by created_at ascending" deterministic.
seq_counter = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def put(store, record):
    record["_seq"] = next(seq_counter)
    store[record["id"]] = record
    return record
