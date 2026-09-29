"""Request schema validation (PRD 2.8 rule 3) and pagination (PRD 2.3).

Every violation here raises ERR_INVALID_REQUEST / HTTP 400.
"""

import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ERR_INVALID_REQUEST, fail

CODE_RE = re.compile(r"^[A-Z0-9-]+$")

# PRD 2.3 pagination defaults
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0

PRODUCT_LINES = ["ON_PREMISES", "VENDED", "INDUSTRIAL_TUNNEL"]
PAYMENT_MODULES = ["COIN", "CARD", "MOBILE"]
CERT_SCOPES = ["DRUM_FAB", "BEARING_INSTALL", "CONTROL_INTEGRATION", "QA_SIGNOFF",
               "DIAGNOSTICS_TOOL"]
STATION_TYPES = ["DRUM_FAB", "BEARING_INSTALL", "CONTROL_INTEGRATION"]


def parse_body():
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return Payload({})
    try:
        data = json.loads(raw, parse_float=Decimal)
    except Exception:
        fail(ERR_INVALID_REQUEST, "Request body is not valid JSON.")
    if not isinstance(data, dict):
        fail(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return Payload(data)


def parse_instant(value, field):
    if not isinstance(value, str):
        fail(ERR_INVALID_REQUEST, "%s must be an ISO 8601 UTC timestamp." % field)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except Exception:
        fail(ERR_INVALID_REQUEST, "%s must be an ISO 8601 UTC timestamp." % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class Payload:
    def __init__(self, data):
        self.data = data

    def present(self, name):
        # An explicit JSON null is treated as an omitted value.
        return name in self.data and self.data[name] is not None

    def get(self, name):
        return self.data.get(name)

    def has_key(self, name):
        return name in self.data

    # ---- scalar readers -------------------------------------------------
    def _missing(self, name, required, default):
        if required:
            fail(ERR_INVALID_REQUEST, "Field '%s' is required." % name)
        return default

    def string(self, name, minlen=1, maxlen=None, required=True, default=None,
               pattern=None):
        if not self.present(name):
            return self._missing(name, required, default)
        value = self.data[name]
        if not isinstance(value, str):
            fail(ERR_INVALID_REQUEST, "Field '%s' must be a string." % name)
        if len(value) < minlen or (maxlen is not None and len(value) > maxlen):
            fail(ERR_INVALID_REQUEST,
                 "Field '%s' must be between %s and %s characters." % (name, minlen, maxlen))
        if pattern is not None and not pattern.match(value):
            fail(ERR_INVALID_REQUEST, "Field '%s' has an invalid format." % name)
        return value

    def code(self, name, maxlen=32, required=True, default=None):
        return self.string(name, 1, maxlen, required, default, CODE_RE)

    def integer(self, name, minimum=None, maximum=None, required=True, default=None):
        if not self.present(name):
            return self._missing(name, required, default)
        value = self.data[name]
        if isinstance(value, bool):
            fail(ERR_INVALID_REQUEST, "Field '%s' must be an integer." % name)
        if isinstance(value, Decimal):
            if value != value.to_integral_value():
                fail(ERR_INVALID_REQUEST, "Field '%s' must be an integer." % name)
            value = int(value)
        if not isinstance(value, int):
            fail(ERR_INVALID_REQUEST, "Field '%s' must be an integer." % name)
        if minimum is not None and value < minimum:
            fail(ERR_INVALID_REQUEST, "Field '%s' must be at least %s." % (name, minimum))
        if maximum is not None and value > maximum:
            fail(ERR_INVALID_REQUEST, "Field '%s' must be at most %s." % (name, maximum))
        return value

    def decimal(self, name, scale=2, gt=None, minimum=None, maximum=None,
                required=True, default=None):
        if not self.present(name):
            return self._missing(name, required, default)
        value = self.data[name]
        if isinstance(value, bool) or isinstance(value, str):
            fail(ERR_INVALID_REQUEST, "Field '%s' must be a number." % name)
        if isinstance(value, int):
            value = Decimal(value)
        if not isinstance(value, Decimal):
            fail(ERR_INVALID_REQUEST, "Field '%s' must be a number." % name)
        if not value.is_finite():
            fail(ERR_INVALID_REQUEST, "Field '%s' must be a finite number." % name)
        if -value.as_tuple().exponent > scale:
            fail(ERR_INVALID_REQUEST,
                 "Field '%s' must carry no more than %d decimal places." % (name, scale))
        if gt is not None and value <= gt:
            fail(ERR_INVALID_REQUEST, "Field '%s' must be greater than %s." % (name, gt))
        if minimum is not None and value < minimum:
            fail(ERR_INVALID_REQUEST, "Field '%s' must be at least %s." % (name, minimum))
        if maximum is not None and value > maximum:
            fail(ERR_INVALID_REQUEST, "Field '%s' must be at most %s." % (name, maximum))
        try:
            return value.quantize(Decimal(1).scaleb(-scale))
        except InvalidOperation:
            fail(ERR_INVALID_REQUEST, "Field '%s' is not a usable number." % name)

    def enum(self, name, members, required=True, default=None):
        if not self.present(name):
            return self._missing(name, required, default)
        value = self.data[name]
        if not isinstance(value, str) or value not in members:
            fail(ERR_INVALID_REQUEST,
                 "Field '%s' must be one of %s." % (name, ", ".join(members)))
        return value

    def boolean(self, name, required=True, default=None):
        if not self.present(name):
            return self._missing(name, required, default)
        value = self.data[name]
        if not isinstance(value, bool):
            fail(ERR_INVALID_REQUEST, "Field '%s' must be a boolean." % name)
        return value

    def instant(self, name, required=True, default=None):
        if not self.present(name):
            return self._missing(name, required, default)
        return parse_instant(self.data[name], "Field '%s'" % name)

    def date_string(self, name, required=True, default=None):
        if not self.present(name):
            return self._missing(name, required, default)
        value = self.data[name]
        if not isinstance(value, str) or value.strip() == "":
            fail(ERR_INVALID_REQUEST, "Field '%s' must be an ISO 8601 date." % name)
        return value

    def enum_array(self, name, members, required=True, default=None, non_empty=True):
        if not self.present(name):
            if required:
                fail(ERR_INVALID_REQUEST, "Field '%s' is required." % name)
            return list(default) if default is not None else None
        value = self.data[name]
        if not isinstance(value, list):
            fail(ERR_INVALID_REQUEST, "Field '%s' must be an array." % name)
        for item in value:
            if not isinstance(item, str) or item not in members:
                fail(ERR_INVALID_REQUEST,
                     "Field '%s' accepts only %s." % (name, ", ".join(members)))
        if len(set(value)) != len(value):
            fail(ERR_INVALID_REQUEST, "Field '%s' must not contain duplicates." % name)
        if non_empty and len(value) == 0:
            fail(ERR_INVALID_REQUEST, "Field '%s' must not be empty." % name)
        return list(value)

    def id_ref(self, name, required=True, default=None):
        if not self.present(name):
            return self._missing(name, required, default)
        value = self.data[name]
        if not isinstance(value, str) or value.strip() == "":
            fail(ERR_INVALID_REQUEST, "Field '%s' must be a resource identifier." % name)
        return value


# ---- query string ------------------------------------------------------
def q_pagination():
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except ValueError:
            fail(ERR_INVALID_REQUEST, "Query parameter 'limit' must be an integer.")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            fail(ERR_INVALID_REQUEST, "Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except ValueError:
            fail(ERR_INVALID_REQUEST, "Query parameter 'offset' must be an integer.")
        if offset < OFFSET_MIN:
            fail(ERR_INVALID_REQUEST, "Query parameter 'offset' must be 0 or greater.")
    return limit, offset


def q_enum(name, members):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in members:
        fail(ERR_INVALID_REQUEST,
             "Query parameter '%s' must be one of %s." % (name, ", ".join(members)))
    return value


def q_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def q_bool(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    lowered = value.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    fail(ERR_INVALID_REQUEST, "Query parameter '%s' must be a boolean." % name)


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
