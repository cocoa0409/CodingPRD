"""Small route-level helpers shared by every blueprint."""
import response
import validation
from errors import fail


def fetch(collection, key, error_id):
    """Resolve an identifier or raise the entity's not-found code (PRD 2.5).

    A value that is not a well-formed UUID simply names nothing and therefore
    yields the same not-found code rather than ERR_VALIDATION.
    """
    record = collection.get(key)
    if record is None:
        fail(error_id)
    return record


def page(records, serializer, limit, offset):
    items, total = validation.paginate(list(records), limit, offset)
    return response.ok_list([serializer(item) for item in items], limit, offset, total)


def matches(record, filters):
    for field, wanted in filters.items():
        if wanted is None:
            continue
        if record.get(field) != wanted:
            return False
    return True


def filtered(records, filters):
    return [r for r in records if matches(r, filters)]


def blank(text):
    return text is None or not str(text).strip()
