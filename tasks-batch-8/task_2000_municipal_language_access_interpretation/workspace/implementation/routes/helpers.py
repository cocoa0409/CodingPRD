"""Shared route helpers: list pagination (PRD §2.3) and read endpoints."""
from flask import request

from db import db
from errors import raise_error, ERR_VALIDATION
from middleware import authorized, ALL_READ_ROLES
from response import success_list, success_object
from util import parse_iso
from validate import require_path


def get_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None or limit_raw == "":
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_error(ERR_VALIDATION, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_error(ERR_VALIDATION, "limit must be between 1 and 100")
    if offset_raw is None or offset_raw == "":
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_error(ERR_VALIDATION, "offset must be an integer")
        if offset < 0:
            raise_error(ERR_VALIDATION, "offset must be >= 0")
    return limit, offset


def list_endpoint(collection, serializer, filters=None, int_filter_fields=()):
    """GET list: all roles may read. Sorted by created_at ascending; optional
    equality filters; limit/offset pagination with the envelope fields in meta."""
    authorized(ALL_READ_ROLES)
    items = list(db[collection].values())
    if filters:
        for field, raw in filters.items():
            if raw is None:
                continue
            if field in int_filter_fields:
                try:
                    value = int(raw)
                except (TypeError, ValueError):
                    return _page([], serializer)
                items = [r for r in items if r.get(field) == value]
            elif field == "language_code" and collection == "interpreters":
                items = [r for r in items if raw in r.get("language_codes", [])]
            elif field == "modality" and collection == "interpreters":
                items = [r for r in items if raw in r.get("modalities", [])]
            else:
                items = [r for r in items if r.get(field) == raw]
    items.sort(key=lambda r: (parse_iso(r["created_at"]), r["_seq"]))
    return _page(items, serializer)


def _page(items, serializer):
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([serializer(r) for r in page], total, limit, offset)


def get_one(collection, rid, not_found_spec, serializer):
    """GET one: all roles may read; unknown id -> the resource's not-found id."""
    authorized(ALL_READ_ROLES)
    rec = require_path(collection, rid, not_found_spec)
    return success_object(serializer(rec))
