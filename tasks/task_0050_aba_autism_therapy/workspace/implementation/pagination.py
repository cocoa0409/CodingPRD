from flask import request
import errors
from errors import err

# Pagination defaults (PRD §2.3 / SCAFFOLD §1.0).
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
MIN_OFFSET = 0


def parse_pagination():
    """Parse limit/offset query params (PRD §2.3).

    limit defaults 10, min 1, max 100. offset defaults 0, min 0.
    Out-of-range / non-integer values are rejected as ERR_VALIDATION.
    """
    limit = _parse_int_param("limit", DEFAULT_LIMIT, MIN_LIMIT, MAX_LIMIT)
    offset = _parse_int_param("offset", DEFAULT_OFFSET, MIN_OFFSET, None)
    return limit, offset


def _parse_int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        v = int(raw)
    except (ValueError, TypeError):
        raise err(errors.ERR_VALIDATION, f"Query param '{name}' must be an integer.")
    if minimum is not None and v < minimum:
        raise err(errors.ERR_VALIDATION, f"Query param '{name}' below minimum {minimum}.")
    if maximum is not None and v > maximum:
        raise err(errors.ERR_VALIDATION, f"Query param '{name}' above maximum {maximum}.")
    return v


def paginate(items, limit, offset):
    """Sort by created_at ASC (tiebreak _seq), then slice (PRD §2.3).

    Returns (page_items, pagination_meta).
    """
    ordered = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta
