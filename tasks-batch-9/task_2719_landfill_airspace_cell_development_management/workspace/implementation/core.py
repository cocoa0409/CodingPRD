"""Foundation: in-memory store, logical clock, response envelope, errors, auth,
request-shape validation and rounding helpers."""
import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, getcontext
from functools import wraps

from flask import request, jsonify

getcontext().prec = 60

# ---------------------------------------------------------------- roles ------
ROLES = (
    "PlatformAdmin", "SiteOperator", "ScaleOperator", "CqaEngineer",
    "SurveyorOfRecord", "EnvironmentalManager", "RegulatoryAgency",
    "FinanceOfficer",
)
ALL_ROLES = list(ROLES)

# --------------------------------------------------------------- errors ------
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_SITE_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_LANDFILL_NOT_FOUND": 404,
    "ERR_CELL_NOT_FOUND": 404,
    "ERR_LINER_QA_PACKAGE_NOT_FOUND": 404,
    "ERR_AERIAL_SURVEY_NOT_FOUND": 404,
    "ERR_OPERATING_DAY_NOT_FOUND": 404,
    "ERR_WASTE_LOAD_NOT_FOUND": 404,
    "ERR_SPECIAL_WASTE_APPROVAL_NOT_FOUND": 404,
    "ERR_TREATMENT_AGREEMENT_NOT_FOUND": 404,
    "ERR_LEACHATE_SHIPMENT_NOT_FOUND": 404,
    "ERR_GAS_WELL_NOT_FOUND": 404,
    "ERR_SURFACE_EMISSION_SCAN_NOT_FOUND": 404,
    "ERR_CLOSURE_COST_ESTIMATE_NOT_FOUND": 404,
    "ERR_HOST_COMMUNITY_AGREEMENT_NOT_FOUND": 404,
    "ERR_CROSS_SITE_REFERENCE": 409,
    "ERR_STALE_LANDFILL_VERSION": 412,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_SITE_NOT_ACCEPTING_WASTE": 409,
    "ERR_CELL_NOT_ACCEPTING_WASTE": 409,
    "ERR_CELL_NOT_READY_FOR_WELLFIELD": 409,
    "ERR_AGREEMENT_NOT_ACTIVE": 409,
    "ERR_PROHIBITED_MATERIAL": 422,
    "ERR_QA_SCORE_BELOW_THRESHOLD": 422,
    "ERR_GAS_CORRECTIVE_ACTION_OPEN": 409,
    "ERR_WELL_OXYGEN_CRITICAL": 422,
    "ERR_APPROVAL_EXPIRED": 422,
    "ERR_SURVEY_PERIOD_OVERLAP": 409,
    "ERR_SURVEY_SPACING_VIOLATION": 409,
    "ERR_SLOT_CAPACITY_EXCEEDED": 409,
    "ERR_DUPLICATE_PERMIT_NUMBER": 409,
    "ERR_DUPLICATE_CELL_CODE": 409,
    "ERR_DUPLICATE_OPERATING_DATE": 409,
    "ERR_DUPLICATE_WELL_CODE": 409,
    "ERR_DUPLICATE_ESTIMATE_YEAR": 409,
    "ERR_PIGGYBACK_PARENT_NOT_CLOSED": 409,
    "ERR_DAILY_LOAD_LIMIT_EXCEEDED": 409,
    "ERR_PENDING_SCREENING_PRESENT": 409,
    "ERR_UNCERTIFIED_LOADS_PRESENT": 409,
    "ERR_CELL_HAS_UNFINISHED_WELLS": 409,
    "ERR_AMENDMENT_IN_PROGRESS": 409,
    "ERR_HOST_AGREEMENT_ALREADY_LIVE": 409,
    "ERR_PERMITTED_AIRSPACE_EXCEEDED": 422,
    "ERR_NO_EXECUTED_HOST_AGREEMENT": 409,
    "ERR_APPROVAL_TONNAGE_CAP_EXCEEDED": 422,
    "ERR_DAILY_GALLON_CAP_EXCEEDED": 422,
    "ERR_FINANCIAL_ASSURANCE_SHORTFALL": 402,
    "ERR_NOT_FOUND": 404,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or error_id.replace("ERR_", "").replace(
            "_", " ").capitalize() + "."


def err(error_id, message=None):
    return ApiError(error_id, message)


# ------------------------------------------------------- time / clock --------
CLOCK_EPOCH = "2026-08-01T00:00:00.000Z"


