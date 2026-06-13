"""Entity -> public JSON projection. Strips internal fields (those prefixed _)."""


def _public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def matter_out(m):
    return _public(m)


def custodian_out(c):
    return _public(c)


def legal_hold_out(h):
    return _public(h)


def hold_ack_out(a):
    return _public(a)


def collection_scope_out(s):
    return _public(s)


def document_out(d):
    return _public(d)


def processing_job_out(j):
    return _public(j)


def review_batch_out(b):
    return _public(b)


def document_review_out(r):
    return _public(r)


def production_set_out(p):
    return _public(p)


def production_item_out(i):
    return _public(i)


def clawback_out(c):
    return _public(c)
