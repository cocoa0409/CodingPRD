"""In-memory data store. Plain dicts keyed by id; the store starts completely
empty on every boot — nothing is seeded, preloaded, or persisted anywhere."""
import itertools
import uuid

STORE = {
    "customers": {},
    "yards": {},
    "access_profiles": {},
    "plans": {},
    "addons": {},
    "subscriptions": {},
    "routes": {},
    "technicians": {},
    "vacation_windows": {},
    "visits": {},
    "invoices": {},
    "line_items": {},
    "reports": {},
}

_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())
