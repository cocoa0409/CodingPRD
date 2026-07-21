"""Shared route helpers: existence lookup, pagination, list responses."""
import errors
from envelope import success


def lookup_or_404(collection, resource_id):
    obj = collection.get(resource_id)
    if obj is None:
        raise errors.not_found()
    return obj


def _pag_int(raw, default, lo, hi, field):
    if raw is None:
        return default
    try:
        v = int(raw)
    except (TypeError, ValueError):
        raise errors.invalid_request("%s must be an integer" % field)
    if v < lo:
        raise errors.invalid_request("%s must be >= %s" % (field, lo))
    if hi is not None and v > hi:
        raise errors.invalid_request("%s must be <= %s" % (field, hi))
    return v


def paginate(items, args):
    limit = _pag_int(args.get("limit"), 10, 1, 100, "limit")
    offset = _pag_int(args.get("offset"), 0, 0, None, "offset")
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def respond_list(request, items, serializer):
    items = sorted(items, key=lambda o: o["_seq"])
    page, pag = paginate(items, request.args)
    data = [serializer(o) for o in page]
    return success(data, "array", 200, pag)
