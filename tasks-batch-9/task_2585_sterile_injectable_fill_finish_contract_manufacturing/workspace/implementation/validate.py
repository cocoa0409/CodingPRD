"""Request-shape and enum validation.

Two ordered phases mirroring PRD 2.10 rungs 6 and 7:

  rung 6  ERR_INVALID_REQUEST   (400) - required field absent or null, wrong
                                        JSON type, non-array array field, or a
                                        numeric field outside its declared range
  rung 7  ERR_INVALID_ENUM_VALUE (422) - an enum-typed input carrying a value
                                        outside its declared constraint set

Both phases run over the whole field spec before the next rung is consulted,
so a body that is simultaneously mis-shaped and carrying a bad enum reports
the mis-shape.
"""

from common import ApiError, parse_dt

# --------------------------------------------------------------------------
# Enum domains, taken verbatim from the entity constraint sets
# --------------------------------------------------------------------------

DOSAGE_FORMS = ("VIAL", "PRESYRINGE")
SUITE_GRADES = ("A", "B", "C")
TECH_STAGES = ("NOT_STARTED", "GAP_ASSESSMENT", "ENGINEERING_RUN", "COMPLETE")
ANALYTICAL_STATUSES = ("NOT_STARTED", "IN_TRANSFER", "VALIDATED")
QUALIFICATION_TYPES = ("GOWNING", "ASEPTIC_INTERVENTION", "VISUAL_INSPECTION")
COMPONENT_TYPES = ("VIAL", "STOPPER", "SYRINGE", "PLUNGER")
CHECK_TYPES = ("FILL_WEIGHT", "CCI", "VISUAL_INSPECTION")
SAMPLE_TYPES = ("VIABLE_AIR", "SURFACE", "PERSONNEL_GLOVE")
DEVIATION_CLASSES = ("MINOR", "MAJOR", "CRITICAL")
CAPA_OUTCOMES = ("APPROVED", "REJECTED")
MEDIA_FILL_OUTCOMES = ("PASSED", "FAILED")
STERILIZATION_OUTCOMES = ("RELEASED", "REJECTED")
QP_DECISIONS = ("RELEASE", "REJECT", "QUARANTINE")
AUDIT_KINDS = ("CLIENT_AUDIT", "INSPECTION_READINESS")
HOST_OUTCOMES = ("HOSTED", "DEFERRED")
READINESS_VARIANTS = ("INTAKE_FORECAST", "GMP_AUDIT")


def bad_request(detail):
    return ApiError("ERR_INVALID_REQUEST", 400, detail)


def bad_enum(field):
    return ApiError(
        "ERR_INVALID_ENUM_VALUE",
        422,
        "Field '%s' carries a value outside its declared enum set." % field,
    )


# --------------------------------------------------------------------------
# Field descriptors
# --------------------------------------------------------------------------


def f_str(name, min_len=1, max_len=None, required=True):
    return {
        "name": name,
        "kind": "str",
        "required": required,
        "min_len": min_len,
        "max_len": max_len,
    }


def f_int(name, minimum=None, maximum=None, required=True, default=None):
    return {
        "name": name,
        "kind": "int",
        "required": required,
        "min": minimum,
        "max": maximum,
        "default": default,
    }


def f_num(name, minimum=None, exclusive_min=False, required=True):
    return {
        "name": name,
        "kind": "num",
        "required": required,
        "min": minimum,
        "exclusive_min": exclusive_min,
    }


def f_dt(name, required=True):
    return {"name": name, "kind": "dt", "required": required}


def f_enum(name, values, required=True):
    return {"name": name, "kind": "enum", "required": required, "values": values}


def f_array(name, item="any", required=True, min_items=0, default=None):
    return {
        "name": name,
        "kind": "array",
        "required": required,
        "item": item,
        "min_items": min_items,
        "default": default,
    }


def f_id(name, required=True):
    """A foreign-key string; existence is a separate rung (9)."""
    return {"name": name, "kind": "str", "required": required, "min_len": 1,
            "max_len": None}


# --------------------------------------------------------------------------
# Validation driver
# --------------------------------------------------------------------------


def _is_int(value):
    # A JSON boolean is an int in Python; it is not an integer here.
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool))


