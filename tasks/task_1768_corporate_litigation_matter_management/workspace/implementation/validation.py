"""Request-shape (priority 23) and scalar field-constraint (priority 11) checks."""
from db import parse_dt
from errors import ERR_FIELD_CONSTRAINT, ERR_INVALID_REQUEST, raise_err


def _well_typed(value, ftype):
    if ftype == "str":
        return isinstance(value, str)
    if ftype == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if ftype == "bool":
        return isinstance(value, bool)
    if ftype == "datetime":
        return isinstance(value, str) and parse_dt(value) is not None
    if ftype == "enum":
        return isinstance(value, str)
    return True


def check_constraints_11(body, spec):
    """Priority 11: field-shape constraints on present, well-typed fields.

    Enum membership, numeric bounds. Cross-field constraints are enforced
    inline by the handlers.
    """
    if not isinstance(body, dict):
        return
    for name, fs in spec.items():
        if name not in body:
            continue
        value = body[name]
        if not _well_typed(value, fs["type"]):
            continue  # malformed scalars are reported at priority 23
        if fs["type"] == "enum" and value not in fs["enum"]:
            raise_err(
                ERR_FIELD_CONSTRAINT,
                "Field '%s' must be one of %s." % (name, ", ".join(fs["enum"])),
            )
        if fs["type"] == "int":
            if "min" in fs and value < fs["min"]:
                raise_err(ERR_FIELD_CONSTRAINT, "Field '%s' is below its minimum." % name)
            if "max" in fs and value > fs["max"]:
                raise_err(ERR_FIELD_CONSTRAINT, "Field '%s' exceeds its maximum." % name)
            if fs.get("positive") and value <= 0:
                raise_err(ERR_FIELD_CONSTRAINT, "Field '%s' must be positive." % name)


def check_shape_23(body, spec, conditional_required=None):
    """Priority 23: request-shape well-formedness.

    Rejects non-object bodies, undeclared fields, missing required fields,
    empty strings where non-empty is required, and malformed scalar types.
    """
    if not isinstance(body, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    for key in body:
        if key not in spec:
            raise_err(ERR_INVALID_REQUEST, "Undeclared field '%s' in request body." % key)
    conditional_required = conditional_required or {}
    for name, fs in spec.items():
        required = fs.get("required", False)
        if name in conditional_required:
            required = conditional_required[name](body)
        if required and name not in body:
            raise_err(ERR_INVALID_REQUEST, "Missing required field '%s'." % name)
        if name not in body:
            continue
        value = body[name]
        if not _well_typed(value, fs["type"]):
            raise_err(ERR_INVALID_REQUEST, "Field '%s' has a malformed value." % name)
        if fs["type"] == "str" and fs.get("non_empty", True) and value == "":
            raise_err(ERR_INVALID_REQUEST, "Field '%s' must be a non-empty string." % name)
        if fs["type"] == "enum" and fs.get("non_empty", True) and value == "":
            raise_err(ERR_INVALID_REQUEST, "Field '%s' must be non-empty." % name)


def reject_extra_fields(body, allowed):
    """Priority 23 for action endpoints that declare no (or few) inputs."""
    if not isinstance(body, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    for key in body:
        if key not in allowed:
            raise_err(ERR_INVALID_REQUEST, "Undeclared field '%s' in request body." % key)
