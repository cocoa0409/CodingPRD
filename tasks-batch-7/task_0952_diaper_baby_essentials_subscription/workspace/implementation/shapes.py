"""Gate G4 — request shape rules (PRD 2.11).

The four rungs run as four ORDERED PASSES over the whole body, not per field:
  rung  8  ERR_MISSING_FIELD      required field absent or explicitly null
  rung  9  ERR_INVALID_FORMAT     a value fails to parse
  rung 10  ERR_INVALID_ENUM       CLOSED, EXHAUSTIVE list of enum fields only
  rung 11  ERR_VALUE_OUT_OF_RANGE numeric range violations
"""

from flask import request

import store
from errors import ApiError


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_FORMAT", "Request body must be a JSON object.")
    return data


def field(name, required=False, kind="string", members=None, lo=None, hi=None,
          default=None, enum_error="ERR_INVALID_ENUM"):
    return {
        "name": name, "required": required, "kind": kind, "members": members,
        "lo": lo, "hi": hi, "default": default, "enum_error": enum_error,
    }


def _is_int(value):
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return float(value).is_integer()
    return False


def _is_number(value):
    if isinstance(value, bool):
        return False
    return isinstance(value, (int, float))


def _format_ok(spec, value):
    kind = spec["kind"]
    if kind in ("string", "enum"):
        return isinstance(value, str)
    if kind == "int":
        return _is_int(value)
    if kind == "number":
        return _is_number(value)
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "date":
        return isinstance(value, str) and store.parse_date(value) is not None
    if kind == "instant":
        return isinstance(value, str) and store.parse_instant(value) is not None
    if kind == "array":
        return isinstance(value, list) and all(isinstance(x, str) for x in value)
    if kind == "id_list":
        return isinstance(value, list) and all(isinstance(x, str) for x in value)
    return True


def _coerce(spec, value):
    if spec["kind"] == "int":
        return int(value)
    return value


def validate(data, specs):
    """Run the four G4 passes in priority order and return the parsed values."""
    present = {}
    for spec in specs:
        name = spec["name"]
        if name in data and data[name] is not None:
            present[name] = data[name]

    # rung 8 — required fields
    for spec in specs:
        if spec["required"] and spec["name"] not in present:
            raise ApiError("ERR_MISSING_FIELD",
                           "Required field '%s' is absent or null." % spec["name"])

    # rung 9 — formats
    for spec in specs:
        name = spec["name"]
        if name in present and not _format_ok(spec, present[name]):
            raise ApiError("ERR_INVALID_FORMAT",
                           "Field '%s' failed to parse." % name)

    # rung 10 — enum membership (closed, exhaustive list of fields)
    for spec in specs:
        name = spec["name"]
        if name in present and spec["members"] is not None:
            if present[name] not in spec["members"]:
                raise ApiError(spec["enum_error"],
                               "Field '%s' carries an undeclared value." % name)

    # rung 11 — numeric ranges
    for spec in specs:
        name = spec["name"]
        if name not in present:
            continue
        if spec["lo"] is not None and present[name] < spec["lo"]:
            raise ApiError("ERR_VALUE_OUT_OF_RANGE",
                           "Field '%s' is below its declared minimum." % name)
        if spec["hi"] is not None and present[name] > spec["hi"]:
            raise ApiError("ERR_VALUE_OUT_OF_RANGE",
                           "Field '%s' is above its declared maximum." % name)

    out = {}
    for spec in specs:
        name = spec["name"]
        if name in present:
            out[name] = _coerce(spec, present[name])
        else:
            out[name] = spec["default"]
    out["_present"] = set(present.keys())
    return out


def supplied(parsed, name):
    return name in parsed.get("_present", set())


# ---------------------------------------------------------------------------
# Query filters — an unrecognised filter value simply matches nothing.
# ---------------------------------------------------------------------------
def qs(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def qs_bool(name, default=True):
    raw = request.args.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("false", "0", "no")


def match(row, name, value, attr=None):
    if value is None:
        return True
    return row.get(attr or name) == value
