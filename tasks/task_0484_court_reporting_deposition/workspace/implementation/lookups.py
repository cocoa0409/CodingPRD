"""Existence lookups with left-to-right ordering (PRD §2.5)."""
from db import db
from errors import err, ERR_NOT_FOUND


def get_case(cid):
    e = db.cases.get(cid)
    if e is None:
        raise err(ERR_NOT_FOUND, "Case not found.")
    return e


def get_attorney(aid):
    e = db.attorneys.get(aid)
    if e is None:
        raise err(ERR_NOT_FOUND, "Attorney not found.")
    return e


def get_resource(rid):
    e = db.resources.get(rid)
    if e is None:
        raise err(ERR_NOT_FOUND, "Resource not found.")
    return e


def get_job(jid):
    e = db.jobs.get(jid)
    if e is None:
        raise err(ERR_NOT_FOUND, "Job not found.")
    return e


def get_assignment(aid):
    e = db.assignments.get(aid)
    if e is None:
        raise err(ERR_NOT_FOUND, "Assignment not found.")
    return e


def get_stream(sid):
    e = db.realtime_streams.get(sid)
    if e is None:
        raise err(ERR_NOT_FOUND, "Realtime stream not found.")
    return e


def get_transcript(tid):
    e = db.transcript_orders.get(tid)
    if e is None:
        raise err(ERR_NOT_FOUND, "Transcript order not found.")
    return e


def get_exhibit(eid):
    e = db.exhibits.get(eid)
    if e is None:
        raise err(ERR_NOT_FOUND, "Exhibit not found.")
    return e


def get_errata(eid):
    e = db.errata.get(eid)
    if e is None:
        raise err(ERR_NOT_FOUND, "Errata not found.")
    return e


def get_invoice(iid):
    e = db.invoices.get(iid)
    if e is None:
        raise err(ERR_NOT_FOUND, "Invoice not found.")
    return e
