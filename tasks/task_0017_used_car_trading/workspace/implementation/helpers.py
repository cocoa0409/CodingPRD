"""Misc helpers: pagination, version checks, body parsing."""

from flask import g, request

from clock import iso, now
from errors import err


def parse_pagination(args):
    """Returns (limit, offset). Raises ERR_PAGINATION_INVALID if bad."""
    try:
        limit = int(args.get("limit", 10))
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        raise err("ERR_PAGINATION_INVALID", "limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise err("ERR_PAGINATION_INVALID", "limit must be in [1,100]")
    if offset < 0:
        raise err("ERR_PAGINATION_INVALID", "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total


def get_body() -> dict:
    """Return the JSON body or {}; never raise on parse-empty."""
    if not request.data:
        return {}
    try:
        body = request.get_json(silent=True, force=True)
    except Exception:
        body = None
    return body if isinstance(body, dict) else {}


def check_version(stored_version: int, body: dict):
    """Optimistic concurrency check; raises ERR_VERSION_CONFLICT on mismatch.
    Skips when client did not supply `version`."""
    if not isinstance(body, dict):
        return
    v = body.get("version", None)
    if v is None:
        return
    try:
        v = int(v)
    except (TypeError, ValueError):
        # Treat malformed version as a conflict — safer.
        raise err("ERR_VERSION_CONFLICT", "Malformed version")
    if v != stored_version:
        raise err("ERR_VERSION_CONFLICT",
                  f"Stale version: client={v}, server={stored_version}")


def bump(record: dict):
    """Bump the version + updated_at on a record (in-place)."""
    if "version" in record:
        record["version"] = int(record.get("version", 1)) + 1
    record["updated_at"] = iso(now())


def stamp_new_record(record: dict, with_version=True):
    """Initialize created_at/updated_at/version on a freshly-minted record."""
    t = iso(now())
    record["created_at"] = t
    if with_version:
        record["updated_at"] = t
        record["version"] = 1
    return record


def sort_for_list(records):
    """Sort by (created_at ASC, id ASC) per PRD §2.3."""
    return sorted(records, key=lambda r: (r.get("created_at", ""), r.get("id", "")))


def actor_owns_seller(seller_id: str) -> bool:
    return g.role == "Seller" and g.user_id == seller_id


def actor_owns_buyer(buyer_id: str) -> bool:
    return g.role == "Buyer" and g.user_id == buyer_id
