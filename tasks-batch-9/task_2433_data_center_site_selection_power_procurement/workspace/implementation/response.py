"""Response envelope helpers (PRD 2.2 / 2.3)."""

import json
import random
import string
from decimal import Decimal

from flask import Response

from db import store

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        # PRD 2.6: server-generated instants read the logical clock.
        "api_request_timestamp": store.now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def _default(value):
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError("not serializable: %r" % (value,))


def _json(payload, status):
    body = json.dumps(payload, default=_default)
    return Response(body, status=status, mimetype="application/json")


def success(data, response_type="object", status=200, extra_meta=None):
    return _json(
        {"meta": _meta(extra_meta), "response_type": response_type, "data": data},
        status,
    )


def error(error_id, message, status):
    return _json(
        {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": error_id, "message": message},
        },
        status,
    )
