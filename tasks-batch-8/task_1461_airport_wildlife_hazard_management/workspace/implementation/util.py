"""Envelope, timestamps, pagination, payload validation, serialization helpers."""
import random
import re
import string
import uuid
from datetime import datetime, timezone, date

from flask import request, jsonify

import errors as E
from db import store


# ---------------------------------------------------------------- timestamps
def now():
    """Logical clock — the only time source in the system (PRD §2.10)."""
    return store.clock


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_datetime(v):
    if not isinstance(v, str):
        raise ValueError("not a string")
    s = v.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(v):
    """Strict YYYY-MM-DD -> datetime.date."""
    if not isinstance(v, str):
        raise ValueError("not a string")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v.strip()):
        raise ValueError("not YYYY-MM-DD")
    parts = v.strip().split("-")
    return date(int(parts[0]), int(parts[1]), int(parts[2]))


# ---------------------------------------------------------------- entities
def new_entity(table, fields):
    """Insert a new record with common fields (PRD §2.4)."""
    ts = now()
    rec = dict(fields)
    rec["id"] = str(uuid.uuid4())
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = store.next_seq()
    table[rec["id"]] = rec
    return rec


def touch(rec):
    """Bump version + updated_at (every mutation increments version, PRD §2.4)."""
    rec["version"] += 1
    rec["updated_at"] = now()


def serialize(rec):
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt_dt(v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------- envelope
def make_meta(extra=None):
    meta = {
        "api_request_id": "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=22)),
        "api_request_timestamp": fmt_dt(now()),
    }
    if extra:
        meta.update(extra)
    return meta


def ok_object(data, code=200, meta_extra=None):
    body = {"meta": make_meta(meta_extra), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_list(records, total, limit, offset):
    meta = make_meta({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(records)) < total,
    })
    return jsonify({"meta": meta, "response_type": "array",
                    "data": [serialize(r) for r in records]}), 200


def error_response(e):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


# ---------------------------------------------------------------- pagination
def pagination_params():
    raw_limit = request.args.get("limit", None)
    raw_offset = request.args.get("offset", None)
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise E.invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise E.invalid_request("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise E.invalid_request("offset must be an integer")
        if offset < 0:
            raise E.invalid_request("offset must be >= 0")
    return limit, offset


def list_response(records):
    """Sort by created_at ascending (insertion order breaks ties), paginate, envelope."""
    limit, offset = pagination_params()
    rows = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_list(page, total, limit, offset)


# ---------------------------------------------------------------- body access
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise E.invalid_request("request body must be a JSON object")
    return data


# ---------------------------------------------------------------- validation
KINDS = ("str", "int", "bool", "number", "enum", "datetime", "date", "pattern")


def _convert(name, value, kind, opts):
    if kind == "str":
        if not isinstance(value, str):
            raise E.invalid_request(f"field '{name}' must be a string")
        return value
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise E.invalid_request(f"field '{name}' must be an integer")
        lo, hi = opts.get("min"), opts.get("max")
        if lo is not None and value < lo:
            raise E.invalid_request(f"field '{name}' must be >= {lo}")
        if hi is not None and value > hi:
            raise E.invalid_request(f"field '{name}' must be <= {hi}")
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            raise E.invalid_request(f"field '{name}' must be a boolean")
        return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise E.invalid_request(f"field '{name}' must be a number")
        gt = opts.get("gt")
        if gt is not None and not (value > gt):
            raise E.invalid_request(f"field '{name}' must be > {gt}")
        return value
    if kind == "enum":
        allowed = opts["values"]
        if not isinstance(value, str) or value not in allowed:
            raise E.invalid_enum(name, value)
        return value
    if kind == "datetime":
        try:
            return parse_datetime(value)
        except Exception:
            raise E.invalid_request(f"field '{name}' must be an ISO8601 datetime")
    if kind == "pattern":
        if not isinstance(value, str) or not re.fullmatch(opts["regex"], value):
            raise E.invalid_request(f"field '{name}' does not match required pattern")
        return value
    raise AssertionError(f"unknown kind {kind}")


def validate_payload(data, spec):
    """spec: list of (name, kind, required, opts). Returns dict of cleaned values.

    Field ordering follows the declared spec; first failure wins.
    """
    out = {}
    for entry in spec:
        name, kind, required = entry[0], entry[1], entry[2]
        opts = entry[3] if len(entry) > 3 else {}
        if name not in data or data[name] is None:
            if required:
                raise E.invalid_request(f"missing required field: '{name}'")
            continue
        value = data[name]
        if kind == "date":
            try:
                d = parse_date(value)
            except Exception:
                raise E.invalid_request(f"field '{name}' must be an ISO date (YYYY-MM-DD)")
            out[name] = value.strip()   # store canonical date string
            continue
        out[name] = _convert(name, value, kind, opts)
    return out


def check_fk(field, value, table, label):
    if value not in table:
        raise E.fk_not_found(field)
    return table[value]


def parse_bool_param(raw, field):
    if raw is None:
        return None
    low = raw.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    raise E.invalid_request(f"query parameter '{field}' must be true or false")


def get_or_404(table, rid, label="resource"):
    rec = table.get(rid)
    if rec is None:
        raise E.not_found(label)
    return rec
