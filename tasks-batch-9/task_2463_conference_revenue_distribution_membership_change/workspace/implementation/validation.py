"""Request-shape validation (PRD section 2.8, ERR_INVALID_REQUEST).

Every required field must be present, every enumerated value must be one the
specification declares, every amount field named in cents and every count must
be a non-negative integer, and every instant must parse as an ISO 8601 UTC
timestamp.
"""

from datetime import datetime, timezone

from errors import ApiError

_MISSING = object()


def invalid(field=None):
    if field:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is missing or invalid." % field)
    raise ApiError("ERR_INVALID_REQUEST")


def _present(body, field):
    return field in body and body[field] is not None


def get_str(body, field, required=True, default=None, allow_empty=False):
    if not _present(body, field):
        if required:
            invalid(field)
        return default
    value = body[field]
    if not isinstance(value, str):
        invalid(field)
    if not allow_empty and value.strip() == "":
        invalid(field)
    return value


def get_optional_str(body, field, default=None, allow_empty=True):
    """Optional free-text field; an explicit null clears it."""
    if field not in body:
        return default
    value = body[field]
    if value is None:
        return None
    if not isinstance(value, str):
        invalid(field)
    if not allow_empty and value.strip() == "":
        invalid(field)
    return value


def get_int(body, field, required=True, default=None, minimum=0, maximum=None):
    if not _present(body, field):
        if required:
            invalid(field)
        return default
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, int):
        invalid(field)
    if minimum is not None and value < minimum:
        invalid(field)
    if maximum is not None and value > maximum:
        invalid(field)
    return value


def get_bool(body, field, required=True, default=None):
    if not _present(body, field):
        if required:
            invalid(field)
        return default
    value = body[field]
    if not isinstance(value, bool):
        invalid(field)
    return value


def get_enum(body, field, allowed, required=True, default=None):
    if not _present(body, field):
        if required:
            invalid(field)
        return default
    value = body[field]
    if not isinstance(value, str) or value not in allowed:
        invalid(field)
    return value


def parse_instant(raw, field="timestamp"):
    if not isinstance(raw, str) or raw.strip() == "":
        invalid(field)
    text = raw.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        invalid(field)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def get_instant(body, field, required=True, default=None):
    if not _present(body, field):
        if required:
            invalid(field)
        return default
    return parse_instant(body[field], field)


def get_id(body, field, required=True, default=None):
    """A foreign-key reference: a non-empty string."""
    if not _present(body, field):
        if required:
            invalid(field)
        return default
    value = body[field]
    if not isinstance(value, str) or value.strip() == "":
        invalid(field)
    return value


def get_nullable_id(body, field, default=None):
    """Optional foreign key where an explicit null means "no reference"."""
    if field not in body:
        return default
    value = body[field]
    if value is None:
        return None
    if not isinstance(value, str) or value.strip() == "":
        invalid(field)
    return value
