"""Body-shape validation (priority 4), pagination, filters and FK resolution."""

from flask import request

from errors import raise_err
from store import MONTH_RE, db, dt_of, fmt_iso, parse_iso, sorted_records

MISSING = object()


class Field:
    """Declared shape of one body field."""

    def __init__(
        self,
        name,
        kind,
        required=True,
        default=MISSING,
        enum=None,
        minimum=None,
        maximum=None,
        exclusive_minimum=None,
    ):
        self.name = name
        self.kind = kind
        self.required = required
        self.default = default
        self.enum = enum
        self.minimum = minimum
        self.maximum = maximum
        self.exclusive_minimum = exclusive_minimum


def raw_body():
    """The JSON body as a dict; a non-object body is a shape violation."""
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise_err("ERR_INVALID_REQUEST", "The request body is not valid JSON.")
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return body


def _bad(name, detail):
    raise_err("ERR_INVALID_REQUEST", "Field '%s' %s." % (name, detail))


def _check_number_range(spec, value):
    if spec.exclusive_minimum is not None and not value > spec.exclusive_minimum:
        _bad(spec.name, "must be greater than %s" % spec.exclusive_minimum)
    if spec.minimum is not None and value < spec.minimum:
        _bad(spec.name, "must be at least %s" % spec.minimum)
    if spec.maximum is not None and value > spec.maximum:
        _bad(spec.name, "must be at most %s" % spec.maximum)


def _coerce(spec, value):
    kind = spec.kind
    if kind == "string":
        if not isinstance(value, str):
            _bad(spec.name, "must be a string")
        if spec.enum is not None and value not in spec.enum:
            _bad(spec.name, "must be one of %s" % ", ".join(spec.enum))
        return value
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            _bad(spec.name, "must be an integer")
        _check_number_range(spec, value)
        return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _bad(spec.name, "must be a number")
        _check_number_range(spec, value)
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            _bad(spec.name, "must be a boolean")
        return value
    if kind == "datetime":
        parsed = parse_iso(value)
        if parsed is None:
            _bad(spec.name, "must be an ISO-8601 instant")
        return fmt_iso(parsed)
    if kind == "month":
        if not isinstance(value, str):
            _bad(spec.name, "must be a string in YYYY-MM form")
        m = MONTH_RE.match(value.strip())
        if not m or not 1 <= int(m.group(2)) <= 12:
            _bad(spec.name, "must be in YYYY-MM form")
        return value.strip()
    if kind == "string_array":
        if not isinstance(value, list):
            _bad(spec.name, "must be an array")
        for entry in value:
            if not isinstance(entry, str):
                _bad(spec.name, "must be an array of strings")
        return list(value)
    raise AssertionError("unknown field kind %s" % kind)


def validate_body(specs, body=None):
    """Validate the request body against the declared field specs."""
    if body is None:
        body = raw_body()
    out = {}
    for spec in specs:
        if spec.name not in body or body[spec.name] is None:
            if spec.required:
                if spec.name in body:
                    _bad(spec.name, "is required")
                _bad(spec.name, "is required")
            if spec.default is not MISSING:
                out[spec.name] = spec.default
            continue
        out[spec.name] = _coerce(spec, body[spec.name])
    return out


def require_interval(values, start_name, end_name):
    """Interval fields must be ordered end strictly after start (priority 4)."""
    start = dt_of(values[start_name])
    end = dt_of(values[end_name])
    if not end > start:
        raise_err(
            "ERR_INVALID_REQUEST",
            "Field '%s' must be strictly after '%s'." % (end_name, start_name),
        )


