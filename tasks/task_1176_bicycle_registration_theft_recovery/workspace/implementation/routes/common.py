"""Shared per-request validation helpers (PRD §2.6 stage 4) and loaders (stage 5)."""
from errors import fail
from util import parse_dt, valid_photo_hash

ABSENT = object()


def field(data, name, kind, required=False, nullable=False, enum=None,
          min_value=None, photo_hash=False):
    """Validate a single body field. Returns the value, None (absent optional),
    or ABSENT marker never — absent optional returns None."""
    if name not in data:
        if required:
            fail("ERR_INVALID_REQUEST", f"Missing required field: {name}")
        return None
    val = data[name]
    if val is None:
        if nullable and not required:
            return None
        if required and nullable:
            return None
        if required:
            fail("ERR_INVALID_REQUEST", f"Field {name} must not be null")
        return None
    if kind == "string":
        if not isinstance(val, str):
            fail("ERR_INVALID_REQUEST", f"Field {name} must be a string")
        if photo_hash and not valid_photo_hash(val):
            fail("ERR_INVALID_REQUEST", f"Field {name} must be 16 lowercase hex chars")
    elif kind == "integer":
        if not isinstance(val, int) or isinstance(val, bool):
            fail("ERR_INVALID_REQUEST", f"Field {name} must be an integer")
        if min_value is not None and val < min_value:
            fail("ERR_INVALID_REQUEST", f"Field {name} must be >= {min_value}")
    elif kind == "boolean":
        if not isinstance(val, bool):
            fail("ERR_INVALID_REQUEST", f"Field {name} must be a boolean")
    elif kind == "datetime":
        if not isinstance(val, str):
            fail("ERR_INVALID_REQUEST", f"Field {name} must be an ISO-8601 string")
        try:
            val = parse_dt(val)
        except (ValueError, TypeError):
            fail("ERR_INVALID_REQUEST", f"Field {name} must be a valid ISO-8601 datetime")
    if enum is not None and val not in enum:
        fail("ERR_INVALID_REQUEST", f"Field {name} must be one of {sorted(enum)}")
    return val


def load(table, rec_id, error_id):
    rec = table.get(rec_id)
    if rec is None:
        fail(error_id, f"Resource {rec_id} not found")
    return rec
