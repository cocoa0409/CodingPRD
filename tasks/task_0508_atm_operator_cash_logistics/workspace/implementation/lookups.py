"""Existence resolution (priority 3 — ERR_NOT_FOUND).

Path ids validate left-to-right; the first that fails to resolve raises
ERR_NOT_FOUND. Body FKs validate after the path. Existence runs after auth +
role but before body validation and business rules (PRD §2.6).
"""
from errors import err


def _get_or_404(collection, _id):
    ent = collection.get(_id)
    if ent is None:
        raise err("ERR_NOT_FOUND", "Resource %s was not found." % _id)
    return ent


def site_merchant(store, _id):
    return _get_or_404(store.site_merchants, _id)


def vault(store, _id):
    return _get_or_404(store.vaults, _id)


def route(store, _id):
    return _get_or_404(store.routes, _id)


def location(store, _id):
    return _get_or_404(store.locations, _id)


def atm(store, _id):
    return _get_or_404(store.atms, _id)


def cassette(store, _id):
    return _get_or_404(store.cassettes, _id)


def replenishment_order(store, _id):
    return _get_or_404(store.replenishment_orders, _id)


def transaction(store, _id):
    return _get_or_404(store.transactions, _id)


def cash_count(store, _id):
    return _get_or_404(store.cash_counts, _id)


def service_ticket(store, _id):
    return _get_or_404(store.service_tickets, _id)


def settlement_run(store, _id):
    return _get_or_404(store.settlement_runs, _id)


def commission_statement(store, _id):
    return _get_or_404(store.commission_statements, _id)


def fee_disclosure(store, _id):
    return _get_or_404(store.fee_disclosures, _id)
