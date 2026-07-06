"""Existence resolution helpers (PRD 2.4). A missing id -> ERR_NOT_FOUND."""
from db import db
from errors import err


def get_or_404(collection, _id):
    rec = collection.get(_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource %s not found." % _id)
    return rec


def get_client(_id):
    return get_or_404(db.clients, _id)


def get_shopper(_id):
    return get_or_404(db.shoppers, _id)


def get_location(_id):
    return get_or_404(db.locations, _id)


def get_script(_id):
    return get_or_404(db.scripts, _id)


def get_wave(_id):
    return get_or_404(db.waves, _id)


def get_assignment(_id):
    return get_or_404(db.assignments, _id)


def get_evidence(_id):
    return get_or_404(db.evidence, _id)


def get_dispute(_id):
    return get_or_404(db.disputes, _id)


def get_payout_batch(_id):
    return get_or_404(db.payout_batches, _id)
