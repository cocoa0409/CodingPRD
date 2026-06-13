"""Existence lookups; raise ERR_RESOURCE_NOT_FOUND (404) when missing."""
import db
import errors


def _get(store, rid):
    obj = store.get(rid)
    if obj is None:
        errors.fail(errors.ERR_RESOURCE_NOT_FOUND, "Resource not found.")
    return obj


def get_fund(rid):
    return _get(db.funds, rid)


def get_lp(rid):
    return _get(db.limited_partners, rid)


def get_commitment(rid):
    return _get(db.commitments, rid)


def get_capital_call(rid):
    return _get(db.capital_calls, rid)


def get_allocation(rid):
    return _get(db.capital_call_allocations, rid)


def get_portfolio_company(rid):
    return _get(db.portfolio_companies, rid)


def get_investment(rid):
    return _get(db.investments, rid)


def get_valuation_mark(rid):
    return _get(db.valuation_marks, rid)


def get_fee_accrual(rid):
    return _get(db.management_fee_accruals, rid)


def get_distribution_event(rid):
    return _get(db.distribution_events, rid)


def get_distribution_allocation(rid):
    return _get(db.distribution_allocations, rid)


def get_side_letter(rid):
    return _get(db.side_letters, rid)
