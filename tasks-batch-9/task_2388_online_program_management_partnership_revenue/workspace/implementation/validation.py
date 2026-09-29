"""Request screening step 4 (PRD 2.5): shape, type, enum, sign and date checks.

Every breach yields ERR_INVALID_REQUEST (400).
"""

import re

from errors import bad_request
from services.money import parse_iso_date, parse_iso_datetime

CIP_RE = re.compile(r"^\d{2}\.\d{4}$")
IPEDS_RE = re.compile(r"^\d{6}$")


class Field(object):
    def __init__(self, kind, required=False, enum=None, minimum=None, maximum=None,
                 nullable=False, pattern=None, item_enum=None):
        self.kind = kind
        self.required = required
        self.enum = tuple(enum) if enum else None
        self.minimum = minimum
        self.maximum = maximum
        self.nullable = nullable
        self.pattern = pattern
        self.item_enum = tuple(item_enum) if item_enum else None


def _check_int(name, value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request("%s must be an integer." % name)
    if name.endswith("_cents") and value < 0:
        raise bad_request("%s must be zero or greater." % name)
    if field.minimum is not None and value < field.minimum:
        raise bad_request("%s is below its minimum." % name)
    if field.maximum is not None and value > field.maximum:
        raise bad_request("%s is above its maximum." % name)
    return value


def _check_number(name, value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad_request("%s must be a number." % name)
    if field.minimum is not None and value < field.minimum:
        raise bad_request("%s is below its minimum." % name)
    if field.maximum is not None and value > field.maximum:
        raise bad_request("%s is above its maximum." % name)
    return value


def _check_tiers(name, value):
    if not isinstance(value, list) or not value:
        raise bad_request("%s must be a non-empty array." % name)
    out = []
    for item in value:
        if not isinstance(item, dict):
            raise bad_request("%s entries must be objects." % name)
        extra = set(item.keys()) - {"through_cents", "partner_rate"}
        if extra or "partner_rate" not in item or "through_cents" not in item:
            raise bad_request("%s entries must carry through_cents and partner_rate." % name)
        through = item["through_cents"]
        if through is not None:
            if isinstance(through, bool) or not isinstance(through, int) or through < 0:
                raise bad_request("%s.through_cents must be a non-negative integer or null." % name)
        rate = item["partner_rate"]
        if isinstance(rate, bool) or not isinstance(rate, (int, float)):
            raise bad_request("%s.partner_rate must be a number." % name)
        if rate < 0 or rate > 1:
            raise bad_request("%s.partner_rate must lie between 0 and 1." % name)
        out.append({"through_cents": through, "partner_rate": rate})
    return out


def _check_bands(name, value):
    if not isinstance(value, list) or not value:
        raise bad_request("%s must be a non-empty array." % name)
    out = []
    for item in value:
        if not isinstance(item, dict):
            raise bad_request("%s entries must be objects." % name)
        extra = set(item.keys()) - {"through_day", "refund_pct"}
        if extra or "refund_pct" not in item or "through_day" not in item:
            raise bad_request("%s entries must carry through_day and refund_pct." % name)
        through = item["through_day"]
        if through is not None:
            if isinstance(through, bool) or not isinstance(through, int) or through < 0:
                raise bad_request("%s.through_day must be a non-negative integer or null." % name)
        pct = item["refund_pct"]
        if isinstance(pct, bool) or not isinstance(pct, (int, float)):
            raise bad_request("%s.refund_pct must be a number." % name)
        if pct < 0 or pct > 1:
            raise bad_request("%s.refund_pct must lie between 0 and 1." % name)
        out.append({"through_day": through, "refund_pct": pct})
    return out


def _check_string_array(name, value, field):
    if not isinstance(value, list):
        raise bad_request("%s must be an array." % name)
    out = []
    for item in value:
        if not isinstance(item, str):
            raise bad_request("%s entries must be strings." % name)
        if field.item_enum is not None and item not in field.item_enum:
            raise bad_request("%s carries an undeclared member." % name)
        if field.pattern is not None and not field.pattern.match(item):
            raise bad_request("%s entries are malformed." % name)
        out.append(item)
    return out


def validate_body(body, spec):
    """Validate a JSON body against a field spec.  Returns the accepted values.

    ``None`` for an optional field is treated as "not supplied" unless the field
    is explicitly nullable, in which case the null is preserved.
    """
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise bad_request("The request body must be a JSON object.")

    for key in body.keys():
        if key not in spec:
            raise bad_request("Unknown field: %s." % key)

    out = {}
    for name, field in spec.items():
        if name not in body:
            if field.required:
                raise bad_request("Missing required field: %s." % name)
            continue
        value = body[name]
        if value is None:
            if field.nullable:
                out[name] = None
                continue
            if field.required:
                raise bad_request("%s may not be null." % name)
            continue

        kind = field.kind
        if kind == "string":
            if not isinstance(value, str):
                raise bad_request("%s must be a string." % name)
            if field.pattern is not None and not field.pattern.match(value):
                raise bad_request("%s is malformed." % name)
            out[name] = value
        elif kind == "enum":
            if not isinstance(value, str):
                raise bad_request("%s must be a string." % name)
            if value not in field.enum:
                raise bad_request("%s carries an undeclared member." % name)
            out[name] = value
        elif kind == "integer":
            out[name] = _check_int(name, value, field)
        elif kind == "number":
            out[name] = _check_number(name, value, field)
        elif kind == "boolean":
            if not isinstance(value, bool):
                raise bad_request("%s must be a boolean." % name)
            out[name] = value
        elif kind == "date":
            if parse_iso_date(value) is None:
                raise bad_request("%s must be an ISO date (YYYY-MM-DD)." % name)
            out[name] = value
        elif kind == "datetime":
            if parse_iso_datetime(value) is None:
                raise bad_request("%s must be an ISO 8601 timestamp." % name)
            out[name] = value
        elif kind == "tiers":
            out[name] = _check_tiers(name, value)
        elif kind == "bands":
            out[name] = _check_bands(name, value)
        elif kind == "string_array":
            out[name] = _check_string_array(name, value, field)
        else:  # pragma: no cover - defensive
            raise bad_request("%s is not understood." % name)

    _check_date_pairs(out)
    return out


def _check_date_pairs(values):
    """PRD 2.5 item 4: period_start <= period_end, launch_window_start <
    launch_window_end, term_start_date <= term_end_date."""
    if "period_start" in values and "period_end" in values:
        if parse_iso_date(values["period_start"]) > parse_iso_date(values["period_end"]):
            raise bad_request("period_start must be no later than period_end.")
    if "launch_window_start" in values and "launch_window_end" in values:
        if parse_iso_date(values["launch_window_start"]) >= parse_iso_date(values["launch_window_end"]):
            raise bad_request("launch_window_start must be strictly earlier than launch_window_end.")
    if "term_start_date" in values and "term_end_date" in values:
        if parse_iso_date(values["term_start_date"]) > parse_iso_date(values["term_end_date"]):
            raise bad_request("term_start_date must be no later than term_end_date.")


# --------------------------------------------------------------------------- #
# query parameters                                                            #
# --------------------------------------------------------------------------- #

def pagination_args(args):
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise bad_request("limit must be an integer.")
        if str(raw).strip() != str(limit):
            raise bad_request("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise bad_request("limit must lie between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise bad_request("offset must be an integer.")
        if str(raw).strip() != str(offset):
            raise bad_request("offset must be an integer.")
        if offset < 0:
            raise bad_request("offset must be zero or greater.")
    return limit, offset


def enum_filter(args, name, members):
    value = args.get(name)
    if value is None:
        return None
    if value not in members:
        raise bad_request("%s carries an undeclared member." % name)
    return value


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + len(page)) < total
    return page, total, has_more
