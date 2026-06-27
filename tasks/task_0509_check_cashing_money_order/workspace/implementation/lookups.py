"""Existence resolution helpers (PRD §2.5). Each returns the entity or raises
ERR_NOT_FOUND. Path identifiers are validated left to right by calling these in
path order."""
import errors
from db import db


def get_customer(cid):
    c = db.customers.get(cid)
    if c is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Customer not found")
    return c


def get_fee_schedule(fid):
    f = db.fee_schedules.get(fid)
    if f is None:
        raise errors.err(errors.ERR_NOT_FOUND, "FeeSchedule not found")
    return f


def get_drawer(did):
    d = db.cash_drawers.get(did)
    if d is None:
        raise errors.err(errors.ERR_NOT_FOUND, "CashDrawer not found")
    return d


def get_transaction(tid):
    t = db.transactions.get(tid)
    if t is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Transaction not found")
    return t


def get_check_item(cid):
    c = db.check_items.get(cid)
    if c is None:
        raise errors.err(errors.ERR_NOT_FOUND, "CheckItem not found")
    return c


def get_returned_item(rid):
    r = db.returned_items.get(rid)
    if r is None:
        raise errors.err(errors.ERR_NOT_FOUND, "ReturnedItem not found")
    return r
