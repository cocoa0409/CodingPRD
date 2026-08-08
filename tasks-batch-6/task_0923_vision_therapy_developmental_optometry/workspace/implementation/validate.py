"""Rung 3 (shape and range) and rung 4 (enum membership).

ENUM ERROR-ROUTING RULE (PRD §2.7 rung 4, applied verbatim and exhaustively):
a value outside the declared set routes to ERR_INVALID_ENUM for exactly these
fields --
    diagnosis_category, discharge_reason, payer_type, assessment_type, purpose,
    metric_code, eye, discharge_criteria_mode, procedure_code, cancel_reason,
    item_class, returned_condition, service_class, direction, urgency,
    response_outcome, severity, close_reason, suspension_reason,
    equipment_class, credential, the `outcome` supplied on a claim
    adjudication, and every enum-valued filter on a list endpoint
    (status, schedule_status, billing_status, progress_state, modality,
     assessment_type, purpose, metric_code, direction, urgency, severity, ...).
Every other unacceptable value -- including a missing or badly typed value in
one of those very fields -- routes to ERR_VALIDATION.  Nothing else is ever
routed to ERR_INVALID_ENUM.
"""

from flask import request

from errors import ApiError
from store import parse_date, parse_instant

_MISSING = object()


def _fail(message):
    raise ApiError("ERR_VALIDATION", message)


def json_body():
    """Rung 3: the body must be a JSON object (an absent body reads as {})."""
    if not request.data:
        return Body({})
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        if request.data.strip() == b"":
            return Body({})
        _fail("Request body must be a JSON object.")
    if not isinstance(data, dict):
        _fail("Request body must be a JSON object.")
    return Body(data)


class Body(object):
    def __init__(self, data):
        self.data = data

    # ------------------------------------------------------------ access ---
    def raw(self, name):
        return self.data.get(name, _MISSING)

    def present(self, name):
        value = self.data.get(name, _MISSING)
        return value is not _MISSING and value is not None

    # ------------------------------------------------------ rung 3 shapes ---
    def str_req(self, name):
        value = self.data.get(name, _MISSING)
        if value is _MISSING or value is None:
            _fail("Field '%s' is required." % name)
        if not isinstance(value, str):
            _fail("Field '%s' must be a string." % name)
        return value

    def str_opt(self, name, default=None):
        value = self.data.get(name, _MISSING)
        if value is _MISSING or value is None:
            return default
        if not isinstance(value, str):
            _fail("Field '%s' must be a string." % name)
        return value

    def int_req(self, name, non_negative=False, minimum=None, maximum=None):
        value = self.data.get(name, _MISSING)
        if value is _MISSING or value is None:
            _fail("Field '%s' is required." % name)
        return self._as_int(name, value, non_negative, minimum, maximum)

    def int_opt(self, name, default=None, non_negative=False, minimum=None, maximum=None):
        value = self.data.get(name, _MISSING)
        if value is _MISSING or value is None:
            return default
        return self._as_int(name, value, non_negative, minimum, maximum)

    def _as_int(self, name, value, non_negative, minimum, maximum):
        if isinstance(value, bool) or isinstance(value, str):
            _fail("Field '%s' must be an integer." % name)
        if isinstance(value, float):
            if value != int(value):
                _fail("Field '%s' must be an integer." % name)
            value = int(value)
        if not isinstance(value, int):
            _fail("Field '%s' must be an integer." % name)
        if non_negative and value < 0:
            _fail("Field '%s' must not be negative." % name)
        if minimum is not None and value < minimum:
            _fail("Field '%s' is below its minimum." % name)
        if maximum is not None and value > maximum:
            _fail("Field '%s' is above its maximum." % name)
        return value

    def num_req(self, name, non_negative=False, minimum=None, maximum=None):
        value = self.data.get(name, _MISSING)
        if value is _MISSING or value is None:
            _fail("Field '%s' is required." % name)
        return self._as_num(name, value, non_negative, minimum, maximum)

    def num_opt(self, name, default=None, non_negative=False, minimum=None, maximum=None):
        value = self.data.get(name, _MISSING)
        if value is _MISSING or value is None:
            return default
        return self._as_num(name, value, non_negative, minimum, maximum)

    def _as_num(self, name, value, non_negative, minimum, maximum):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _fail("Field '%s' must be a number." % name)
        if non_negative and value < 0:
            _fail("Field '%s' must not be negative." % name)
        if minimum is not None and value < minimum:
            _fail("Field '%s' is below its minimum." % name)
        if maximum is not None and value > maximum:
            _fail("Field '%s' is above its maximum." % name)
        return value

    def bool_opt(self, name, default=False):
        value = self.data.get(name, _MISSING)
        if value is _MISSING or value is None:
            return default
        if not isinstance(value, bool):
            _fail("Field '%s' must be a boolean." % name)
        return value

    def date_req(self, name):
        text = self.str_req(name)
        if parse_date(text) is None:
            _fail("Field '%s' must be an ISO 8601 calendar date." % name)
        return text

    def date_opt(self, name, default=None):
        text = self.str_opt(name)
        if text is None:
            return default
        if parse_date(text) is None:
            _fail("Field '%s' must be an ISO 8601 calendar date." % name)
        return text

    def instant_req(self, name):
        text = self.str_req(name)
        if parse_instant(text) is None:
            _fail("Field '%s' must be an ISO 8601 UTC instant." % name)
        return text

    def instant_opt(self, name, default=None):
        text = self.str_opt(name)
        if text is None:
            return default
        if parse_instant(text) is None:
            _fail("Field '%s' must be an ISO 8601 UTC instant." % name)
        return text

    def enum_shape_req(self, name):
        """Rung 3 half of an enum field: present and a string."""
        return self.str_req(name)

    def enum_shape_opt(self, name):
        return self.str_opt(name)

    # ------------------------------------------------------- rung 4 enums ---
    def enum_req(self, name, allowed):
        value = self.data.get(name, _MISSING)
        if value is _MISSING or value is None or not isinstance(value, str):
            _fail("Field '%s' is required." % name)
        return enum_check(name, value, allowed)

    def enum_opt(self, name, allowed, default=None):
        value = self.data.get(name, _MISSING)
        if value is _MISSING or value is None:
            return default
        if not isinstance(value, str):
            _fail("Field '%s' must be a string." % name)
        return enum_check(name, value, allowed)


def enum_check(name, value, allowed):
    if value not in allowed:
        raise ApiError("ERR_INVALID_ENUM", "Field '%s' carries a value outside its declared set." % name)
    return value


def filter_enum(args, name, allowed):
    """An enum-valued list filter: a bad value is ERR_INVALID_ENUM (§2.3)."""
    value = args.get(name)
    if value is None:
        return None
    return enum_check(name, value, allowed)


def filter_str(args, name):
    return args.get(name)


def require_order(earlier_raw, later_raw, message, inclusive=False):
    """Rung 3 interval ordering on two ISO instants."""
    a = parse_instant(earlier_raw)
    b = parse_instant(later_raw)
    if a is None or b is None:
        _fail(message)
    if inclusive:
        if b < a:
            _fail(message)
    elif b <= a:
        _fail(message)


def require_date_order(earlier_raw, later_raw, message):
    """Rung 3 date ordering: `later` must be on or after `earlier`."""
    a = parse_date(earlier_raw)
    b = parse_date(later_raw)
    if a is None or b is None:
        _fail(message)
    if b < a:
        _fail(message)
