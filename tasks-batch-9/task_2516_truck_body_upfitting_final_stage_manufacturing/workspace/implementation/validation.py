"""Request-shape validation (PRD section 2.6 step 5) and enum vocabularies.

Everything in here raises ERR_INVALID_REQUEST (422): missing required fields,
unknown enum members, and numeric or date values outside their declared range.
"""

from datetime import date, datetime

from flask import request

from errors import ApiError

# --------------------------------------------------------------------------
# Enum vocabularies (SCAFFOLD entity field definitions)
# --------------------------------------------------------------------------
ELECTRICAL_BUS = ("J1939_CAN", "DISCRETE")
PTO_PROVISION = ("NONE", "CLUTCH_SHIFT", "FULL")
CHASSIS_OWNERSHIP = ("POOL_STOCK", "CUSTOMER_ASSIGNED")
CHASSIS_STATUS = (
    "RECEIVED",
    "INSPECTED",
    "QUARANTINED",
    "ALLOCATED",
    "IN_UPFIT",
    "COMPLETED",
    "RETURNED",
)
BODY_TYPE = ("SERVICE", "DUMP", "FLATBED", "VAN")
EQUIPMENT_CLASS = ("CRANE", "LIFTGATE", "PTO_HOIST", "PTO_PUMP")
MOUNT_ZONE = ("BEHIND_CAB", "BODY_FLOOR", "REAR_OVERHANG")
WORK_BAY_STATUS = ("ACTIVE", "DOWN")
STANDARDIZATION_TIER = ("TIER_A", "TIER_B", "CUSTOM")
CONFIG_STATUS = ("DRAFT", "PUBLISHED", "DEPRECATED")
ORDER_TYPE = ("POOL_STOCK", "CUSTOMER_SPECIFIC")
BODY_INSTALL_STATUS = ("PLANNED", "INSTALLED")
BUILD_STATUS = (
    "DRAFT",
    "ENGINEERING_REVIEW",
    "REWORK",
    "RELEASED",
    "SCHEDULED",
    "IN_BUILD",
    "BUILD_COMPLETE",
    "DELIVERED",
    "CHASSIS_HOLD",
    "CANCELLED",
)
COMPLIANCE_STATUS = ("NOT_STARTED", "DESIGN_CERTIFIED", "MEASURED_CERTIFIED", "LABELED")
CHASSIS_WARRANTY_STATUS = ("INTACT", "CONDITIONAL", "VOIDED")
HYDRAULIC_CIRCUIT = ("NONE", "PRIMARY", "SECONDARY")
HYDRAULIC_STATUS = ("NOT_APPLICABLE", "OK", "DEFICIT")
INSTALLATION_STATUS = ("PLANNED", "INSTALLED", "COMMISSIONED", "REMOVED")
INTERFACE_METHOD = ("BODY_BUILDER_MODULE", "CAN_GATEWAY", "DIRECT_SPLICE")
SIGNAL_SOURCE = ("BODY_CONTROLLER", "J1939_BUS", "DISCRETE_CIRCUIT")
WARRANTY_IMPACT = ("NONE", "CONDITIONAL", "VOIDS")
INTERFACE_STATUS = ("PROPOSED", "APPROVED", "REJECTED", "SUPERSEDED")
SLOT_TYPE = ("BODY_MOUNT", "EQUIPMENT_INTEGRATION", "FINAL_QC")
SLOT_STATUS = ("QUEUED", "SCHEDULED", "IN_BUILD", "CLOSED", "CANCELLED")
CERT_BASIS = ("AS_DESIGNED", "AS_MEASURED")
CERT_STATUS = ("DRAFT", "APPROVED", "VOIDED")
CERT_VOID_REASON = ("COMPONENT_SET_CHANGED", "BODY_MOUNT_CHANGED", "SUPERSEDED_BY_NEWER_DRAFT")
LABEL_TYPE = ("FINAL_STAGE", "ALTERER", "INCOMPLETE_PASSTHROUGH")
RESPONSIBLE_PARTY = ("UPFITTER", "CHASSIS_MANUFACTURER")
FAILURE_SYSTEM = (
    "CHASSIS_ENGINE",
    "CHASSIS_TRANSMISSION",
    "CHASSIS_BRAKES",
    "CHASSIS_ELECTRICAL",
    "BODY_STRUCTURE",
    "BODY_ELECTRICAL",
    "HYDRAULICS",
)
SPLIT_BASIS = ("PROVISIONAL", "FINAL")
CLAIM_STATUS = ("SUBMITTED", "INSPECTED", "ADJUDICATED", "DISPUTED", "PAID")


