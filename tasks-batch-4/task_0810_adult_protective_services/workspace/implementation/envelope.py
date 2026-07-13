"""Response envelope helpers (PRD 2.2). All timestamps use the logical clock."""
import random
import string
from datetime import timezone

from store import store

_ALNUM = string.ascii_letters + string.digits


def request_id():
    return "req_" + "".join(random.choices(_ALNUM, k=20))


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def _meta(extra=None):
    m = {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_ts(store.clock),
    }
    if extra:
        m.update(extra)
    return m


def success(data, response_type="object", pagination=None):
    return {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
