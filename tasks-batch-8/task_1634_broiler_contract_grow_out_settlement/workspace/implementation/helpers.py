"""Shared route helpers: existence, input validation, uniqueness.

Validation failures use the scaffold's error catalog. The catalog defines no
generic malformed-input error, so missing/invalid fields map to the nearest
cataloged 422 for the endpoint family (ERR_QUANTITY_INVALID for quantities and
general payload sanity, ERR_LOAN_TERMS_INVALID for loan terms).
"""
from errors import ApiError
import utils


def get_or_404(table, rid, what="Resource"):
    rec = table.get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "%s %s not found." % (what, rid), 404)
    return rec


def _invalid(field, message=None, error_id="ERR_QUANTITY_INVALID", status=422):
    raise ApiError(error_id, message or ("Field '%s' is missing or invalid." % field), status)


def need_str(b, field, error_id="ERR_QUANTITY_INVALID", status=422):
    v = b.get(field)
    if not isinstance(v, str) or not v.strip():
        _invalid(field, "Field '%s' is required and must be a non-empty string." % field, error_id, status)
    return v


def opt_str(b, field, default=None):
    v = b.get(field)
    return v if isinstance(v, str) else default


def need_int(b, field, error_id="ERR_QUANTITY_INVALID", status=422):
    v = b.get(field)
    if not utils.is_int(v):
        _invalid(field, "Field '%s' is required and must be an integer." % field, error_id, status)
    return v


def need_date(b, field, error_id="ERR_QUANTITY_INVALID", status=422):
    v = b.get(field)
    if utils.parse_date(v) is None:
        _invalid(field, "Field '%s' must be an ISO date (YYYY-MM-DD)." % field, error_id, status)
    return v


def need_instant(b, field, error_id="ERR_QUANTITY_INVALID", status=422):
    v = b.get(field)
    if utils.parse_instant(v) is None:
        _invalid(field, "Field '%s' must be an ISO 8601 datetime." % field, error_id, status)
    return v


def need_enum(b, field, allowed, error_id="ERR_QUANTITY_INVALID", status=422):
    v = b.get(field)
    if v not in allowed:
        _invalid(field, "Field '%s' must be one of %s." % (field, list(allowed)), error_id, status)
    return v


def check_unique(records, field, value, what, scope_field=None, scope_value=None):
    """ERR_DUPLICATE when value already taken (optionally within a scope)."""
    for rec in records:
        if scope_field is not None and rec.get(scope_field) != scope_value:
            continue
        if rec.get(field) == value:
            raise ApiError(
                "ERR_DUPLICATE",
                "%s '%s' already exists." % (what, value),
                409,
            )
