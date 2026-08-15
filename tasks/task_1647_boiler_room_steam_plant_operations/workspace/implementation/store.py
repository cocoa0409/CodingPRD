"""In-memory data store. Starts empty on every boot; nothing is ever seeded."""
import itertools
import uuid

plants = {}
boilers = {}
operators = {}
log_entries = {}
chemistry_logs = {}
inspections = {}
steam_traps = {}
dispatches = {}
incidents = {}
fuel_deliveries = {}

_seq = itertools.count(1)     # insertion order (created_at tie-break)
_event = itertools.count(1)   # causal event order (trip/suspension/outcome)


def next_seq():
    return next(_seq)


def next_event():
    return next(_event)


def new_id():
    return str(uuid.uuid4())
