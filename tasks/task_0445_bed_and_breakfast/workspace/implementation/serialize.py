"""Public JSON serialization for each entity.

Strips internal bookkeeping keys (leading underscore) and exposes the exact field
set the PRD/scaffold declare. Bookings carry the full computed money ladder, which
is stored on the row and refreshed at create/confirm/payment time.
"""

# Internal keys we never expose.
_INTERNAL_PREFIX = "_"


def _public(row):
    return {k: v for k, v in row.items() if not k.startswith(_INTERNAL_PREFIX)}


def inn(row):
    return _public(row)


def room(row):
    return _public(row)


def rate_period(row):
    return _public(row)


def package(row):
    return _public(row)


def guest(row):
    return _public(row)


def gift_certificate(row):
    return _public(row)


def booking(row):
    return _public(row)


def breakfast_plan(row):
    return _public(row)


def ledger_entry(row):
    return _public(row)


def housekeeping_task(row):
    return _public(row)


def tax_remittance(row):
    return _public(row)
