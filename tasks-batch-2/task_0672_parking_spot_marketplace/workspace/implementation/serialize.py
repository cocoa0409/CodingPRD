"""Public serialization of entity records.

Drives derived/computed fields onto the wire representation and strips internal
bookkeeping fields (those prefixed with '_').
"""


def _public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def host_view(rec):
    return _public(rec)


def driver_view(rec):
    return _public(rec)


def spot_view(rec):
    return _public(rec)


def pricing_event_view(rec):
    return _public(rec)


def booking_view(rec):
    return _public(rec)


def access_pass_view(rec):
    return _public(rec)


def violation_view(rec):
    return _public(rec)


def ledger_entry_view(rec):
    return _public(rec)


def transfer_offer_view(rec):
    return _public(rec)
