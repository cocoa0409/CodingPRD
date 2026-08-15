"""In-memory data store. Starts empty on every boot; no seeding."""
import itertools
import uuid

seasons = {}
categories = {}
entrants = {}
entries = {}
materials = {}
invoices = {}
judges = {}
declarations = {}
assignments = {}
rounds = {}
scores = {}
finalists = {}
ceremonies = {}
announcements = {}
fulfillment_orders = {}
appeals = {}
audit_logs = {}

_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())
