"""Standard response envelope and pagination, per scaffold response_envelope."""
import json
import uuid
from datetime import datetime
from decimal import Decimal

from flask import Response, request

import db


def _request_meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": db.wall_now(),
    }


def serialize(value):
    if isinstance(value, dict):
        return {k: serialize(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [serialize(v) for v in value]
    if isinstance(value, datetime):
        return db.iso_logical(value)
    if isinstance(value, Decimal):
        return float(value)
    return value


def _json_response(payload, status):
    return Response(json.dumps(payload), status=status, mimetype="application/json")


def ok(data, status=200, rtype="object", pagination=None):
    meta = _request_meta()
    if pagination is not None:
        meta.update(pagination.meta())
    payload = {"meta": meta, "response_type": rtype, "data": serialize(data)}
    return _json_response(payload, status)


def created(data, rtype="object"):
    return ok(data, status=201, rtype=rtype)


def error(err):
    payload = {
        "meta": _request_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return _json_response(payload, err.status)


class Paginator:
    """Offset pagination: limit default 10 (min 1, max 100), offset default 0.

    List results sort by created_at ascending (insertion order tie-break).
    """

    def __init__(self):
        try:
            limit = int(request.args.get("limit", 10))
        except (TypeError, ValueError):
            limit = 10
        self.limit = max(1, min(100, limit))
        try:
            offset = int(request.args.get("offset", 0))
        except (TypeError, ValueError):
            offset = 0
        self.offset = max(0, offset)
        self._meta = {"limit": self.limit, "offset": self.offset,
                      "total_count": 0, "has_more": False}

    def filter(self, rows, field):
        raw = request.args.get(field)
        if raw is None:
            return rows
        return [r for r in rows if str(r.get(field)) == raw]

    def __call__(self, rows):
        rows = sorted(rows, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
        total = len(rows)
        page = rows[self.offset:self.offset + self.limit]
        self._meta = {
            "limit": self.limit,
            "offset": self.offset,
            "total_count": total,
            "has_more": (self.offset + len(page)) < total,
        }
        return page

    def meta(self):
        return dict(self._meta)