def iso_ms(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return iso_ms(datetime.now(timezone.utc))


def parse_iso(value):
    """Parse an ISO-8601 instant. Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s[-1] in ("Z", "z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def canon_iso(value):
    dt = parse_iso(value)
    return None if dt is None else iso_ms(dt)


def date_part(iso):
    return iso[:10] if iso else None


def month_part(iso):
    return iso[:7] if iso else None


def whole_days_between(iso_a, iso_b):
    a = parse_iso(iso_a)
    b = parse_iso(iso_b)
    return abs((a - b).total_seconds()) / 86400.0


# --------------------------------------------------------- decimal ----------
def D(x):
    return x if isinstance(x, Decimal) else Decimal(str(x))


def q2(x):
    return D(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def q4(x):
    return D(x).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def f2(x):
    return float(q2(x))


def f4(x):
    return float(q4(x))


def ceil_int(x):
    return int(D(x).to_integral_value(rounding=ROUND_CEILING))


# ---------------------------------------------------------- data store -------
KINDS = (
    "landfill", "cell", "liner_qa_package", "aerial_survey", "operating_day",
    "waste_load", "special_waste_approval", "treatment_agreement",
    "leachate_shipment", "gas_well", "surface_emission_scan",
    "closure_cost_estimate", "host_community_agreement",
)

NOT_FOUND = {
    "landfill": "ERR_LANDFILL_NOT_FOUND",
    "cell": "ERR_CELL_NOT_FOUND",
    "liner_qa_package": "ERR_LINER_QA_PACKAGE_NOT_FOUND",
    "aerial_survey": "ERR_AERIAL_SURVEY_NOT_FOUND",
    "operating_day": "ERR_OPERATING_DAY_NOT_FOUND",
    "waste_load": "ERR_WASTE_LOAD_NOT_FOUND",
    "special_waste_approval": "ERR_SPECIAL_WASTE_APPROVAL_NOT_FOUND",
    "treatment_agreement": "ERR_TREATMENT_AGREEMENT_NOT_FOUND",
    "leachate_shipment": "ERR_LEACHATE_SHIPMENT_NOT_FOUND",
    "gas_well": "ERR_GAS_WELL_NOT_FOUND",
    "surface_emission_scan": "ERR_SURFACE_EMISSION_SCAN_NOT_FOUND",
    "closure_cost_estimate": "ERR_CLOSURE_COST_ESTIMATE_NOT_FOUND",
    "host_community_agreement": "ERR_HOST_COMMUNITY_AGREEMENT_NOT_FOUND",
}


class Store(object):
    """Pure in-memory store. Starts completely empty on every boot: no seeding,
    no preloading, no persistence of any kind."""

    def __init__(self):
        self.tables = {}
        self.clock = CLOCK_EPOCH
        self.seq = 0
        for k in KINDS:
            self.tables[k] = {}


store = Store()


def table(kind):
    return store.tables[kind]


def rows(kind):
    return list(store.tables[kind].values())


def clock():
    return store.clock


def new_row(kind, data):
    store.seq += 1
    stamp = now_iso()
    row = {"id": str(uuid.uuid4())}
    row.update(data)
    row["created_at"] = stamp
    row["updated_at"] = stamp
    row["version"] = 1
    row["_seq"] = store.seq
    store.tables[kind][row["id"]] = row
    return row


def touch(row):
    row["updated_at"] = now_iso()
    row["version"] = row["version"] + 1
    return row


def public(row):
    return dict((k, v) for k, v in row.items() if not k.startswith("_"))


def order_key(row):
    return (row["created_at"], row["_seq"])


def get_or_404(kind, row_id):
    row = store.tables[kind].get(row_id)
    if row is None:
        raise err(NOT_FOUND[kind])
    return row


def fk_or_404(kind, row_id):
    """Body foreign-key resolution: a non-string id can never resolve."""
    if not isinstance(row_id, str):
        raise err(NOT_FOUND[kind])
    row = store.tables[kind].get(row_id)
    if row is None:
        raise err(NOT_FOUND[kind])
    return row


# ------------------------------------------------------------- envelope ------
_ALNUM = string.ascii_uppercase + string.digits


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": now_iso(),
    }


def obj_response(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def created(data):
    return obj_response(data, 201)


def list_response(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_body(error_id, message):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    })


# ---------------------------------------------------------- pagination -------
def _int_arg(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None:
        return default
    text = raw.strip()
    ok = len(text) > 0
    body = text[1:] if text[:1] in ("+", "-") else text
    if not body.isdigit():
        ok = False
    if not ok:
        raise err("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    value = int(text)
    if minimum is not None and value < minimum:
        raise err("ERR_INVALID_REQUEST", "%s is out of range." % name)
    if maximum is not None and value > maximum:
        raise err("ERR_INVALID_REQUEST", "%s is out of range." % name)
    return value


def pagination():
    limit = _int_arg("limit", 10, 1, 100)
    offset = _int_arg("offset", 0, 0, None)
    return limit, offset


def paged(rowset, serializer=public):
    limit, offset = pagination()
    ordered = sorted(rowset, key=order_key)
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return list_response([serializer(r) for r in window], limit, offset, total)


def filtered(rowset, mapping):
    out = rowset
    for param, field_name in mapping.items():
        raw = request.args.get(param)
        if raw is None:
            continue
        out = [r for r in out if r.get(field_name) is not None
               and str(r.get(field_name)) == raw]
    return out


# ------------------------------------------------------------------ auth ------
def endpoint(app, rule, methods, roles):
    """Registers a route. Rung 1 (headers/role recognised) and rung 2 (role
    permitted for this endpoint) run before body parsing and before any lookup."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(**kwargs):
            user_id = request.headers.get("X-User-ID")
            user_role = request.headers.get("X-User-Role")
            if not user_id or not user_role or user_role not in ROLES:
                raise err("ERR_UNAUTHENTICATED",
                          "Missing or unrecognised authentication headers.")
            if user_role not in roles:
                raise err("ERR_ROLE_NOT_PERMITTED",
                          "Role %s may not call this endpoint." % user_role)
            return fn(user_id, user_role, **kwargs)

        app.add_url_rule(rule, "%s %s" % ("|".join(methods), rule), wrapper,
                         methods=list(methods))
        return fn
    return decorator


# -------------------------------------------------- request shape (rung 3) ----
class Body(object):
    """Validates a write body field by field, in the order the endpoint declares
    its inputs. Every failure is ERR_INVALID_REQUEST (400)."""

    def __init__(self):
        raw = None
        data = request.get_data(cache=True, as_text=True)
        if data is not None and data.strip():
            try:
                raw = request.get_json(force=True, silent=False)
            except Exception:
                raise err("ERR_INVALID_REQUEST", "Body is not valid JSON.")
            if raw is None or not isinstance(raw, dict):
                raise err("ERR_INVALID_REQUEST", "Body must be a JSON object.")
        self.raw = raw if isinstance(raw, dict) else {}
        self.out = {}

    def _bad(self, name, why):
        raise err("ERR_INVALID_REQUEST", "%s %s" % (name, why))

    def _fetch(self, name, required, default):
        if name not in self.raw or self.raw[name] is None:
            if required:
                self._bad(name, "is required.")
            self.out[name] = default
            return False, default
        return True, self.raw[name]

    def has(self, name):
        return name in self.raw and self.raw[name] is not None

    def forbid(self, name, why="must be omitted."):
        if self.has(name):
            self._bad(name, why)

    def string(self, name, required=True, minlen=None, maxlen=None, default=None):
        present, value = self._fetch(name, required, default)
        if not present:
            return default
        if not isinstance(value, str):
            self._bad(name, "must be a string.")
        if minlen is not None and len(value) < minlen:
            self._bad(name, "is too short.")
        if maxlen is not None and len(value) > maxlen:
            self._bad(name, "is too long.")
        self.out[name] = value
        return value

    def enum(self, name, choices, required=True, default=None):
        present, value = self._fetch(name, required, default)
        if not present:
            return default
        if not isinstance(value, str) or value not in choices:
            self._bad(name, "must be one of %s." % ", ".join(choices))
        self.out[name] = value
        return value

    def number(self, name, required=True, gt=None, ge=None, le=None, default=None):
        present, value = self._fetch(name, required, default)
        if not present:
            return default
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            self._bad(name, "must be a number.")
        dec = D(value)
        if gt is not None and not dec > D(gt):
            self._bad(name, "must be greater than %s." % gt)
        if ge is not None and not dec >= D(ge):
            self._bad(name, "must be at least %s." % ge)
        if le is not None and not dec <= D(le):
            self._bad(name, "must be at most %s." % le)
        self.out[name] = value
        return value

    def integer(self, name, required=True, minimum=None, maximum=None, default=None):
        present, value = self._fetch(name, required, default)
        if not present:
            return default
        if isinstance(value, bool) or not isinstance(value, int):
            self._bad(name, "must be an integer.")
        if minimum is not None and value < minimum:
            self._bad(name, "must be at least %s." % minimum)
        if maximum is not None and value > maximum:
            self._bad(name, "must be at most %s." % maximum)
        self.out[name] = value
        return value

    def timestamp(self, name, required=True, default=None):
        present, value = self._fetch(name, required, default)
        if not present:
            return default
        canonical = canon_iso(value)
        if canonical is None:
            self._bad(name, "must be an ISO 8601 timestamp.")
        self.out[name] = canonical
        return canonical

    def fk(self, name, required=True, default=None):
        """A foreign key travels as a string; type errors are shape errors."""
        present, value = self._fetch(name, required, default)
        if not present:
            return default
        if not isinstance(value, str) or not value:
            self._bad(name, "must be a string identifier.")
        self.out[name] = value
        return value
