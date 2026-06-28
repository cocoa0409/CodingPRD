"""Entity lookup with ERR_NOT_FOUND and ownership checks (ERR_NOT_RESOURCE_OWNER)."""
from db import db
from errors import err, ERR_NOT_FOUND, ERR_NOT_RESOURCE_OWNER


def get_or_404(store, _id):
    ent = store.get(_id)
    if ent is None:
        raise err(ERR_NOT_FOUND, "Resource not found")
    return ent


# ---- ownership helpers ----
def check_client_owner(role, user_id, client_id):
    """Client role may only act on its own client_id."""
    if role == "Client" and user_id != client_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Client does not own this resource")


def check_therapist_owner(role, user_id, therapist_id):
    """Therapist role may only act on resources tied to its own therapist_id."""
    if role == "Therapist" and user_id != therapist_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Therapist does not own this resource")


def match_owner_therapist_id(match):
    return match["therapist_id"]


def paginate(items, args):
    """Apply limit/offset pagination. Returns (page_items, limit, offset, total).
    items must already be sorted."""
    from validate import err as verr  # noqa
    from errors import err as _err, ERR_VALIDATION

    limit = args.get("limit")
    offset = args.get("offset")
    # defaults
    lim = 10
    off = 0
    if limit is not None:
        try:
            lim = int(limit)
        except (ValueError, TypeError):
            raise _err(ERR_VALIDATION, "limit must be an integer")
        if lim < 1 or lim > 100:
            raise _err(ERR_VALIDATION, "limit out of range [1,100]")
    if offset is not None:
        try:
            off = int(offset)
        except (ValueError, TypeError):
            raise _err(ERR_VALIDATION, "offset must be an integer")
        if off < 0:
            raise _err(ERR_VALIDATION, "offset must be >= 0")
    total = len(items)
    page = items[off:off + lim]
    return page, lim, off, total
