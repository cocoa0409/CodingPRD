"""Rungs 21-23: payload shape, enum membership and numeric/date ranges.

ENUM ROUTING (rung 22) is exhaustive and CLOSED.  Exactly these request-body
fields route an unrecognised value to ``ERR_INVALID_ENUM``:

    1.  ``zone``                on POST /barns                       (Barn.zone)
    2.  ``served_weekdays[]``   on POST /barns                       (Barn.served_weekdays members)
    3.  ``certification_level`` on POST /farriers and .../recertify  (Farrier.certification_level)
    4.  ``material``            on POST /shoe-skus                   (ShoeSku.material)
    5.  ``reason``              on POST /farriers/{id}/deactivate
    6.  ``lines[].service_type``on POST /appointments/{id}/service-lines (ServiceLine.service_type)
    7.  ``limb_scope[]``        on POST /vet-prescriptions           (VetPrescription.limb_scope members)
    8.  ``warranty_reason``     on POST /appointments/{id}/warranty-revisit
    9.  ``delivery_outcome``    on POST /reminders/{id}/send
    10. ``direction``           on POST /route-stops/{id}/reorder
    11. ``visit_kind``          (Appointment.visit_kind) -- declared on the closed
        list, but no endpoint accepts it as input, so it is unreachable.
    12. ``limb``                (LimbState.limb) -- declared on the closed list,
        but it is a system field: the only caller-supplied ``limb`` is the query
        FILTER of GET /horses/{id}/limb-states, and section 4.1 does not list
        ERR_INVALID_ENUM among that endpoint's refusals, so filters do not
        route here.

No other field routes to ERR_INVALID_ENUM.  Every other membership-ish failure
goes elsewhere:
  * query filters (``status``, ``zone``, ``material``, ``hold_status``,
    ``location_kind``, ``line_kind``, ``limb``, ...) never error -- they are
    exact-match and simply yield an empty page;
  * a missing / mistyped / illegally-combined body field  -> ERR_VALIDATION (21);
  * a numeric or date value outside its band              -> ERR_VALUE_OUT_OF_RANGE (23);
  * a body foreign key naming no row                      -> the entity's own
    ``*_NOT_FOUND`` code (rungs 4-20);
  * a value that is legal but wrong for the current state -> ERR_INVALID_STATE
    or the relevant gate code.
"""

from flask import request

from .errors import ApiError
from .timeutil import parse_iso_date


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "The request body must be a JSON object.")
    return data


def bad(message):
    raise ApiError("ERR_VALIDATION", message)


def out_of_range(message):
    raise ApiError("ERR_VALUE_OUT_OF_RANGE", message)


def bad_enum(field, value):
    raise ApiError("ERR_INVALID_ENUM", "%s carries an undeclared member: %r" % (field, value))


# --- rung 21 helpers --------------------------------------------------------
def req_str(data, name):
    value = data.get(name)
    if not isinstance(value, str) or not value.strip():
        bad("Field %s is required and must be a non-empty string." % name)
    return value


def opt_str(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    value = data[name]
    if not isinstance(value, str) or not value.strip():
        bad("Field %s must be a non-empty string when supplied." % name)
    return value


def req_int(data, name):
    value = data.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field %s is required and must be an integer." % name)
    return value


def opt_int(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field %s must be an integer when supplied." % name)
    return value


def req_bool(data, name):
    value = data.get(name)
    if not isinstance(value, bool):
        bad("Field %s is required and must be a boolean." % name)
    return value


def opt_bool(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    value = data[name]
    if not isinstance(value, bool):
        bad("Field %s must be a boolean when supplied." % name)
    return value


def req_date(data, name):
    value = data.get(name)
    if not isinstance(value, str) or parse_iso_date(value) is None:
        bad("Field %s is required and must be an ISO calendar date." % name)
    return value


def req_list(data, name, non_empty=True):
    value = data.get(name)
    if not isinstance(value, list):
        bad("Field %s is required and must be an array." % name)
    if non_empty and not value:
        bad("Field %s must be a non-empty array." % name)
    return value


def opt_list(data, name, default=None):
    if name not in data or data[name] is None:
        return list(default) if default is not None else None
    value = data[name]
    if not isinstance(value, list):
        bad("Field %s must be an array when supplied." % name)
    return value


def no_duplicates(values, name):
    if len(set(values)) != len(values):
        bad("Field %s may not contain duplicates." % name)


# --- rung 22 helper ---------------------------------------------------------
def enum(value, members, field):
    if value not in members:
        bad_enum(field, value)
    return value


# --- rung 23 helper ---------------------------------------------------------
def in_range(value, low, high, name):
    if value < low or value > high:
        out_of_range("%s must be between %s and %s inclusive." % (name, low, high))
    return value
