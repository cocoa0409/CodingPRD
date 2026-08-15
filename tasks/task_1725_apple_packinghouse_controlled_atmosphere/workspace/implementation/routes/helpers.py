"""Shared route helpers: serialization, pagination, list responses, scoping."""
from flask import request

from db import db
from errors import raise_error, ERR_INVALID_REQUEST
from middleware import get_caller, check_role_allowed
from response import success_list
from services.domain import bins_allocated
from util import num


def public(rec):
    """Strip internal fields and convert Decimals to JSON-native numbers."""
    if rec is None:
        return None
    return {k: num(v) for k, v in rec.items() if not k.startswith("_")}


def public_room(room):
    """CARoom serialization with derived bins_allocated / bins_free."""
    out = public(room)
    allocated = bins_allocated(room["id"])
    out["bins_allocated"] = allocated
    out["bins_free"] = room["bin_capacity"] - allocated
    return out


def get_pagination():
    """limit/offset query params: defaults 10/0, bounds 1..100 / >=0 (PRD 2.3)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None or limit_raw == "":
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            raise_error(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset_raw is None or offset_raw == "":
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_error(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def sorted_items(collection):
    """created_at ascending; insertion sequence breaks identical-clock ties."""
    items = list(db[collection].values())
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return items


def list_response(items, serializer=public):
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serializer(r) for r in page], total, limit, offset)
