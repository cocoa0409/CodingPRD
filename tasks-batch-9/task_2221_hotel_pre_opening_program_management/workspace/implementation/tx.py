"""Per-request version/updated_at bookkeeping."""
from flask import g

import db


def begin():
    g.tx_key = object()
    db.begin(g.tx_key)


def commit(*force_ids):
    key = getattr(g, "tx_key", None)
    if key is None:
        return
    db.finish(key, [i for i in force_ids if i])
    g.tx_key = None


def discard():
    key = getattr(g, "tx_key", None)
    if key is not None:
        db.discard(key)
        g.tx_key = None
