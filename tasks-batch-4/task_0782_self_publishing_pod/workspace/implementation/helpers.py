"""Request-parsing helpers: body, pagination, existence lookups, serialization."""
from flask import request

from envelope import ApiError, success_list
from store import db

# entity_kind -> (store dict attr, not_found error id)
_KIND = {
    "publisher": ("publishers", "ERR_PUBLISHER_NOT_FOUND"),
    "title": ("titles", "ERR_TITLE_NOT_FOUND"),
    "format": ("formats", "ERR_FORMAT_NOT_FOUND"),
    "asset": ("assets", "ERR_ASSET_NOT_FOUND"),
    "isbn": ("isbns", "ERR_ISBN_NOT_FOUND"),
    "channel": ("channels", "ERR_CHANNEL_NOT_FOUND"),
    "price": ("prices", "ERR_PRICE_NOT_FOUND"),
    "proof": ("proofs", "ERR_PROOF_NOT_FOUND"),
    "drequest": ("drequests", "ERR_DISTRIBUTION_NOT_FOUND"),
    "salesline": ("sales", "ERR_SALESLINE_NOT_FOUND"),
    "statement": ("statements", "ERR_STATEMENT_NOT_FOUND"),
}


def store_of(kind):
    return getattr(db, _KIND[kind][0])


def resolve(kind, rec_id):
    """Fetch a record by id or raise the entity's not-found error (404)."""
    rec = store_of(kind).get(rec_id)
    if rec is None:
        raise ApiError(_KIND[kind][1])
    return rec


def get_body():
    """Return the JSON request body as a dict. Malformed JSON or a non-object
    body is a shape error (ERR_INVALID_REQUEST). Absent body -> {}."""
    if request.content_length in (None, 0) and not (request.data or b"").strip():
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def pagination():
    """Parse limit/offset with defaults 10/0, clamp limit to [1, 100]."""
    def _int(name, default):
        raw = request.args.get(name)
        if raw is None or raw == "":
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    limit = _int("limit", 10)
    offset = _int("offset", 0)
    if limit > 100:
        limit = 100
    if limit < 1:
        limit = 1
    if offset < 0:
        offset = 0
    return limit, offset


def ordered(records):
    """Sort by created_at ascending (insertion order via _seq tie-break)."""
    return sorted(records, key=lambda r: r.get("_seq", 0))


def paginate_list(records, serializer):
    limit, offset = pagination()
    records = ordered(records)
    total = len(records)
    window = records[offset:offset + limit]
    return success_list([serializer(r) for r in window], limit, offset, total)


# ---- shape validation helpers ----

def require_fields(body, fields):
    for f in fields:
        if body.get(f) is None:
            raise ApiError("ERR_INVALID_REQUEST", f"Missing required field: {f}")


def require_enum(value, allowed, name):
    if value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", f"Invalid value for {name}")


def require_positive_int(value, name):
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ApiError("ERR_INVALID_REQUEST", f"{name} must be a positive integer")


def require_int(value, name):
    if not isinstance(value, int) or isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", f"{name} must be an integer")
