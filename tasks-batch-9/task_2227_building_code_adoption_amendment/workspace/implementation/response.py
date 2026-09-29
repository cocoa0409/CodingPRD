"""Response envelope helpers (PRD 2.2, SCAFFOLD 1.0 response_envelope)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify

_ALPHABET = string.ascii_lowercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(16))


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def iso_instant(dt):
    """ISO 8601 UTC for a domain instant.

    PRD 2.4 fixes three fractional digits on `created_at` / `updated_at` only.
    Every other datetime the PRD names — the declared intake dates, comment
    window bounds, hearing schedule, the clock-stamped `received_at`,
    `convened_at`, `adjourned_at`, `published_at`, and the whole transition
    schedule — is rendered without a fractional part when it lands on a whole
    second, which is how the PRD itself writes those instants (for example the
    default clock reading `2026-08-01T00:00:00Z`).
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return "%04d-%02d-%02dT%02d:%02d:%02dZ" % (
            dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        )
    return iso(dt)


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(datetime.now(timezone.utc)),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def list_response(items, limit, offset, total_count, status=200):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(items) < total_count,
    }
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
