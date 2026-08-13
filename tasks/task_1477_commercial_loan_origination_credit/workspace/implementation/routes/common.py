"""Shared route helpers: path existence (pipeline stage 3) and list rendering."""
from errors import raise_err, ERR_NOT_FOUND, ERR_VALIDATION
from response import success_list
from validation import parse_pagination, paginate


def get_or_404(collection, resource_id, label="Resource"):
    entity = collection.get(resource_id)
    if entity is None:
        raise_err(ERR_NOT_FOUND, "%s '%s' does not exist." % (label, resource_id))
    return entity


def body_fk_exists(collection, fk_id, label):
    """Foreign keys carried in the request body must reference existing
    resources; a dangling reference is a body-schema failure (stage 4)."""
    if not isinstance(fk_id, str) or collection.get(fk_id) is None:
        raise_err(ERR_VALIDATION, "Field references a %s that does not exist." % label)


def render_list(items, serializer):
    """Sort by creation ascending (ties by insertion sequence) and paginate."""
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda e: (e['created_at'], e['_seq']))
    page, total = paginate(ordered, limit, offset)
    return success_list([serializer(e) for e in page], limit, offset, total)
