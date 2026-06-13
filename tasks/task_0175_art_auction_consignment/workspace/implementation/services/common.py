"""Shared helpers: serialization, pagination, OCC, field validation.

Serialization strips internal-only keys (those starting with "_") so the
response body never leaks the creation-order sequence.
"""
import errors
from errors import err

# Pagination defaults (PRD §2.3, SCAFFOLD §1.0)
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def serialize(record):
    """Return a public copy of a record with internal keys removed."""
    if record is None:
        return None
    return {k: v for k, v in record.items() if not k.startswith("_")}


def parse_pagination(args):
    """Parse limit/offset query params. Raises ERR_VALIDATION_PAGINATION when
    out of range (limit 1..100, offset >= 0). Missing -> defaults."""
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None:
        limit = LIMIT_DEFAULT
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err(errors.ERR_VALIDATION_PAGINATION, "limit must be an integer")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise err(errors.ERR_VALIDATION_PAGINATION, "limit out of range 1..100")

    if offset_raw is None:
        offset = OFFSET_DEFAULT
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err(errors.ERR_VALIDATION_PAGINATION, "offset must be an integer")
        if offset < 0:
            raise err(errors.ERR_VALIDATION_PAGINATION, "offset must be >= 0")

    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at ASC (creation order via _seq tiebreak) and slice."""
    ordered = sorted(records, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [serialize(r) for r in page], total


def require_fields(body, names):
    """Ensure every named field is present and not None. ERR_INVALID_REQUEST."""
    for name in names:
        if name not in body or body[name] is None:
            raise err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % name)


def require_string(body, name):
    require_fields(body, [name])
    val = body[name]
    if not isinstance(val, str) or val == "":
        raise err(errors.ERR_INVALID_REQUEST, "%s must be a non-empty string" % name)
    return val


def require_int(body, name, minimum=None):
    """Required integer. Booleans are rejected (bool is a subclass of int)."""
    require_fields(body, [name])
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(errors.ERR_INVALID_REQUEST, "%s must be an integer" % name)
    if minimum is not None and val < minimum:
        raise err(errors.ERR_INVALID_REQUEST, "%s must be >= %s" % (name, minimum))
    return val


def optional_int(body, name, default, minimum=None):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(errors.ERR_INVALID_REQUEST, "%s must be an integer" % name)
    if minimum is not None and val < minimum:
        raise err(errors.ERR_INVALID_REQUEST, "%s must be >= %s" % (name, minimum))
    return val


def require_bool(body, name):
    require_fields(body, [name])
    val = body[name]
    if not isinstance(val, bool):
        raise err(errors.ERR_INVALID_REQUEST, "%s must be a boolean" % name)
    return val


def require_enum(body, name, allowed, default=None):
    if name not in body or body[name] is None:
        if default is not None:
            return default
        raise err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % name)
    val = body[name]
    if val not in allowed:
        raise err(errors.ERR_INVALID_REQUEST, "%s must be one of %s" % (name, sorted(allowed)))
    return val


def validate_occ_field(body, field_name, required=False):
    """Body well-formedness for an OCC version field (priority 6 /
    ERR_INVALID_REQUEST). When required, the field must be present and a plain
    integer. This runs BEFORE state/dependency checks so a malformed body
    surfaces ahead of a state-precondition failure (PRD §2.9). Returns the
    parsed value or None when absent (and not required)."""
    if field_name not in body or body[field_name] is None:
        if required:
            raise err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % field_name)
        return None
    expected = body[field_name]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err(errors.ERR_INVALID_REQUEST, "%s must be an integer" % field_name)
    return expected


def match_occ(record, body, field_name):
    """OCC version-match check (priority 9 / ERR_STALE_VERSION). Runs AFTER
    state and dependency checks. Assumes validate_occ_field already verified
    presence/type. When the field is absent, the check is skipped."""
    if field_name not in body or body[field_name] is None:
        return
    expected = body[field_name]
    if expected != record.get("version"):
        raise err(errors.ERR_STALE_VERSION,
                  "%s does not match current version" % field_name)
