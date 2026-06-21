"""Existence lookups that raise ERR_NOT_FOUND. PRD §2.5."""
from db import db
from errors import err


def _get_or_404(store, rid):
    rec = store.get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return rec


def covered_entity(rid):
    return _get_or_404(db.covered_entities, rid)


def child_site(rid):
    return _get_or_404(db.child_sites, rid)


def prescriber(rid):
    return _get_or_404(db.prescribers, rid)


def patient(rid):
    return _get_or_404(db.patients, rid)


def drug_product(rid):
    return _get_or_404(db.drug_products, rid)


def ceiling_price(rid):
    return _get_or_404(db.ceiling_prices, rid)


def contract_pharmacy(rid):
    return _get_or_404(db.contract_pharmacies, rid)


def accumulator(rid):
    return _get_or_404(db.accumulators, rid)


def dispense(rid):
    return _get_or_404(db.dispenses, rid)


def audit_finding(rid):
    return _get_or_404(db.audit_findings, rid)


def repayment_obligation(rid):
    return _get_or_404(db.repayment_obligations, rid)


def purchase_order(rid):
    return _get_or_404(db.purchase_orders, rid)


def sorted_by_created(items):
    """Default list sort: created_at ASC, tie-broken by insertion sequence."""
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
