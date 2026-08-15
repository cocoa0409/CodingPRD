"""Payload parsing, field type guards, pagination, list helpers.

Validation pipeline per PRD section 2.12: payload-shape errors (400) are the
FINAL gate, so Payload records bad fields and raises only when finish() runs,
after existence/state/business/OCC checks have had their chance.
"""
import re
from datetime import datetime

from flask import request

from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import list_response


class Payload:
    def __init__(self):
        if not request.data:
            self.body = {}
            self.malformed = False
        else:
            data = request.get_json(force=True, silent=True)
            if isinstance(data, dict):
                self.body = data
                self.malformed = False
            else:
                self.body = {}
                self.malformed = True
        self.bad = []

    def provided(self, name):
        return name in self.body

    def req_str(self, name, pattern=None, min_len=None, max_len=None):
        v = self.body.get(name)
        if not isinstance(v, str):
            self.bad.append(name)
            return None
        if pattern is not None and not re.fullmatch(pattern, v):
            self.bad.append(name)
            return None
        if min_len is not None and len(v) < min_len:
            self.bad.append(name)
            return None
        if max_len is not None and len(v) > max_len:
            self.bad.append(name)
            return None
        return v

    def opt_str(self, name, pattern=None, min_len=None, max_len=None, nullable=True):
        if name not in self.body:
            return None
        v = self.body.get(name)
        if v is None:
            if nullable:
                return None
            self.bad.append(name)
            return None
        return self.req_str(name, pattern=pattern, min_len=min_len, max_len=max_len)

    def req_int(self, name):
        v = self.body.get(name)
        if isinstance(v, bool) or not isinstance(v, int):
            self.bad.append(name)
            return None
        return v

    def opt_int(self, name, nullable=True):
        if name not in self.body:
            return None
        v = self.body.get(name)
        if v is None:
            if nullable:
                return None
            self.bad.append(name)
            return None
        return self.req_int(name)

    def req_num(self, name):
        v = self.body.get(name)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            self.bad.append(name)
            return None
        return v

    def opt_num(self, name):
        if name not in self.body:
            return None
        v = self.body.get(name)
        if v is None:
            return None
        return self.req_num(name)

    def req_date(self, name):
        v = self.body.get(name)
        if not isinstance(v, str):
            self.bad.append(name)
            return None
        try:
            return datetime.strptime(v, "%Y-%m-%d").date()
        except ValueError:
            self.bad.append(name)
            return None

    def req_enum(self, name, values):
        v = self.body.get(name)
        if not isinstance(v, str) or v not in values:
            self.bad.append(name)
            return None
        return v

    def finish(self):
        if self.malformed or self.bad:
            raise ApiError(
                ERR_INVALID_REQUEST, 400,
                "Required field missing, wrong scalar type, or malformed value: "
                + (", ".join(self.bad) if self.bad else "body"),
            )


def require_exists(collection, entity_id, what="resource"):
    obj = collection.get(entity_id) if isinstance(entity_id, str) else None
    if obj is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Referenced %s does not exist" % what)
    return obj


def pagination_params():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit, offset = 10, 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    return limit, offset


def list_page(items, view):
    """Default sort: created_at ascending; _seq breaks identical logical-clock ties."""
    limit, offset = pagination_params()
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return list_response([view(e) for e in page], total, limit, offset)
