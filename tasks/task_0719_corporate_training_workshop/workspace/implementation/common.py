from flask import request
from db import db, new_id, now_iso
from errors import err

_seq_counter = [0]


def next_seq():
    _seq_counter[0] += 1
    return _seq_counter[0]


def get_body():
    """Return the JSON body as a dict. Raises ERR_INVALID_REQUEST on malformed JSON."""
    if request.content_length in (None, 0) and not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Body must be a JSON object")
    return data


def base_fields(with_common=True):
    ts = now_iso()
    rec = {"id": new_id(), "_seq": next_seq()}
    if with_common:
        rec["created_at"] = ts
        rec["updated_at"] = ts
        rec["version"] = 1
    else:
        rec["created_at"] = ts
    return rec


def touch(rec):
    """Bump updated_at + version on a common-fields entity."""
    rec["updated_at"] = now_iso()
    if "version" in rec:
        rec["version"] = rec.get("version", 1) + 1


def public(rec):
    """Strip internal fields before serialization."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---- field type / value helpers --------------------------------------------

def require_str(body, name):
    if name not in body:
        raise err("ERR_INVALID_REQUEST", "Missing field: %s" % name)
    v = body[name]
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", "%s must be a non-empty string" % name)
    return v


def opt_str(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", "%s must be a string" % name)
    return v


def require_int(body, name):
    if name not in body:
        raise err("ERR_INVALID_REQUEST", "Missing field: %s" % name)
    return _as_int(body[name], name)


def opt_int(body, name, default):
    if name not in body or body[name] is None:
        return default
    return _as_int(body[name], name)


def _as_int(v, name):
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    return v


def require_number(body, name):
    if name not in body:
        raise err("ERR_INVALID_REQUEST", "Missing field: %s" % name)
    return _as_number(body[name], name)


def opt_number(body, name, default):
    if name not in body or body[name] is None:
        return default
    return _as_number(body[name], name)


def _as_number(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", "%s must be a number" % name)
    return v


def require_enum(body, name, allowed):
    v = require_str(body, name)
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", "%s must be one of %s" % (name, sorted(allowed)))
    return v


def opt_bool(body, name, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "%s must be a boolean" % name)
    return v


def require_datetime(body, name):
    from timeutil import parse_iso
    v = require_str(body, name)
    try:
        parse_iso(v)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "%s must be an ISO 8601 datetime" % name)
    return v


# ---- existence helpers (raise ERR_NOT_FOUND) -------------------------------

def find_or_404(table, _id):
    rec = table.get(_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource not found: %s" % _id)
    return rec
