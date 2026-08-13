"""In-memory data store. Starts empty on every boot; no seeding."""
import itertools
import uuid

borrowers = {}
loans = {}
applications = {}
documents = {}
programs = {}
evaluations = {}
steps = {}
plans = {}
payments = {}
modifications = {}
notices = {}
appeals = {}
cases = {}
analyses = {}

_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())
