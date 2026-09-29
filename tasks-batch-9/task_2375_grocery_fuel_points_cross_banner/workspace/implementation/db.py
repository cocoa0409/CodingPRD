"""In-memory data store. Starts EMPTY on every boot — nothing is ever seeded."""
import itertools
import uuid

_seq = itertools.count(1)

banners = {}
sites = {}
households = {}
members = {}
household_links = {}
promo_events = {}
point_cycles = {}
purchase_transactions = {}
ledger_entries = {}
fuel_redemptions = {}
settlement_batches = {}
point_disputes = {}
fraud_signals = {}


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)
