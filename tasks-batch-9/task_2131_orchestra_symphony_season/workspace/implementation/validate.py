"""Request-shape helpers (rung 6), body referential integrity (rung 4)
and pagination parsing (PRD 2.3)."""

from datetime import datetime, timezone

from flask import request

from db import db
from errors import raise_err


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def _bad(field, why):
    raise_err("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, why))


def present(data, field):
    return field in data and data[field] is not None


# --------------------------------------------------------------------------
# scalar shape checks
# --------------------------------------------------------------------------

def req_str(data, field):
    if not present(data, field):
        _bad(field, "is required")
    value = data[field]
    if not isinstance(value, str) or value.strip() == "":
        _bad(field, "must be a non-empty string")
    return value


def opt_str(data, field, default=None):
    if not present(data, field):
        return default
    return req_str(data, field)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_int(data, field, minv=None, maxv=None):
    if not present(data, field):
        _bad(field, "is required")
    value = data[field]
    if not _is_int(value):
        _bad(field, "must be an integer")
    if minv is not None and value < minv:
        _bad(field, "must be >= %d" % minv)
    if maxv is not None and value > maxv:
        _bad(field, "must be <= %d" % maxv)
    return value


def opt_int(data, field, default=None, minv=None, maxv=None):
    if not present(data, field):
        return default
    return req_int(data, field, minv, maxv)


def req_bool(data, field):
    if not present(data, field):
        _bad(field, "is required")
    if not isinstance(data[field], bool):
        _bad(field, "must be a boolean")
    return data[field]


def opt_bool(data, field, default=False):
    if not present(data, field):
        return default
    return req_bool(data, field)


def req_enum(data, field, values):
    value = req_str(data, field)
    if value not in values:
        _bad(field, "must be one of %s" % ", ".join(values))
    return value


def opt_enum(data, field, values, default=None):
    if not present(data, field):
        return default
    return req_enum(data, field, values)


def parse_dt(value, field="timestamp"):
    if not isinstance(value, str) or not value.strip():
        _bad(field, "must be an ISO 8601 UTC timestamp")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        _bad(field, "must be an ISO 8601 UTC timestamp")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def req_dt(data, field):
    if not present(data, field):
        _bad(field, "is required")
    return parse_dt(data[field], field)


def req_list(data, field):
    if field not in data or data[field] is None:
        _bad(field, "is required")
    if not isinstance(data[field], list):
        _bad(field, "must be an array")
    return data[field]


# --------------------------------------------------------------------------
# rung 4 — body referential integrity
# --------------------------------------------------------------------------

_FK_TABLES = [
    ("season_id", "seasons", "ERR_SEASON_NOT_FOUND"),
    ("venue_id", "venues", "ERR_VENUE_NOT_FOUND"),
    ("concert_id", "concerts", "ERR_CONCERT_NOT_FOUND"),
    ("seat_section_id", "sections", "ERR_SECTION_NOT_FOUND"),
    ("patron_id", "patrons", "ERR_PATRON_NOT_FOUND"),
    ("musician_id", "musicians", "ERR_MUSICIAN_NOT_FOUND"),
    ("contract_id", "contracts", "ERR_CONTRACT_NOT_FOUND"),
]


def check_body_fks(data, fields):
    """Resolve every foreign key supplied in the body, in the canonical order
    of PRD 2.6 rung 4.  `fields` names the FK columns this endpoint carries."""
    for name, table, error_id in _FK_TABLES:
        if name not in fields:
            continue
        if not present(data, name):
            continue
        value = data[name]
        if not isinstance(value, str) or value not in getattr(db, table):
            raise_err(error_id)
    if "concert_ids" in fields and isinstance(data.get("concert_ids"), list):
        for cid in data["concert_ids"]:
            if not isinstance(cid, str) or cid not in db.concerts:
                raise_err("ERR_CONCERT_NOT_FOUND")


# --------------------------------------------------------------------------
# pagination
# --------------------------------------------------------------------------

def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            _bad("limit", "must be an integer")
        if limit < 1 or limit > 100:
            _bad("limit", "must be between 1 and 100")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            _bad("offset", "must be an integer")
        if offset < 0:
            _bad("offset", "must be >= 0")
    return limit, offset


def sort_key(record):
    """Default list ordering: created_at ascending, stabilised by insertion
    sequence so that a frozen logical clock still yields creation order."""
    return (record["created_at"], record["_seq"])


def paginate(records, serializer):
    limit, offset = pagination()
    records = sorted(records, key=sort_key)
    total = len(records)
    page = records[offset:offset + limit]
    return [serializer(r) for r in page], limit, offset, total
