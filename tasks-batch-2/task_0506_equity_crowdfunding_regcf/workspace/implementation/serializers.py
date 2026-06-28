"""Output projections for each entity.

Strips internal bookkeeping fields (those prefixed with '_') so only the public
contract surface is returned.
"""


def _public(record):
    return {k: v for k, v in record.items() if not k.startswith("_")}


def issuer_out(r):
    return _public(r)


def offering_out(r):
    return _public(r)


def investor_out(r):
    return _public(r)


def accreditation_request_out(r):
    return _public(r)


def investment_out(r):
    return _public(r)


def escrow_out(r):
    return _public(r)


def cap_table_entry_out(r):
    return _public(r)


def investor_update_out(r):
    return _public(r)
