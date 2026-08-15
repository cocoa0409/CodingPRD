"""Rung 3 of the validation ladder (PRD 2.8): request-body schema checks.

Required fields present, types correct, enum members valid, minimum lengths
met, ends_at strictly after starts_at, distance_miles greater than 0,
required_documents non-empty, diversion unit_type present exactly when scope
is SPECIFIC_UNIT.  All failures are 400: ERR_INVALID_REQUEST, or the dedicated
ERR_NARRATIVE_TOO_SHORT / ERR_FINDINGS_TOO_SHORT for the two length rules.
"""

from flask import request

from .errors import fail

_ERR = "ERR_INVALID_REQUEST"


def body():
    """The request JSON object; absent or malformed bodies read as {}.

    A missing required field out of {} fails as ERR_INVALID_REQUEST, which is
    the same error a malformed body would draw, so no distinction is needed.
    """
    data = request.get_json(silent=True, force=True)
    if not isinstance(data, dict):
        return {}
    return data


def _present(body_dict, field):
    return field in body_dict and body_dict[field] is not None


def need_str(body_dict, field):
    if not _present(body_dict, field) or not isinstance(body_dict[field], str):
        fail(_ERR, "Field '%s' is required and must be a string." % field, 400)
    return body_dict[field]


def opt_str(body_dict, field, default=None):
    if not _present(body_dict, field):
        return default
    if not isinstance(body_dict[field], str):
        fail(_ERR, "Field '%s' must be a string." % field, 400)
    return body_dict[field]


def need_bool(body_dict, field):
    if not _present(body_dict, field) or not isinstance(body_dict[field], bool):
        fail(_ERR, "Field '%s' is required and must be a boolean." % field, 400)
    return body_dict[field]


def opt_bool(body_dict, field, default=False):
    if not _present(body_dict, field):
        return default
    if not isinstance(body_dict[field], bool):
        fail(_ERR, "Field '%s' must be a boolean." % field, 400)
    return body_dict[field]


def need_int(body_dict, field):
    value = body_dict.get(field)
    if not _present(body_dict, field) or isinstance(value, bool) or not isinstance(value, int):
        fail(_ERR, "Field '%s' is required and must be an integer." % field, 400)
    return value


def need_number(body_dict, field):
    value = body_dict.get(field)
    if (not _present(body_dict, field) or isinstance(value, bool)
            or not isinstance(value, (int, float))):
        fail(_ERR, "Field '%s' is required and must be a number." % field, 400)
    return value


def need_enum(body_dict, field, members):
    value = need_str(body_dict, field)
    if value not in members:
        fail(_ERR, "Field '%s' must be one of %s." % (field, ", ".join(members)), 400)
    return value


def opt_enum(body_dict, field, members, default=None):
    if not _present(body_dict, field):
        return default
    return need_enum(body_dict, field, members)


def need_str_list(body_dict, field):
    if not _present(body_dict, field) or not isinstance(body_dict[field], list):
        fail(_ERR, "Field '%s' is required and must be an array." % field, 400)
    items = body_dict[field]
    for item in items:
        if not isinstance(item, str):
            fail(_ERR, "Field '%s' must be an array of strings." % field, 400)
    return items


def opt_str_list(body_dict, field, default=None):
    if not _present(body_dict, field):
        return default
    return need_str_list(body_dict, field)


def need_enum_list(body_dict, field, members):
    items = need_str_list(body_dict, field)
    for item in items:
        if item not in members:
            fail(_ERR, "Field '%s' contains an invalid member '%s'." % (field, item), 400)
    return items


def need_min_length(value, field, minimum, error_id):
    if len(value) < minimum:
        fail(error_id, "Field '%s' must be at least %d characters." % (field, minimum), 400)
    return value
