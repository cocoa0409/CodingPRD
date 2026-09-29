"""Small shared route helpers."""

from errors import ApiError


def find(coll, rec_id, error_id):
    """Resolve a path identifier or raise the endpoint's declared 404."""
    rec = coll.get(rec_id) if isinstance(rec_id, str) else None
    if rec is None:
        raise ApiError(error_id)
    return rec


def body_fk(data, key, coll, error_id):
    """Resolve a body foreign key.

    An absent or non-string value is left to rung 14 (`ERR_INVALID_REQUEST`);
    a present but unresolvable value raises the declared 404 of its rung.
    """
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    rec = coll.get(value)
    if rec is None:
        raise ApiError(error_id)
    return rec


def state_error(error_id, message=None):
    raise ApiError(error_id, message)
