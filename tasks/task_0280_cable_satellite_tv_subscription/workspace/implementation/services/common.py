"""Shared route helpers: body parsing, pagination, catalog lookups, serialization."""

from flask import request

import db
import errors
from response import list_response, object_response


# ---------------------------------------------------------------------------
# Body parsing
# ---------------------------------------------------------------------------
def get_json_body():
    """Return the request JSON body as a dict, or {} when absent. Raises on malformed."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.invalid_request("Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Body must be a JSON object")
    return body


def require_str(body, field):
    val = body.get(field)
    if not isinstance(val, str) or not val.strip():
        raise errors.invalid_request(f"Missing or invalid field: {field}")
    return val


def require_int(body, field, minimum=None):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Missing or invalid integer field: {field}")
    if minimum is not None and val < minimum:
        raise errors.invalid_request(f"Field {field} must be >= {minimum}")
    return val


def optional_int(body, field, default, minimum=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Invalid integer field: {field}")
    if minimum is not None and val < minimum:
        raise errors.invalid_request(f"Field {field} must be >= {minimum}")
    return val


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise errors.invalid_request(f"Invalid boolean field: {field}")
    return val


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3) — limit default 10, min 1, max 100; offset default 0
# ---------------------------------------------------------------------------
def get_pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise errors.validation("limit must be an integer")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise errors.validation("offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate_and_respond(items):
    """Sort by created_at asc, apply limit/offset, return a list envelope."""
    limit, offset = get_pagination()
    items = sorted(items, key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return list_response(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Catalog lookups (existence + active per PRD §2.6)
# ---------------------------------------------------------------------------
def get_active_catalog(store, entity_id):
    """Return an active catalog entity or raise ERR_CATALOG_ENTITY_NOT_FOUND."""
    ent = store.get(entity_id)
    if ent is None or not ent.get("active", True):
        raise errors.catalog_not_found()
    return ent


def get_account_or_404(account_id):
    acc = db.accounts.get(account_id)
    if acc is None:
        raise errors.account_not_found()
    return acc


def subscriber_owns(role, user_id, account_id):
    """Enforce Subscriber ownership against the PATH account id (PRD §2.7).

    Ownership (priority 3) precedes account existence (priority 4), so this
    compares X-User-ID to the path id and must be called BEFORE the existence
    lookup. For a Subscriber whose id does not equal the path account id, this
    raises ERR_NOT_RESOURCE_OWNER even when the account does not exist.
    """
    if role == "Subscriber" and user_id != account_id:
        raise errors.not_resource_owner()


def resolve_account(role, user_id, account_id):
    """Ownership-before-existence: check Subscriber ownership, then resolve 404."""
    subscriber_owns(role, user_id, account_id)
    return get_account_or_404(account_id)
