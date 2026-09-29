"""Reference resolution helpers (PRD 2.7)."""

from errors import ApiError


def path_ref(table, rec_id, error_id):
    """Resolve an identifier taken from the request path."""
    rec = table.get(rec_id)
    if rec is None:
        raise ApiError(error_id)
    return rec


def body_ref(data, name, table, error_id):
    """Resolve a foreign key carried in the request body.

    An absent or non-string value is left to payload validation (step 6),
    which is the only step that may report a shape defect.
    """
    if not isinstance(data, dict):
        return None
    value = data.get(name)
    if not isinstance(value, str) or value == "":
        return None
    rec = table.get(value)
    if rec is None:
        raise ApiError(error_id)
    return rec
