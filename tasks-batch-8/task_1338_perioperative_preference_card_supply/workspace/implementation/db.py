"""In-memory data store. The store starts empty on every boot; nothing is
seeded at startup. All state lives in module-level dicts keyed by id."""

import itertools
import uuid

_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


surgeons = {}
supply_items = {}
preference_cards = {}
card_lines = {}
cases = {}
pick_lists = {}
pick_list_lines = {}
usage_records = {}
audits = {}
product_requests = {}
consignment_counts = {}
consignment_charges = {}