def invalid(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def body():
    """Parse the JSON body.  An absent body is treated as an empty object so the
    missing-field messages stay specific."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise invalid("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise invalid("Request body must be a JSON object.")
    return parsed


# --------------------------------------------------------------------------
# Scalar field readers
# --------------------------------------------------------------------------
def req_str(payload, name, max_len=None, min_len=1, exact_len=None):
    if name not in payload or payload[name] is None:
        raise invalid("Field '%s' is required." % name)
    value = payload[name]
    if not isinstance(value, str):
        raise invalid("Field '%s' must be a string." % name)
    if exact_len is not None and len(value) != exact_len:
        raise invalid("Field '%s' must be exactly %d characters." % (name, exact_len))
    if min_len is not None and len(value) < min_len:
        raise invalid("Field '%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        raise invalid("Field '%s' must be at most %d characters." % (name, max_len))
    return value


def opt_str(payload, name, default=None, max_len=None):
    if name not in payload or payload[name] is None:
        return default
    value = payload[name]
    if not isinstance(value, str):
        raise invalid("Field '%s' must be a string." % name)
    if max_len is not None and len(value) > max_len:
        raise invalid("Field '%s' must be at most %d characters." % (name, max_len))
    return value


def _as_int(name, value):
    if isinstance(value, bool):
        raise invalid("Field '%s' must be an integer." % name)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and float(value).is_integer():
        return int(value)
    raise invalid("Field '%s' must be an integer." % name)


def req_int(payload, name, minimum=None, maximum=None):
    if name not in payload or payload[name] is None:
        raise invalid("Field '%s' is required." % name)
    value = _as_int(name, payload[name])
    _check_range(name, value, minimum, maximum)
    return value


def opt_int(payload, name, default=None, minimum=None, maximum=None):
    if name not in payload or payload[name] is None:
        return default
    value = _as_int(name, payload[name])
    _check_range(name, value, minimum, maximum)
    return value


def _check_range(name, value, minimum, maximum):
    if minimum is not None and value < minimum:
        raise invalid("Field '%s' must be greater than or equal to %s." % (name, minimum))
    if maximum is not None and value > maximum:
        raise invalid("Field '%s' must be less than or equal to %s." % (name, maximum))


def req_bool(payload, name):
    if name not in payload or payload[name] is None:
        raise invalid("Field '%s' is required." % name)
    value = payload[name]
    if not isinstance(value, bool):
        raise invalid("Field '%s' must be a boolean." % name)
    return value


def opt_bool(payload, name, default=False):
    if name not in payload or payload[name] is None:
        return default
    value = payload[name]
    if not isinstance(value, bool):
        raise invalid("Field '%s' must be a boolean." % name)
    return value


def req_enum(payload, name, allowed):
    value = req_str(payload, name)
    if value not in allowed:
        raise invalid("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def opt_enum(payload, name, allowed, default=None):
    if name not in payload or payload[name] is None:
        return default
    value = payload[name]
    if not isinstance(value, str) or value not in allowed:
        raise invalid("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def parse_date(name, value):
    if not isinstance(value, str):
        raise invalid("Field '%s' must be a YYYY-MM-DD date string." % name)
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except Exception:
        raise invalid("Field '%s' must be a YYYY-MM-DD date string." % name)


def req_date(payload, name):
    if name not in payload or payload[name] is None:
        raise invalid("Field '%s' is required." % name)
    parse_date(name, payload[name])
    return payload[name].strip()


def opt_date(payload, name, default=None):
    if name not in payload or payload[name] is None:
        return default
    parse_date(name, payload[name])
    return payload[name].strip()


def req_id_list(payload, name, default=None):
    if name not in payload or payload[name] is None:
        return list(default) if default is not None else []
    value = payload[name]
    if not isinstance(value, list):
        raise invalid("Field '%s' must be an array." % name)
    for item in value:
        if not isinstance(item, str) or item.strip() == "":
            raise invalid("Field '%s' must be an array of identifiers." % name)
    return value


def req_enum_list(payload, name, allowed, allow_empty=False):
    if name not in payload or payload[name] is None:
        raise invalid("Field '%s' is required." % name)
    value = payload[name]
    if not isinstance(value, list):
        raise invalid("Field '%s' must be an array." % name)
    if not allow_empty and len(value) == 0:
        raise invalid("Field '%s' must not be empty." % name)
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            raise invalid("Field '%s' entries must be one of %s." % (name, ", ".join(allowed)))
    return value


def as_date(value):
    """Convert a stored YYYY-MM-DD string into a date object."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return datetime.strptime(value, "%Y-%m-%d").date()


# --------------------------------------------------------------------------
# Query-string filter readers
# --------------------------------------------------------------------------
def filter_str(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def filter_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        raise invalid("Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def filter_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise invalid("Query parameter '%s' must be true or false." % name)


def parse_iso_datetime(name, value):
    if not isinstance(value, str):
        raise invalid("Field '%s' must be an ISO 8601 UTC timestamp." % name)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        raise invalid("Field '%s' must be an ISO 8601 UTC timestamp." % name)
    return parsed
