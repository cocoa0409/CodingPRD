"""Existence lookups (PRD §2.5, validation priority 3): resolve ids left-to-right,
first miss -> ERR_NOT_FOUND."""
import db
from errors import err, ERR_NOT_FOUND


def get_customer(cid):
    c = db.customers.get(cid)
    if c is None:
        raise err(ERR_NOT_FOUND, "customer not found")
    return c


def get_invoice(iid):
    iv = db.invoices.get(iid)
    if iv is None:
        raise err(ERR_NOT_FOUND, "invoice not found")
    return iv


def get_payment(pid):
    p = db.payments.get(pid)
    if p is None:
        raise err(ERR_NOT_FOUND, "payment not found")
    return p


def get_application(aid):
    a = db.payment_applications.get(aid)
    if a is None:
        raise err(ERR_NOT_FOUND, "payment application not found")
    return a


def get_dispute(did):
    d = db.disputes.get(did)
    if d is None:
        raise err(ERR_NOT_FOUND, "dispute not found")
    return d


def get_promise(pid):
    p = db.promises.get(pid)
    if p is None:
        raise err(ERR_NOT_FOUND, "promise not found")
    return p


def get_writeoff(wid):
    w = db.write_offs.get(wid)
    if w is None:
        raise err(ERR_NOT_FOUND, "write-off not found")
    return w


def get_sequence(sid):
    s = db.dunning_sequences.get(sid)
    if s is None:
        raise err(ERR_NOT_FOUND, "dunning sequence not found")
    return s


def get_statement(sid):
    s = db.statements.get(sid)
    if s is None:
        raise err(ERR_NOT_FOUND, "statement not found")
    return s
