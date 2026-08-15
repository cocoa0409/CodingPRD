"""In-memory data store. Starts completely empty on every boot; no seeding."""
import itertools
import uuid

from timeutil import now as _now

_seq = itertools.count(1)

# Entity tables: dicts keyed by id.
vendors = {}
audits = {}
packages = {}
rules = {}
matrices = {}
positions = {}
candidates = {}
orders = {}
consents = {}
reports = {}
findings = {}
assessments = {}
cases = {}
disputes = {}


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


def new_entity(fields=None):
    """Common field set: id, created_at, updated_at, version (+internal _seq)."""
    t = _now()
    ent = {
        "id": new_id(),
        "created_at": t,
        "updated_at": t,
        "version": 1,
        "_seq": next_seq(),
    }
    if fields:
        ent.update(fields)
    return ent


def bump(ent):
    """Every mutation refreshes updated_at and increments version."""
    ent["updated_at"] = _now()
    ent["version"] += 1
