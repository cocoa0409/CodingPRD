"""Request-shape validation helpers and domain enumerations."""

from datetime import datetime, timezone

from flask import request

from errors import api_error

ROLES = [
    "ProductEngineer",
    "ProcurementSpecialist",
    "SupplierRep",
    "TestTechnician",
    "QualityManager",
    "MonogramAuditor",
    "FieldServiceCoordinator",
]

VALVE_TYPES = ["GATE", "BALL", "BUTTERFLY", "CONTROL"]
PRESSURE_CLASSES = [150, 300, 600, 900, 1500, 2500]
MATERIAL_GRADES = ["WCB", "CF8M", "LCC", "A105", "F316"]
SEAT_TYPES = ["SOFT", "METAL"]
SPECIAL_SERVICES = ["FIRE_SAFE", "CRYOGENIC", "FUGITIVE_EMISSION"]
PROCESSES = ["CASTING", "FORGING"]
COMPONENT_TYPES = ["BODY", "BONNET", "BALL", "DISC", "STEM", "SEAT_RING"]
TEST_TYPES = ["SHELL", "SEAT", "FUNCTIONAL", "FIRE_SAFE", "CRYOGENIC", "FUGITIVE_EMISSION"]
TEST_RESULTS = ["PASS", "FAIL"]
ACTUATOR_TYPES = ["PNEUMATIC", "HYDRAULIC", "ELECTRIC"]
SIZING_BASES = ["CATALOG", "DATASHEET"]
DOC_TYPES = [
    "MATERIAL_TEST_REPORT",
    "TEST_CERTIFICATE",
    "DIMENSIONAL_REPORT",
    "NDE_REPORT",
    "ACTUATOR_DATASHEET",
    "DECLARATION_OF_CONFORMITY",
]
BUILD_STATUSES = ["BLANK", "MACHINED", "ASSEMBLED", "PACKAGED", "SHIPPED", "REWORK"]
BUILD_SEQUENCE = ["BLANK", "MACHINED", "ASSEMBLED", "PACKAGED", "SHIPPED"]
CERT_STATUSES = [
    "UNCERTIFIED",
    "TESTS_IN_PROGRESS",
    "TESTS_PASSED",
    "TESTS_FAILED",
    "CERTIFIED",
    "DECERTIFIED",
]
SERVICE_STATUSES = ["NONE", "OPEN", "PARTS_RESERVED", "IN_SERVICE", "SERVICED"]
DECERT_REASONS = [
    "MANUAL",
    "LOT_QUARANTINE",
    "LICENSE_SUSPENDED",
    "LICENSE_DENIED",
    "SPECIAL_SERVICE_REVOKED",
]
TORQUE_SOURCES = ["CUSTOMER_STATED", "VENDOR_MEASURED"]
SEVERITIES = ["MAJOR", "MINOR"]


def invalid(message):
    return api_error("ERR_INVALID_REQUEST", message)


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        raw = request.get_data(cache=True, as_text=True)
        if raw and raw.strip():
            raise invalid("request body is not valid JSON")
        return {}
    if not isinstance(data, dict):
        raise invalid("request body must be a JSON object")
    return data


def present(body, name):
    return name in body and body[name] is not None


def get_string(body, name, required=True, default=None):
    if not present(body, name):
        if required:
            raise invalid("field '%s' is required" % name)
        return default
    value = body[name]
    if not isinstance(value, str) or value.strip() == "":
        raise invalid("field '%s' must be a non-empty string" % name)
    return value


def get_enum(body, name, allowed, required=True, default=None):
    value = get_string(body, name, required=required, default=None)
    if value is None:
        return default
    if value not in allowed:
        raise invalid("field '%s' must be one of %s" % (name, ", ".join(allowed)))
    return value


def get_int(body, name, required=True, default=None, minimum=None, maximum=None, allowed=None):
    if not present(body, name):
        if required:
            raise invalid("field '%s' is required" % name)
        return default
    value = body[name]
    if isinstance(value, bool):
        raise invalid("field '%s' must be an integer" % name)
    if isinstance(value, float):
        if not float(value).is_integer():
            raise invalid("field '%s' must be an integer" % name)
        value = int(value)
    if not isinstance(value, int):
        raise invalid("field '%s' must be an integer" % name)
    if allowed is not None and value not in allowed:
        raise invalid(
            "field '%s' must be one of %s" % (name, ", ".join(str(a) for a in allowed))
        )
    if minimum is not None and value < minimum:
        raise invalid("field '%s' must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        raise invalid("field '%s' must be <= %s" % (name, maximum))
    return value


def get_number(body, name, required=True, default=None, minimum=None, exclusive_minimum=None):
    if not present(body, name):
        if required:
            raise invalid("field '%s' is required" % name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid("field '%s' must be a number" % name)
    value = float(value)
    if minimum is not None and value < minimum:
        raise invalid("field '%s' must be >= %s" % (name, minimum))
    if exclusive_minimum is not None and value <= exclusive_minimum:
        raise invalid("field '%s' must be > %s" % (name, exclusive_minimum))
    return value


def get_bool(body, name, required=True, default=None):
    if not present(body, name):
        if required:
            raise invalid("field '%s' is required" % name)
        return default
    value = body[name]
    if not isinstance(value, bool):
        raise invalid("field '%s' must be a boolean" % name)
    return value


def get_enum_array(body, name, allowed, required=True, default=None):
    if not present(body, name):
        if required:
            raise invalid("field '%s' is required" % name)
        return list(default) if default is not None else None
    value = body[name]
    if not isinstance(value, list):
        raise invalid("field '%s' must be an array" % name)
    seen = set()
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            raise invalid(
                "field '%s' may only contain %s" % (name, ", ".join(allowed))
            )
        if item in seen:
            raise invalid("field '%s' must not contain duplicates" % name)
        seen.add(item)
    return list(value)


def parse_iso(value, name):
    if not isinstance(value, str) or not value.strip():
        raise invalid("field '%s' must be an ISO 8601 timestamp" % name)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise invalid("field '%s' must be an ISO 8601 timestamp" % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def get_datetime(body, name, required=True):
    """Returns (raw_string, datetime) so the raw input can be echoed back."""
    if not present(body, name):
        if required:
            raise invalid("field '%s' is required" % name)
        return None, None
    raw = body[name]
    return raw, parse_iso(raw, name)


def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise api_error("ERR_INVALID_PAGINATION", "limit must be an integer")
        if str(raw).strip() != str(limit):
            raise api_error("ERR_INVALID_PAGINATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise api_error("ERR_INVALID_PAGINATION", "limit must be between 1 and 100")
    elif "limit" in args:
        raise api_error("ERR_INVALID_PAGINATION", "limit must be an integer")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise api_error("ERR_INVALID_PAGINATION", "offset must be an integer")
        if str(raw).strip() != str(offset):
            raise api_error("ERR_INVALID_PAGINATION", "offset must be an integer")
        if offset < 0:
            raise api_error("ERR_INVALID_PAGINATION", "offset must be >= 0")
    elif "offset" in args:
        raise api_error("ERR_INVALID_PAGINATION", "offset must be an integer")
    return limit, offset


def filter_value(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset: offset + limit], total
