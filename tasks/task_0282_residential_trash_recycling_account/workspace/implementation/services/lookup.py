"""Path-id existence (ERR_NOT_FOUND) and body-FK existence (ERR_REFERENCE_NOT_FOUND).

PRD §2.5: path-identifier existence and body-reference existence are distinct
concerns with distinct error identifiers.
"""
import db
from errors import err


def get_or_404(store, rid):
    rec = store.get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource not found.")
    return rec


def ref_or_404(store, rid):
    rec = store.get(rid)
    if rec is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "Referenced resource not found.")
    return rec
