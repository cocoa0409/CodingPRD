"""Body/field validation helpers (ladder rungs 5, 6 and 7)."""

from flask import request

from errors import ApiError
from store import NOT_FOUND_ERRORS, db, parse_iso


def invalid(detail=None):
    raise ApiError("ERR_INVALID_REQUEST", detail)


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        invalid("Request body must be a JSON object.")
    return data


# ------------------------------------------------------------------- existence

def path_row(collection, row_id):
    row = getattr(db, collection).get(row_id)
    if row is None:
        raise ApiError(NOT_FOUND_ERRORS[collection])
    return row


def fk(collection, data, field, required=True):
    """Rung 6: resolve a body foreign key in declaration order.

    A value that is absent or of the wrong type is left to rung 7.
    """
    if field not in data or data.get(field) is None:
        return None
    value = data.get(field)
    if not isinstance(value, str):
        return None
    row = getattr(db, collection).get(value)
    if row is None:
        raise ApiError(NOT_FOUND_ERRORS[collection])
    return row


# ------------------------------------------------------------------ scalars

_MISSING = object()


def _present(data, field, required):
    if field not in data or data.get(field) is None:
        if required:
            invalid("Field '%s' is required." % field)
        return False
    return True


def str_field(data, field, minimum=1, maximum=None, required=True, default=None):
    if not _present(data, field, required):
        return default
    value = data.get(field)
    if not isinstance(value, str):
        invalid("Field '%s' must be a string." % field)
    if minimum is not None and len(value) < minimum:
        invalid("Field '%s' is too short." % field)
    if maximum is not None and len(value) > maximum:
        invalid("Field '%s' is too long." % field)
    return value


def enum_field(data, field, allowed, required=True, default=None):
    if not _present(data, field, required):
        return default
    value = data.get(field)
    if not isinstance(value, str) or value not in allowed:
        invalid("Field '%s' must be one of %s." % (field, ", ".join(sorted(allowed))))
    return value


def int_field(data, field, minimum=None, maximum=None, required=True, default=None):
    if not _present(data, field, required):
        return default
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        invalid("Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        invalid("Field '%s' is below the allowed minimum." % field)
    if maximum is not None and value > maximum:
        invalid("Field '%s' is above the allowed maximum." % field)
    return value


def number_field(data, field, minimum=None, maximum=None, required=True, default=None):
    if not _present(data, field, required):
        return default
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        invalid("Field '%s' must be a number." % field)
    if minimum is not None and value < minimum:
        invalid("Field '%s' is below the allowed minimum." % field)
    if maximum is not None and value > maximum:
        invalid("Field '%s' is above the allowed maximum." % field)
    return value


def bool_field(data, field, required=True, default=None):
    if not _present(data, field, required):
        return default
    value = data.get(field)
    if not isinstance(value, bool):
        invalid("Field '%s' must be a boolean." % field)
    return value


def datetime_field(data, field, required=True, default=None):
    if not _present(data, field, required):
        return default
    value = data.get(field)
    parsed = parse_iso(value)
    if parsed is None:
        invalid("Field '%s' must be an ISO 8601 timestamp." % field)
    return parsed


def enum_list_field(data, field, allowed, min_items=1, max_items=None,
                    required=True, default=None, unique=True):
    if not _present(data, field, required):
        return default
    value = data.get(field)
    if not isinstance(value, list):
        invalid("Field '%s' must be an array." % field)
    if min_items is not None and len(value) < min_items:
        invalid("Field '%s' has too few entries." % field)
    if max_items is not None and len(value) > max_items:
        invalid("Field '%s' has too many entries." % field)
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            invalid("Field '%s' contains an unknown value." % field)
    if unique and len(set(value)) != len(value):
        invalid("Field '%s' contains duplicates." % field)
    return value


def dict_field(data, field, required=True, default=None):
    if not _present(data, field, required):
        return default
    value = data.get(field)
    if not isinstance(value, dict):
        invalid("Field '%s' must be an object." % field)
    return value


# -------------------------------------------------------------- list filtering

def _as_bool(text):
    lowered = text.strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    return None


def apply_filters(rows, spec):
    """spec: {query_param: (field_name, kind)} with kind in str/int/bool/date/list."""
    for param, (field, kind) in spec.items():
        raw = request.args.get(param)
        if raw is None:
            continue
        keep = []
        for row in rows:
            value = row.get(field)
            if kind == "int":
                try:
                    wanted = int(raw)
                except ValueError:
                    keep = []
                    break
                if value == wanted:
                    keep.append(row)
            elif kind == "bool":
                wanted = _as_bool(raw)
                if wanted is None:
                    keep = []
                    break
                if bool(value) is wanted:
                    keep.append(row)
            elif kind == "list":
                if isinstance(value, list) and raw in value:
                    keep.append(row)
            elif kind == "date":
                if isinstance(value, str) and value.startswith(raw[:10]):
                    keep.append(row)
            else:
                if value == raw:
                    keep.append(row)
        rows = keep
    return rows
