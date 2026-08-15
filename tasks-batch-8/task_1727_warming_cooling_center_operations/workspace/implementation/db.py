"""In-memory data store. Starts empty on every boot — no seeding."""
import itertools
import uuid

store = {
    "episodes": {},
    "readings": {},
    "sites": {},
    "activations": {},
    "staff": {},
    "shifts": {},
    "guests": {},
    "stays": {},
    "vehicles": {},
    "dispatches": {},
    "donations": {},
    "meal_services": {},
    "incidents": {},
    "aars": {},
}

_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    """Global monotonically increasing insertion counter — used as a stable
    tie-break wherever created_at ordering is required."""
    return next(_seq)
