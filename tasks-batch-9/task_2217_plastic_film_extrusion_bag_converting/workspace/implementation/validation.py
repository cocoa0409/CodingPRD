"""Request-shape, pagination, path and foreign-key screening (PRD §2.7 steps 3-7)."""

from datetime import datetime, timezone

from flask import request

from errors import ApiError
from response import array_response
from store import serialize_all, store

_MISSING = object()


# ---------------------------------------------------------------- body -----
def parse_body(required=False):
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "A JSON request body is required.")
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


def bad(field, why):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, why))


def _present(body, key, required, default):
    if key not in body or body[key] is None:
        if required:
            bad(key, "is required")
        return _MISSING if default is _MISSING else default
    return body[key]


def get_str(body, key, required=True, default=None, min_len=1, max_len=None):
    if key not in body or body[key] is None:
        if required:
            bad(key, "is required")
        return default
    value = body[key]
    if not isinstance(value, str):
        bad(key, "must be a string")
    if min_len is not None and len(value) < min_len:
        bad(key, "must not be empty")
    if max_len is not None and len(value) > max_len:
        bad(key, "must be at most %d characters" % max_len)
    return value


def get_id(body, key, required=True):
    value = _present(body, key, required, None)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        bad(key, "must be a non-empty string identifier")
    return value


def get_enum(body, key, members, required=True, default=None):
    value = _present(body, key, required, default)
    if value is None:
        return None
    if not isinstance(value, str) or value not in members:
        bad(key, "must be one of %s" % ", ".join(members))
    return value


def get_bool(body, key, required=False, default=False):
    value = _present(body, key, required, default)
    if value is None:
        return default
    if not isinstance(value, bool):
        bad(key, "must be a boolean")
    return value


def get_num(body, key, required=True, default=None, gt=None, ge=None, lt=None, le=None):
    value = _present(body, key, required, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad(key, "must be a number")
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        bad(key, "must be a finite number")
    if gt is not None and not value > gt:
        bad(key, "must be greater than %s" % gt)
    if ge is not None and not value >= ge:
        bad(key, "must be greater than or equal to %s" % ge)
    if lt is not None and not value < lt:
        bad(key, "must be less than %s" % lt)
    if le is not None and not value <= le:
        bad(key, "must be less than or equal to %s" % le)
    return value


def get_int(body, key, required=True, default=None, gt=None, ge=None, lt=None, le=None):
    value = _present(body, key, required, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        bad(key, "must be an integer")
    if gt is not None and not value > gt:
        bad(key, "must be greater than %s" % gt)
    if ge is not None and not value >= ge:
        bad(key, "must be greater than or equal to %s" % ge)
    if lt is not None and not value < lt:
        bad(key, "must be less than %s" % lt)
    if le is not None and not value <= le:
        bad(key, "must be less than or equal to %s" % le)
    return value


def parse_datetime(value, key):
    if not isinstance(value, str) or not value:
        bad(key, "must be an ISO 8601 datetime string")
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        bad(key, "must be an ISO 8601 datetime string")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def get_datetime(body, key, required=True):
    value = _present(body, key, required, None)
    if value is None:
        return None, None
    return value, parse_datetime(value, key)


# ---------------------------------------------------------- pagination -----
def _query_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_PAGINATION", "%s must be an integer." % name)
    value = int(text)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_PAGINATION", "%s must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_PAGINATION", "%s must be at most %d." % (name, maximum))
    return value


def pagination():
    limit = _query_int("limit", 10, 1, 100)
    offset = _query_int("offset", 0, 0, None)
    return limit, offset


def _matches(actual, raw):
    if isinstance(actual, bool):
        return str(actual).lower() == raw.strip().lower()
    if actual is None:
        return raw.strip().lower() in ("null", "none", "")
    return str(actual) == raw


def list_endpoint(collection, filter_fields):
    """Paginated, created_at-ascending collection read with equality filters."""
    limit, offset = pagination()
    items = store.sorted_values(collection)
    for field in filter_fields:
        raw = request.args.get(field)
        if raw is None:
            continue
        items = [e for e in items if _matches(e.get(field), raw)]
    total = len(items)
    page = items[offset : offset + limit]
    return array_response(serialize_all(page), limit, offset, total)


# ------------------------------------------------------- path / FK ids -----
_ENTITY_LOOKUP = {
    "product": ("products", "ERR_PRODUCT_NOT_FOUND"),
    "resin_grade": ("resin_grades", "ERR_RESIN_GRADE_NOT_FOUND"),
    "blend_recipe": ("blend_recipes", "ERR_BLEND_RECIPE_NOT_FOUND"),
    "extrusion_line": ("extrusion_lines", "ERR_EXTRUSION_LINE_NOT_FOUND"),
    "extrusion_run": ("extrusion_runs", "ERR_EXTRUSION_RUN_NOT_FOUND"),
    "film_roll": ("film_rolls", "ERR_FILM_ROLL_NOT_FOUND"),
    "regrind_pool": ("regrind_pools", "ERR_REGRIND_POOL_NOT_FOUND"),
    "regrind_transaction": ("regrind_transactions", "ERR_REGRIND_TRANSACTION_NOT_FOUND"),
    "print_press": ("print_presses", "ERR_PRINT_PRESS_NOT_FOUND"),
    "plate_set": ("plate_sets", "ERR_PLATE_SET_NOT_FOUND"),
    "print_job": ("print_jobs", "ERR_PRINT_JOB_NOT_FOUND"),
    "bag_lot": ("bag_lots", "ERR_BAG_LOT_NOT_FOUND"),
    "compliance_dossier": ("compliance_dossiers", "ERR_DOSSIER_NOT_FOUND"),
}

# Foreign keys are resolved in exactly this order (PRD §2.7 rule 6).
FK_ORDER = (
    "product_id",
    "resin_grade_id",
    "blend_recipe_id",
    "line_id",
    "extrusion_run_id",
    "pool_id",
    "film_roll_id",
    "plate_set_id",
    "press_id",
    "print_job_id",
    "bag_lot_id",
    "supersedes_recipe_id",
)

FK_ENTITY = {
    "product_id": "product",
    "resin_grade_id": "resin_grade",
    "blend_recipe_id": "blend_recipe",
    "line_id": "extrusion_line",
    "extrusion_run_id": "extrusion_run",
    "pool_id": "regrind_pool",
    "film_roll_id": "film_roll",
    "plate_set_id": "plate_set",
    "press_id": "print_press",
    "print_job_id": "print_job",
    "bag_lot_id": "bag_lot",
    "supersedes_recipe_id": "blend_recipe",
}


def fetch(entity_kind, entity_id):
    collection_name, error_id = _ENTITY_LOOKUP[entity_kind]
    entity = getattr(store, collection_name).get(entity_id)
    if entity is None:
        raise ApiError(error_id, "%s '%s' was not found." % (entity_kind, entity_id))
    return entity


def resolve_fks(values):
    """values: mapping of fk field name -> raw id (None allowed for optional)."""
    resolved = {}
    for field in FK_ORDER:
        if field not in values:
            continue
        raw = values[field]
        if raw is None:
            resolved[field] = None
            continue
        resolved[field] = fetch(FK_ENTITY[field], raw)
    return resolved


def require_unique(collection, field, value):
    for entity in collection.values():
        if entity.get(field) == value:
            raise ApiError(
                "ERR_DUPLICATE_CODE", "%s '%s' is already in use." % (field, value)
            )
