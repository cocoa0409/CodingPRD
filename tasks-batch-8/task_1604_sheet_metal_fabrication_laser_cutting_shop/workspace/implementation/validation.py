"""Request validation: body shape (tier 2), path/FK existence (tier 3), field helpers."""
from flask import request

from errors import ApiError

# Field validators: kind -> predicate
def _is_string(v):
    return isinstance(v, str)


def _is_integer(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and v == v and v not in (float("inf"), float("-inf")))


def _is_boolean(v):
    return isinstance(v, bool)


LINE_SCHEMA = {
    "grade_id": ("string", True, None),
    "thickness_mm": ("number", True, None),
    "bbox_width_mm": ("integer", True, None),
    "bbox_height_mm": ("integer", True, None),
    "hole_count": ("integer", False, None),
    "hole_diameter_mm": ("number", False, None),
    "corner_fillet_count": ("integer", False, None),
    "bend_count": ("integer", False, None),
    "weld_inches": ("number", False, None),
    "finish": ("string", False, None),
    "qty": ("integer", True, None),
}


def _check(kind, value, enum_values):
    if kind == "string":
        return _is_string(value)
    if kind == "integer":
        return _is_integer(value)
    if kind == "number":
        return _is_number(value)
    if kind == "boolean":
        return _is_boolean(value)
    if kind == "enum":
        return _is_string(value) and value in enum_values
    if kind == "lines":
        if not isinstance(value, list):
            return False
        for item in value:
            validate_schema(item, LINE_SCHEMA)
        return True
    if kind == "tiers":
        if not isinstance(value, list):
            return False
        for item in value:
            validate_schema(item, {
                "max_thickness_mm": ("number", True, None),
                "tier_index": ("integer", True, None),
            })
        return True
    return False


def validate_schema(body, schema):
    """Raise ERR_INVALID_REQUEST unless body is a dict matching schema exactly."""
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    for key in body:
        if key not in schema:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Unknown field: %s" % key)
    for field, (kind, required, enum_values) in schema.items():
        if field not in body:
            if required:
                raise ApiError("ERR_INVALID_REQUEST", 400, "Missing required field: %s" % field)
            continue
        if not _check(kind, body[field], enum_values):
            raise ApiError("ERR_INVALID_REQUEST", 400, "Field %s has wrong type or value" % field)


def parse_body(schema, allow_empty=True):
    """Parse and validate the JSON request body against schema.

    allow_empty=True permits a missing body only when no required fields exist.
    """
    has_required = any(req for _, req, _ in schema.values())
    body = request.get_json(silent=True)
    if body is None:
        if allow_empty and not has_required:
            body = {}
        else:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    validate_schema(body, schema)
    return body


def require_path_entity(table, entity_id):
    entity = table.get(entity_id)
    if entity is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found: %s" % entity_id)
    return entity


def resolve_fk(table, fk_id, field_name):
    entity = table.get(fk_id)
    if entity is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced %s does not exist" % field_name)
    return entity


def valid_enum(body, field, allowed, error_id="ERR_INVALID_REQUEST", http=400):
    value = body.get(field)
    if value not in allowed:
        raise ApiError(error_id, http, "Field %s must be one of %s" % (field, ",".join(allowed)))
    return value


def valid_integer(body, field, min_value=None, error_id="ERR_INVALID_REQUEST", http=400):
    value = body.get(field)
    if not _is_integer(value) or (min_value is not None and value < min_value):
        raise ApiError(error_id, http, "Field %s must be an integer >= %s" % (field, min_value))
    return value


def valid_number(body, field, error_id="ERR_INVALID_REQUEST", http=400):
    value = body.get(field)
    if not _is_number(value):
        raise ApiError(error_id, http, "Field %s must be a number" % field)
    return value
