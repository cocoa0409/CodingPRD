"""In-memory data store. Starts empty on every boot — no seeding."""
import itertools
import uuid

store = {
    "clients": {},
    "studies": {},
    "arms": {},
    "time_points": {},
    "chambers": {},
    "sample_units": {},
    "panelists": {},
    "sessions": {},
    "assignments": {},
    "scores": {},
    "lab_results": {},
    "recommendations": {},
    "reports": {},
    "claims": {},
}

_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    """Global monotonically increasing insertion counter — stable tie-break
    for created_at ordering when the logical clock does not advance."""
    return next(_seq)
