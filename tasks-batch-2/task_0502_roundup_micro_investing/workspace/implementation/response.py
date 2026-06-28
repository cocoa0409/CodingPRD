"""Response envelope helpers (PRD §2.2) and timestamp formatting (§2.4).

Envelope field names are emitted verbatim from the scaffold §1.0:
  meta { api_request_id, api_request_timestamp[, pagination fields] }
  response_type: "object" | "array" | "error"
  data: {...}
"""

import datetime
import random
import string

from flask import jsonify

_ALNUM = string.ascii_letters + string.digits


def gen_request_id():
    # PRD §2.2 — server-generated id that starts with "req_".
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def iso_now_ms():
    # PRD §2.2 / §2.4 — ISO 8601 UTC with three fractional digits.
    now = datetime.datetime.now(datetime.timezone.utc)
    return format_ts(now)


def format_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits, trailing 'Z'."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    dt = dt.astimezone(datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _base_meta():
    return {
        "api_request_id": gen_request_id(),
        "api_request_timestamp": iso_now_ms(),
    }


def success(data, status=200, pagination=None):
    response_type = "array" if isinstance(data, list) else "object"
    meta = _base_meta()
    if pagination is not None:
        # PRD §2.3 — list responses carry limit/offset/total_count/has_more in meta.
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(error_id, message, http_status):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
