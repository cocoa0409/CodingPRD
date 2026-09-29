"""Response envelope helpers (PRD section 2.2) and value serialisation."""

import datetime
import random
import string
from decimal import Decimal

from flask import g, jsonify

from db import db

_ALNUM = string.ascii_uppercase + string.digits

# End-of-day domain deadlines carry 23:59:59 UTC with zero fractional seconds
# (PRD section 2.4).  Every other timestamp carries exactly three digits.
EOD_FIELDS = frozenset(["deadline_utc", "invoice_due_utc", "expires_at_utc"])


def fmt_dt(dt):
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_eod(dt):
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_dt(datetime.datetime.now(datetime.timezone.utc)),
    }


def _convert(key, value):
    if isinstance(value, datetime.datetime):
        return fmt_eod(value) if key in EOD_FIELDS else fmt_dt(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return dict((k, _convert(k, v)) for k, v in value.items())
    if isinstance(value, list):
        return [_convert(key, v) for v in value]
    return value


def jsonable(record):
    """Project a stored record onto its wire shape, dropping internal keys."""
    if record is None:
        return None
    out = {}
    for key, value in record.items():
        if key.startswith("_"):
            continue
        out[key] = _convert(key, value)
    return out


def ok(data, status=200):
    # jsonable() is idempotent, so ad-hoc payloads (metrics, the clock reading)
    # get the same datetime and Decimal treatment stored records do.
    if isinstance(data, dict):
        data = jsonable(data)
    return jsonify({"meta": meta(), "response_type": "object", "data": data}), status


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total_count):
    m = meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total_count
    m["has_more"] = (offset + len(items)) < total_count
    payload = [jsonable(i) if isinstance(i, dict) else i for i in items]
    return jsonify({"meta": m, "response_type": "array", "data": payload}), 200


def error_body(error_id, message):
    return {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def touch(record, force=False):
    """Advance a record's revision counter and updated_at.

    A record mutated several times inside one request (a cascade touching the
    same parcel through two links) advances its ``version`` by exactly 1, per
    PRD section 2.10, unless ``force`` names a genuinely repeated mutation.
    """
    if record is None or "version" not in record:
        return record
    touched = getattr(g, "touched", None)
    if touched is None:
        touched = set()
        g.touched = touched
    if not force and record["id"] in touched:
        return record
    touched.add(record["id"])
    record["version"] += 1
    record["updated_at"] = db.clock
    return record
