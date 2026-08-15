"""In-memory data store. The store starts empty on every boot — no seeding."""

import itertools

stores = {
    "gala_events": {},
    "donors": {},
    "bidders": {},
    "solicitations": {},
    "items": {},
    "valuations": {},
    "bundles": {},
    "bids": {},
    "invoices": {},
    "payments": {},
    "certificates": {},
    "blackout_windows": {},
    "dispositions": {},
    "acknowledgments": {},
}

_seq_counter = itertools.count(1)


def next_seq():
    return next(_seq_counter)
