"""Common-field discipline and validation helpers shared across entities.

PRD §2.4: every resource carries a system-generated `id` (UUID, no prefix),
`created_at` (ISO 8601 UTC, 3 fractional digits), `updated_at` (refreshed on
every mutation), and an integer `version` that begins at 1 and increments by
one on every mutation. There are no version-less resources.
"""
import db
import errors


def base_record(extra):
    """Build a new record with the common system fields populated.

    version begins at 1 (its initial value) and increments on every mutation.
    """
    ts = db.now_iso()
    rec = {
        "id": db.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    rec.update(extra)
    return rec


def touch(rec):
    """Mark a record mutated: refresh updated_at and bump version (PRD §2.4/§2.5)."""
    rec["updated_at"] = db.now_iso()
    rec["version"] = rec["version"] + 1


# --- Request-body field extraction & validation ------------------------------

def require_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v.strip() == "":
        raise errors.invalid_request("Field '%s' is required." % field)
    return v


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        raise errors.invalid_request("Field '%s' must be a string." % field)
    return v


def require_int(body, field, min_value=None):
    if field not in body or body[field] is None:
        raise errors.invalid_request("Field '%s' is required." % field)
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.invalid_request("Field '%s' must be an integer." % field)
    if min_value is not None and v < min_value:
        raise errors.invalid_request("Field '%s' must be >= %s." % (field, min_value))
    return v


def opt_int(body, field, default=None, min_value=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.invalid_request("Field '%s' must be an integer." % field)
    if min_value is not None and v < min_value:
        raise errors.invalid_request("Field '%s' must be >= %s." % (field, min_value))
    return v


def opt_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise errors.invalid_request("Field '%s' must be a boolean." % field)
    return v


def require_enum(body, field, members):
    v = require_str(body, field)
    if v not in members:
        raise errors.invalid_request(
            "Field '%s' must be one of %s." % (field, sorted(members)))
    return v
