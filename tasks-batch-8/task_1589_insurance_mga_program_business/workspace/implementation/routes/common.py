"""Shared route helpers: path existence (pipeline stage 3) and list rendering."""
from db import STORE
from errors import raise_err, ERR_NOT_FOUND
from response import success_list
from validation import parse_pagination, paginate


def get_or_404(collection, resource_id, label="Resource"):
    entity = collection.get(resource_id)
    if entity is None:
        raise_err(ERR_NOT_FOUND, "%s '%s' does not exist." % (label, resource_id))
    return entity


def program_of(child):
    return STORE.programs[child["program_id"]]


def render_list(items, serializer):
    """Sort by creation timestamp ascending (ties by insertion sequence) and
    paginate with limit/offset."""
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    page, total = paginate(ordered, limit, offset)
    return success_list([serializer(e) for e in page], limit, offset, total)


def filter_query(items, **filters):
    """Equality filters from query params; a None value means 'not supplied'."""
    out = []
    for e in items:
        ok = True
        for field, value in filters.items():
            if value is not None and e.get(field) != value:
                ok = False
                break
        if ok:
            out.append(e)
    return out
