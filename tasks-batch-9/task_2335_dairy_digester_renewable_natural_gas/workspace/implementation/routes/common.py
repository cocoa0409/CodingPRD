"""Path / body reference resolution (ladder ranks 3 and 4) and list plumbing."""
from flask import request

from db import db
from errors import fail
from response import listing
from validation import query_pagination

_LOOKUPS = (
    ("dairy", "dairies", "ERR_DAIRY_NOT_FOUND"),
    ("facility", "facilities", "ERR_FACILITY_NOT_FOUND"),
    ("agreement", "agreements", "ERR_AGREEMENT_NOT_FOUND"),
    ("delivery", "deliveries", "ERR_DELIVERY_NOT_FOUND"),
    ("ops_day", "ops_days", "ERR_OPS_DAY_NOT_FOUND"),
    ("interconnect", "interconnects", "ERR_INTERCONNECT_NOT_FOUND"),
    ("nomination", "nominations", "ERR_NOMINATION_NOT_FOUND"),
    ("pathway", "pathways", "ERR_PATHWAY_NOT_FOUND"),
    ("batch", "batches", "ERR_BATCH_NOT_FOUND"),
    ("audit", "audits", "ERR_AUDIT_NOT_FOUND"),
    ("application", "applications", "ERR_APPLICATION_NOT_FOUND"),
    ("statement", "statements", "ERR_STATEMENT_NOT_FOUND"),
)


def _make(collection_name, error_id):
    def getter(row_id):
        collection = getattr(db, collection_name)
        row = collection.get(row_id) if isinstance(row_id, str) else None
        if row is None:
            fail(error_id, "Referenced resource does not exist.")
        return row
    return getter


get_dairy = _make("dairies", "ERR_DAIRY_NOT_FOUND")
get_facility = _make("facilities", "ERR_FACILITY_NOT_FOUND")
get_agreement = _make("agreements", "ERR_AGREEMENT_NOT_FOUND")
get_delivery = _make("deliveries", "ERR_DELIVERY_NOT_FOUND")
get_ops_day = _make("ops_days", "ERR_OPS_DAY_NOT_FOUND")
get_interconnect = _make("interconnects", "ERR_INTERCONNECT_NOT_FOUND")
get_nomination = _make("nominations", "ERR_NOMINATION_NOT_FOUND")
get_pathway = _make("pathways", "ERR_PATHWAY_NOT_FOUND")
get_batch = _make("batches", "ERR_BATCH_NOT_FOUND")
get_audit = _make("audits", "ERR_AUDIT_NOT_FOUND")
get_application = _make("applications", "ERR_APPLICATION_NOT_FOUND")
get_statement = _make("statements", "ERR_STATEMENT_NOT_FOUND")


def resolve_refs(b, specs):
    """Resolve body foreign keys in declared order.

    Ladder rank 4 (referenced-entity 404) outranks rank 6 (schema 400), so a
    field that *is* a non-empty string is resolved first -- a bad id yields the
    entity's own 404 even when a later field is malformed.  Only once every
    present id has resolved do absent / non-string fields fall through to the
    generic ERR_INVALID_REQUEST.
    """
    resolved = []
    for field, getter in specs:
        value = b.raw.get(field)
        resolved.append(getter(value) if isinstance(value, str) and value else None)
    for index, (field, _getter) in enumerate(specs):
        if resolved[index] is None:
            b.ref(field)
    return tuple(resolved)


def paged_list(collection, serializer, filter_fields=()):
    """Default ordering is created_at ascending (PRD 2.3).  Filters are applied to
    the serialised view so that derived fields (a dairy's status, for instance)
    filter exactly as they read."""
    limit, offset = query_pagination(request.args)
    rows = list(collection.values())
    rows.sort(key=lambda r: (r["_created"], r["_seq"]))
    docs = [serializer(r) for r in rows]
    for field in filter_fields:
        wanted = request.args.get(field)
        if wanted is None or wanted == "":
            continue
        docs = [d for d in docs if d.get(field) is not None and str(d.get(field)) == wanted]
    total = len(docs)
    return listing(docs[offset:offset + limit], limit, offset, total)
