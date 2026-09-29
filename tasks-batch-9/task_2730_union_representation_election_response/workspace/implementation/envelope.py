"""Response envelope helpers (PRD 2.2 / 2.3)."""

import datetime
import decimal
import json
import random
import string

from flask import Response

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _wall_timestamp():
    dt = datetime.datetime.now(datetime.timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000)


def _meta():
    return {"api_request_id": request_id(), "api_request_timestamp": _wall_timestamp()}


def _json_default(value):
    """Safety net so a stray computed value never becomes a 500."""
    import clockutil
    if isinstance(value, datetime.datetime):
        return clockutil.fmt_dt(value)
    if isinstance(value, datetime.date):
        return clockutil.fmt_date(value)
    if isinstance(value, decimal.Decimal):
        return float(value)
    return str(value)


def _emit(body, status):
    return Response(json.dumps(body, default=_json_default), status=status,
                    mimetype="application/json")


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object",
            "data": data if data is not None else {}}
    return _emit(body, status)


def created(data):
    return object_response(data, 201)


def empty_response(status=200):
    return object_response({}, status)


def array_response(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return _emit(body, 200)


def error_response(error_id, message, status):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}
    return _emit(body, status)