def _check_shape(spec, body, out):
    name = spec["name"]
    present = name in body and body[name] is not None
    if not present:
        if spec["required"]:
            raise bad_request("Field '%s' is required." % name)
        out[name] = spec.get("default")
        if spec["kind"] == "array" and out[name] is None:
            out[name] = []
        return
    value = body[name]
    kind = spec["kind"]
    if kind in ("str", "enum"):
        if not isinstance(value, str):
            raise bad_request("Field '%s' must be a string." % name)
        if kind == "str":
            if spec.get("min_len") is not None and len(value) < spec["min_len"]:
                raise bad_request("Field '%s' is shorter than its minimum." % name)
            if spec.get("max_len") is not None and len(value) > spec["max_len"]:
                raise bad_request("Field '%s' is longer than its maximum." % name)
        out[name] = value
    elif kind == "int":
        if not _is_int(value):
            raise bad_request("Field '%s' must be an integer." % name)
        if spec.get("min") is not None and value < spec["min"]:
            raise bad_request("Field '%s' is below its declared minimum." % name)
        if spec.get("max") is not None and value > spec["max"]:
            raise bad_request("Field '%s' is above its declared maximum." % name)
        out[name] = value
    elif kind == "num":
        if not _is_num(value):
            raise bad_request("Field '%s' must be a number." % name)
        if spec.get("min") is not None:
            if spec.get("exclusive_min") and not value > spec["min"]:
                raise bad_request("Field '%s' must be greater than %s."
                                  % (name, spec["min"]))
            if not spec.get("exclusive_min") and value < spec["min"]:
                raise bad_request("Field '%s' is below its declared minimum." % name)
        out[name] = value
    elif kind == "dt":
        if not isinstance(value, str):
            raise bad_request("Field '%s' must be an ISO 8601 string." % name)
        parsed = parse_dt(value)
        if parsed is None:
            raise bad_request("Field '%s' is not a valid ISO 8601 instant." % name)
        out[name] = parsed
        out["_raw_" + name] = value
    elif kind == "array":
        if not isinstance(value, list):
            raise bad_request("Field '%s' must be an array." % name)
        if len(value) < spec.get("min_items", 0):
            raise bad_request("Field '%s' has too few elements." % name)
        if spec["item"] == "str":
            for item in value:
                if not isinstance(item, str):
                    raise bad_request("Field '%s' must contain only strings." % name)
        elif spec["item"] == "num":
            for item in value:
                if not _is_num(item):
                    raise bad_request("Field '%s' must contain only numbers." % name)
        out[name] = list(value)
    else:  # pragma: no cover - defensive
        out[name] = value


def parse_body(body, specs):
    """Run rung 6 across every field, then rung 7 across the enum fields."""
    if body is None or not isinstance(body, dict):
        body = {}
    out = {}
    for spec in specs:
        _check_shape(spec, body, out)
    for spec in specs:
        if spec["kind"] != "enum":
            continue
        value = out.get(spec["name"])
        if value is None:
            continue
        if value not in spec["values"]:
            raise bad_enum(spec["name"])
    return out


# --------------------------------------------------------------------------
# Pagination (PRD 2.3, rung 8)
# --------------------------------------------------------------------------

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100


def _parse_pagination_int(raw):
    text = raw.strip()
    if text == "":
        return None
    negative = text.startswith("-")
    digits = text[1:] if (negative or text.startswith("+")) else text
    if not digits.isdigit():
        return None
    return int(text)


def parse_pagination(args):
    limit = PAGINATION_DEFAULT_LIMIT
    offset = 0
    err = ApiError(
        "ERR_INVALID_PAGINATION",
        400,
        "limit must be an integer in 1..100 and offset an integer >= 0.",
    )
    if "limit" in args:
        parsed = _parse_pagination_int(args.get("limit"))
        if parsed is None or parsed < PAGINATION_MIN_LIMIT or parsed > PAGINATION_MAX_LIMIT:
            raise err
        limit = parsed
    if "offset" in args:
        parsed = _parse_pagination_int(args.get("offset"))
        if parsed is None or parsed < 0:
            raise err
        offset = parsed
    return limit, offset
