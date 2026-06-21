"""Existence lookups and helpers shared across routes."""
from db import db
from errors import err, ERR_NOT_FOUND
from models import sort_by_created


def get_or_404(collection, rec_id):
    rec = collection.get(rec_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "resource not found")
    return rec


def get_catalog_or_404(cid):
    return get_or_404(db.catalogs, cid)


def get_device_model_or_404(mid):
    return get_or_404(db.device_models, mid)


def get_customer_or_404(cid):
    return get_or_404(db.customers, cid)


def get_trade_in_or_404(tid):
    return get_or_404(db.trade_ins, tid)


def quotes_for(trade_in_id):
    return sort_by_created([q for q in db.quotes.values()
                            if q["trade_in_id"] == trade_in_id])


def locked_quote_of(trade_in):
    """The Quote currently in LOCKED status for this trade-in (PRD 2.5),
    discovered by walking the trade-in's quotes rather than trusting the
    denormalized pointer in isolation."""
    for q in quotes_for(trade_in["id"]):
        if q["status"] == "LOCKED":
            return q
    return None


def shipping_kits_for(trade_in_id):
    return sort_by_created([k for k in db.shipping_kits.values()
                            if k["trade_in_id"] == trade_in_id])


def inspections_for(trade_in_id):
    return sort_by_created([i for i in db.inspections.values()
                            if i["trade_in_id"] == trade_in_id])


def payouts_for(trade_in_id):
    return sort_by_created([p for p in db.payouts.values()
                            if p["trade_in_id"] == trade_in_id])


def data_wipe_certs_for(trade_in_id):
    return sort_by_created([c for c in db.data_wipe_certificates.values()
                            if c["trade_in_id"] == trade_in_id])


def disposition_records_for(trade_in_id):
    return sort_by_created([d for d in db.disposition_records.values()
                            if d["trade_in_id"] == trade_in_id])
