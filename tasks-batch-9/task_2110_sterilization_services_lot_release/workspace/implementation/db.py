"""In-memory store.  Every dict starts empty on every boot: the implementation
encodes the system only, never any seed data."""

import itertools
import uuid

_seq_counter = itertools.count(1)


class Store(object):
    def __init__(self):
        self.customers = {}
        self.products = {}
        self.permits = {}
        self.chambers = {}
        self.recipes = {}
        self.qualifications = {}
        self.dose_audits = {}
        self.lots = {}
        self.cycles = {}
        self.load_positions = {}
        self.indicators = {}
        self.aeration_records = {}
        self.adverse_events = {}


db = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq_counter)
