"""In-memory data store. Starts EMPTY on every boot; no seeding of any kind."""
import itertools
import uuid

_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    """Monotonic insertion sequence for stable created_at tie-breaking."""
    return next(_seq)


territories = {}
technicians = {}
shifts = {}
crews = {}
calls = {}
incidents = {}
assignments = {}
pauses = {}
readings = {}
actions = {}
authorizations = {}
shutoffs = {}
determinations = {}
work_orders = {}
reports = {}
notifications = {}
