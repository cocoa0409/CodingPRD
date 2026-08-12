"""Rung 5 (body validity, ERR_INVALID_REQUEST) and rung 6 (enum membership,
ERR_INVALID_ENUM) helpers.

Rung 6's list is exhaustive and closed.  ENUM_ROUTED_FIELDS below is that list,
literally and completely; no other field routes to ERR_INVALID_ENUM.
"""

from flask import request

from errors import ApiError
from timeutil import parse_date, parse_instant

# The closed iff-list of rung 6.  Nineteen request fields route to
# ERR_INVALID_ENUM when they carry a value outside their declared member set.
# Anything not on this list is ERR_INVALID_REQUEST at rung 5.
ENUM_ROUTED_FIELDS = frozenset(
    [
        "payer_regime_default",          # agency
        "statutory_authority",           # ORI
        "applicant_type",                # service type
        "required_document_codes",       # service type -- members
        "accepted_id_document_types",    # service type -- members
        "site_kind",                     # capture site
        "booking_channel",               # appointment
        "presented_document_type",       # appointment check-in
        "sex",                           # applicant
        "id_document_type",              # applicant
        "exception_code",                # position closure
        "destination",                   # destination result
        "result_code",                   # destination result
        "outcome",                       # fitness determination
        "amended_outcome",               # challenge resolution
        "resolution",                    # challenge resolution
        "decision",                      # purge decision
        "event_type",                    # rap-back notification
        "to_status",                     # ORI authority change
    ]
)


def bad_request(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        bad_request("request body must be a JSON object")
    return data


def present(data, name):
    return name in data and data[name] is not None


# -- rung 5 typed accessors --------------------------------------------------

def req_string(data, name, allow_empty=False):
    if not present(data, name):
        bad_request("%s is required" % name)
    value = data[name]
    if not isinstance(value, str):
        bad_request("%s must be a string" % name)
    if not allow_empty and value == "":
        bad_request("%s must not be empty" % name)
    return value


def opt_string(data, name, default=None, allow_empty=True):
    if not present(data, name):
        return default
    value = data[name]
    if not isinstance(value, str):
        bad_request("%s must be a string" % name)
    if not allow_empty and value == "":
        bad_request("%s must not be empty" % name)
    return value


def req_int(data, name, minimum=None, maximum=None):
    if not present(data, name):
        bad_request("%s is required" % name)
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad_request("%s must be an integer" % name)
    _range(name, value, minimum, maximum)
    return value


def opt_int(data, name, default=None, minimum=None, maximum=None):
    if not present(data, name):
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad_request("%s must be an integer" % name)
    _range(name, value, minimum, maximum)
    return value


def _range(name, value, minimum, maximum):
    if minimum is not None and value < minimum:
        bad_request("%s must be at least %s" % (name, minimum))
    if maximum is not None and value > maximum:
        bad_request("%s must be at most %s" % (name, maximum))


def req_bool(data, name):
    if not present(data, name):
        bad_request("%s is required" % name)
    value = data[name]
    if not isinstance(value, bool):
        bad_request("%s must be a boolean" % name)
    return value


def opt_bool(data, name, default=None):
    if not present(data, name):
        return default
    value = data[name]
    if not isinstance(value, bool):
        bad_request("%s must be a boolean" % name)
    return value


def req_array(data, name, allow_empty=False):
    if not present(data, name):
        bad_request("%s is required" % name)
    value = data[name]
    if not isinstance(value, list):
        bad_request("%s must be an array" % name)
    if not allow_empty and len(value) == 0:
        bad_request("%s must not be empty" % name)
    for item in value:
        if not isinstance(item, str):
            bad_request("%s members must be strings" % name)
    return value


def req_instant(data, name):
    if not present(data, name):
        bad_request("%s is required" % name)
    value = parse_instant(data[name])
    if value is None:
        bad_request("%s must be an ISO 8601 datetime" % name)
    return value


def opt_instant(data, name, default=None):
    if not present(data, name):
        return default
    value = parse_instant(data[name])
    if value is None:
        bad_request("%s must be an ISO 8601 datetime" % name)
    return value


def req_date(data, name):
    if not present(data, name):
        bad_request("%s is required" % name)
    value = parse_date(data[name])
    if value is None:
        bad_request("%s must be a YYYY-MM-DD date" % name)
    return value


def opt_date(data, name, default=None):
    if not present(data, name):
        return default
    value = parse_date(data[name])
    if value is None:
        bad_request("%s must be a YYYY-MM-DD date" % name)
    return value


# -- rung 6 -------------------------------------------------------------------

def enum_value(name, value, members):
    """Rung 6.  Only ever called for a field on ENUM_ROUTED_FIELDS."""
    assert name in ENUM_ROUTED_FIELDS
    if value not in members:
        raise ApiError("ERR_INVALID_ENUM", "%s must be one of %s" % (name, ", ".join(members)))
    return value


def enum_members(name, values, members):
    assert name in ENUM_ROUTED_FIELDS
    for item in values:
        if item not in members:
            raise ApiError(
                "ERR_INVALID_ENUM", "%s members must be one of %s" % (name, ", ".join(members))
            )
    return values