# ---------------------------------------------------------------------------
# path / body foreign key resolution
# ---------------------------------------------------------------------------
COLLECTIONS = {
    "state_program": ("state_programs", "ERR_STATE_PROGRAM_NOT_FOUND"),
    "wholesaler": ("wholesalers", "ERR_WHOLESALER_NOT_FOUND"),
    "licensee_user": ("licensee_users", "ERR_LICENSEE_USER_NOT_FOUND"),
    "brand": ("brands", "ERR_BRAND_NOT_FOUND"),
    "price_schedule": ("price_schedules", "ERR_PRICE_SCHEDULE_NOT_FOUND"),
    "price_schedule_item": ("price_schedule_items", "ERR_PRICE_SCHEDULE_ITEM_NOT_FOUND"),
    "quantity_discount_tier": (
        "quantity_discount_tiers",
        "ERR_QUANTITY_DISCOUNT_TIER_NOT_FOUND",
    ),
    "combination_sale": ("combination_sales", "ERR_COMBINATION_SALE_NOT_FOUND"),
    "hold_amendment": ("hold_amendments", "ERR_HOLD_AMENDMENT_NOT_FOUND"),
    "error_correction": ("error_corrections", "ERR_ERROR_CORRECTION_NOT_FOUND"),
    "retailer_invoice": ("retailer_invoices", "ERR_RETAILER_INVOICE_NOT_FOUND"),
    "invoice_line": ("invoice_lines", "ERR_INVOICE_LINE_NOT_FOUND"),
    "compliance_audit": ("compliance_audits", "ERR_COMPLIANCE_AUDIT_NOT_FOUND"),
    "audit_finding": ("audit_findings", "ERR_AUDIT_FINDING_NOT_FOUND"),
}


def must_find(kind, record_id):
    attr, error_id = COLLECTIONS[kind]
    record = getattr(db, attr).get(record_id) if isinstance(record_id, str) else None
    if record is None:
        raise_err(error_id)
    return record


# ---------------------------------------------------------------------------
# pagination and filters
# ---------------------------------------------------------------------------
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _query_int(name, default, minimum, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        raise_err("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    value = int(text)
    if value < minimum or (maximum is not None and value > maximum):
        raise_err("ERR_INVALID_REQUEST", "Query parameter '%s' is out of range." % name)
    return value


def pagination():
    limit = _query_int("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _query_int("offset", OFFSET_DEFAULT, 0, None)
    return limit, offset


def filters(spec):
    """Read exact-equality filters from the query string.

    ``spec`` maps a query parameter name to either None (free-form string match)
    or a tuple of the declared enum members for that field.
    """
    out = {}
    for name, enum in spec.items():
        raw = request.args.get(name)
        if raw is None or raw == "":
            continue
        value = raw.strip()
        if enum is not None and value not in enum:
            raise_err(
                "ERR_INVALID_REQUEST",
                "Query parameter '%s' must be one of %s." % (name, ", ".join(enum)),
            )
        out[name] = value
    return out


def paginate(records, limit, offset, serializer):
    total = len(records)
    window = records[offset : offset + limit]
    return [serializer(r) for r in window], total


def collection_response(records, spec, serializer):
    """Filter, sort, paginate and render a collection."""
    from envelope import list_response

    limit, offset = pagination()
    active = filters(spec)
    matched = []
    for record in records:
        keep = True
        for name, value in active.items():
            stored = record.get(name)
            if isinstance(stored, bool):
                stored = "true" if stored else "false"
            if stored is None or str(stored) != value:
                keep = False
                break
        if keep:
            matched.append(record)
    matched = sorted_records(matched)
    page, total = paginate(matched, limit, offset, serializer)
    return list_response(page, limit, offset, total)


def query_enum(name, members, default):
    """A query parameter constrained to a declared set of members."""
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    value = raw.strip()
    if value not in members:
        raise_err(
            "ERR_INVALID_REQUEST",
            "Query parameter '%s' must be one of %s." % (name, ", ".join(members)),
        )
    return value


def query_instant(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    parsed = parse_iso(raw)
    if parsed is None:
        raise_err(
            "ERR_INVALID_REQUEST",
            "Query parameter '%s' must be an ISO-8601 instant." % name,
        )
    return parsed
