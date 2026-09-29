"""Small helpers shared by every route module."""
from __future__ import annotations

import envelope
import store as store_mod
from store import store


def respond(record, status=200):
    return envelope.ok(store_mod.serialize(record), status, store.now_iso())


def respond_raw(payload, status=200):
    return envelope.ok(payload, status, store.now_iso())


def respond_list(records, limit, offset):
    total = len(records)
    page = records[offset:offset + limit]
    return envelope.ok_list(
        [store_mod.serialize(r) for r in page], limit, offset, total, store.now_iso()
    )
