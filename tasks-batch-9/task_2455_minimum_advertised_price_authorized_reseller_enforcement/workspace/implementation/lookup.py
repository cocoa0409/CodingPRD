"""Existence lookups (PRD §2.9 steps 4-5) and list filtering helpers."""

from flask import request

from errors import fail
from store import store

NOT_FOUND = {
    "policies": "ERR_POLICY_NOT_FOUND",
    "products": "ERR_PRODUCT_NOT_FOUND",
    "resellers": "ERR_RESELLER_NOT_FOUND",
    "distributors": "ERR_DISTRIBUTOR_NOT_FOUND",
    "agreements": "ERR_AGREEMENT_NOT_FOUND",
    "observations": "ERR_OBSERVATION_NOT_FOUND",
    "violations": "ERR_VIOLATION_NOT_FOUND",
    "notices": "ERR_NOTICE_NOT_FOUND",
    "exceptions": "ERR_EXCEPTION_NOT_FOUND",
    "serial_units": "ERR_SERIAL_UNIT_NOT_FOUND",
    "test_purchases": "ERR_TEST_PURCHASE_NOT_FOUND",
    "chargebacks": "ERR_CHARGEBACK_NOT_FOUND",
}


def find(collection_name, row_id, error_id=None):
    collection = getattr(store, collection_name)
    row = collection.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        fail(error_id or NOT_FOUND[collection_name])
    return row


def policy(row_id):
    return find("policies", row_id)


def product(row_id):
    return find("products", row_id)


def reseller(row_id):
    return find("resellers", row_id)


def distributor(row_id):
    return find("distributors", row_id)


def agreement(row_id):
    return find("agreements", row_id)


def observation(row_id):
    return find("observations", row_id)


def violation(row_id):
    return find("violations", row_id)


def notice(row_id):
    return find("notices", row_id)


def exception(row_id):
    return find("exceptions", row_id)


def serial_unit(row_id):
    return find("serial_units", row_id)


def test_purchase(row_id):
    return find("test_purchases", row_id)


def chargeback(row_id):
    return find("chargebacks", row_id)


def filtered(collection_name, fields):
    """Conjunctive equality filters read from the query string (PRD §2.3)."""
    rows = list(getattr(store, collection_name).values())
    for param, field in fields.items():
        raw = request.args.get(param)
        if raw is None:
            continue
        rows = [r for r in rows if _matches(r.get(field), raw)]
    return rows


def _matches(value, raw):
    if isinstance(value, bool):
        lowered = raw.strip().lower()
        if lowered in ("true", "1"):
            return value is True
        if lowered in ("false", "0"):
            return value is False
        return False
    if value is None:
        return False
    return str(value) == raw
