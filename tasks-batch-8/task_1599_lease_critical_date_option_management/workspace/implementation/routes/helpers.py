"""Shared route helpers: pagination, nested path resolution (left-to-right 404)."""
from flask import request

from db import db
from errors import raise_error, ERR_NOT_FOUND, ERR_VALIDATION
from response import success_list


def get_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None or raw_limit == "":
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_error(ERR_VALIDATION, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_error(ERR_VALIDATION, "limit must be between 1 and 100")
    if raw_offset is None or raw_offset == "":
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_error(ERR_VALIDATION, "offset must be an integer")
        if offset < 0:
            raise_error(ERR_VALIDATION, "offset must be >= 0")
    return limit, offset


def parse_bool_query(field):
    v = request.args.get(field)
    if v is None or v == "":
        return None
    if v.lower() == "true":
        return True
    if v.lower() == "false":
        return False
    raise_error(ERR_VALIDATION, f"query parameter {field} must be true or false")


def sorted_items(collection, filters=None):
    items = list(db[collection].values())
    if filters:
        for k, v in filters.items():
            if v is None:
                continue
            items = [r for r in items if r.get(k) == v]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))  # created_at ascending
    return items


def paged(items, serializer):
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serializer(r) for r in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Nested path resolution — strictly left to right (PRD §2.6)
# ---------------------------------------------------------------------------

def resolve_portfolio(pid):
    p = db["portfolios"].get(pid)
    if p is None:
        raise_error(ERR_NOT_FOUND, "portfolio not found")
    return p


def resolve_lease(pid, lid):
    p = resolve_portfolio(pid)
    l = db["leases"].get(lid)
    if l is None or l["portfolio_id"] != pid:
        raise_error(ERR_NOT_FOUND, "lease not found")
    return p, l


def resolve_option(pid, lid, oid):
    p, l = resolve_lease(pid, lid)
    o = db["options"].get(oid)
    if o is None or o["lease_id"] != lid:
        raise_error(ERR_NOT_FOUND, "option not found")
    return p, l, o


def resolve_notice(pid, lid, oid, nid):
    p, l, o = resolve_option(pid, lid, oid)
    n = db["notices"].get(nid)
    if n is None or n["option_id"] != oid:
        raise_error(ERR_NOT_FOUND, "exercise notice not found")
    return p, l, o, n


def resolve_assessment(pid, lid, oid, mid):
    p, l, o = resolve_option(pid, lid, oid)
    m = db["assessments"].get(mid)
    if m is None or m["option_id"] != oid:
        raise_error(ERR_NOT_FOUND, "assessment not found")
    return p, l, o, m


def resolve_amendment(pid, lid, aid):
    p, l = resolve_lease(pid, lid)
    a = db["amendments"].get(aid)
    if a is None or a["lease_id"] != lid:
        raise_error(ERR_NOT_FOUND, "amendment not found")
    return p, l, a


def resolve_contact(pid, cid):
    p = resolve_portfolio(pid)
    c = db["contacts"].get(cid)
    if c is None or c["portfolio_id"] != pid:
        raise_error(ERR_NOT_FOUND, "contact not found")
    return p, c
