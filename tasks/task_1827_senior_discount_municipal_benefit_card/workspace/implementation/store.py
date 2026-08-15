"""In-memory data store. Starts empty on every boot; no seeding."""
import itertools
import uuid

applications = {}
documents = {}
cardholders = {}
cards = {}
merchants = {}
offers = {}
waivers = {}
transactions = {}
claims = {}
funds = {}

_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())
