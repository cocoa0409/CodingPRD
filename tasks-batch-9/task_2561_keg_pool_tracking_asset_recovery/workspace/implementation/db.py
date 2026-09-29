"""In-memory data store.

Every collection starts empty on every boot.  Nothing is ever seeded: each
entity the tests need is created through the declared API surface.
"""

brewers = {}
distributors = {}
pools = {}
kegs = {}
scan_events = {}
agreements = {}
orders = {}
service_centers = {}
service_cycles = {}
assessments = {}
claims = {}
accruals = {}
investigations = {}
commodity_index = {}

_ALL = [
    brewers, distributors, pools, kegs, scan_events, agreements, orders,
    service_centers, service_cycles, assessments, claims, accruals,
    investigations, commodity_index,
]


def reset():
    for coll in _ALL:
        coll.clear()
