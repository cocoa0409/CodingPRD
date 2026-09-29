"""CAFO Nutrient Management API -- Flask application.

Boots with a completely empty store and the logical clock at 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask, g, jsonify, request

import calc
from calc import (
    ANIMAL_GROUP,
    METHOD_SETBACK_MULTIPLIER,
    MIN_STORAGE_DAYS,
    OVERFLOW_FREEBOARD_IN,
    PRECIPITATION_LIMIT_IN,
    REAPPLICATION_INTERVAL_DAYS,
    RESPONSE_DAYS,
    application_load,
    budget_allowable_rate,
    design_storage_days,
    effective_daily,
    field_setback_and_net_acres,
    incident_notification_deadlines,
    annual_report_mass_balance,
    latest_inspection,
    lock_budgets,
    measured_volume,
    nutrient_rollup,
    operation_animal_units_and_class,
    operation_design_production,
    operation_seasonal_factor,
    permit_renewal_fee,
    recompute_operation,
    recompute_storage,
    records_basis,
    refresh_hauler,
    refresh_soil_test,
    seasonal_factor_for,
    set_fields,
    soil_test_p_index,
    stamp_coverage_dates,
    storage_geometry,
    storages_of,
    transfer_load,
)
from core import (
    ApiError,
    D,
    DB,
    NOT_FOUND_CODE,
    add_days,
    add_years,
    error_body,
    fail,
    fmt_dt,
    fmt_stamp,
    get,
    ifloor,
    jsonable,
    meta,
    new_row,
    now,
    ok_list,
    ok_object,
    parse_dt,
    rows,
    serialize,
    set_clock,
    touch,
    q2,
    q4,
)

app = Flask(__name__)
app.url_map.strict_slashes = False

ROLES = ("Operator", "CertifiedPlanner", "StateReviewer", "Hauler", "ComplianceAdmin")

METHODS = ("SURFACE_BROADCAST", "INCORPORATED_24H", "INJECTION", "IRRIGATION")
DEFICIENCY_CATEGORIES = (
    "RECORDKEEPING",
    "FREEBOARD",
    "SETBACK",
    "TRANSFER_DOCUMENTATION",
    "MORTALITY",
)


# ==========================================================================
# error handling
# ==========================================================================


@app.errorhandler(ApiError)
def _api_error(e):
    return jsonify(error_body(e.error_id, e.message)), e.status


@app.errorhandler(404)
def _not_found(_e):
    return jsonify(error_body("ERR_INVALID_REQUEST", "Unknown route.")), 404


@app.errorhandler(405)
def _bad_method(_e):
    return jsonify(error_body("ERR_INVALID_REQUEST", "Method not allowed.")), 405


@app.errorhandler(500)
def _boom(e):  # pragma: no cover
    return jsonify(error_body("ERR_INVALID_REQUEST", "Internal error: %s" % e)), 500


# ==========================================================================
# auth (priority 1 and 2)
# ==========================================================================


def auth(*roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    g.user_id = uid
    g.role = role
    if role not in roles:
        fail("ERR_UNAUTHORIZED")
    return uid, role


def require_owner(op_id):
    """priority 3 -- Operator ownership."""
    if g.role == "Operator" and op_id is not None and g.user_id != op_id:
        fail("ERR_OWNERSHIP_VIOLATION")


def require_hauler(hauler_id):
    """priority 3 -- Hauler assignment."""
    if g.role == "Hauler" and hauler_id is not None and g.user_id != hauler_id:
        fail("ERR_OWNERSHIP_VIOLATION")


# ==========================================================================
# path / fk resolution (priority 5 and 6)
# ==========================================================================


def need(table, rid):
    row = get(table, rid)
    if row is None:
        fail(NOT_FOUND_CODE[table], "No such resource: %s" % rid)
    return row


def fk(table, data, key, required=True):
    """priority 6 -- resolve one declared foreign key from the body."""
    if key not in data:
        return None
    v = data.get(key)
    if v is None:
        return None
    row = get(table, v)
    if row is None:
        fail(NOT_FOUND_CODE[table], "No such %s: %s" % (key, v))
    return row


# ==========================================================================
# body validation (priority 7)
# ==========================================================================


class F(object):
    def __init__(
        self,
        kind,
        required=True,
        default=None,
        enum=None,
        gt=None,
        ge=None,
        nullable=False,
    ):
        self.kind = kind
        self.required = required
        self.default = default
        self.enum = enum
        self.gt = gt
        self.ge = ge
        self.nullable = nullable


def raw_body():
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def no_body(data):
    if data:
        fail("ERR_INVALID_REQUEST", "This endpoint accepts no request body fields.")


def _bad(name, why):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s." % (name, why))


def validate(data, spec):
    for k in data:
        if k not in spec:
            _bad(k, "is not a recognised field")
    out = {}
    for name, f in spec.items():
        if name not in data:
            if f.required:
                _bad(name, "is required")
            out[name] = f.default
            continue
        v = data[name]
        if v is None:
            if f.nullable or (not f.required and f.default is None):
                out[name] = None
                continue
            _bad(name, "must not be null")
        if f.kind == "string":
            if not isinstance(v, str) or not v.strip():
                _bad(name, "must be a non-empty string")
            out[name] = v
        elif f.kind == "id":
            if not isinstance(v, str) or not v.strip():
                _bad(name, "must be a non-empty string identifier")
            out[name] = v
        elif f.kind == "bool":
            if not isinstance(v, bool):
                _bad(name, "must be a boolean")
            out[name] = v
        elif f.kind == "int":
            if isinstance(v, bool) or not isinstance(v, int):
                _bad(name, "must be an integer")
            if f.ge is not None and v < f.ge:
                _bad(name, "must be >= %s" % f.ge)
            if f.gt is not None and v <= f.gt:
                _bad(name, "must be > %s" % f.gt)
            out[name] = v
        elif f.kind == "number":
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                _bad(name, "must be a number")
            d = D(str(v))
            if f.ge is not None and d < D(f.ge):
                _bad(name, "must be >= %s" % f.ge)
            if f.gt is not None and d <= D(f.gt):
                _bad(name, "must be > %s" % f.gt)
            out[name] = d
        elif f.kind == "enum":
            if not isinstance(v, str) or v not in f.enum:
                _bad(name, "must be one of %s" % ", ".join(f.enum))
            out[name] = v
        elif f.kind == "datetime":
            dt = parse_dt(v) if isinstance(v, str) else None
            if dt is None:
                _bad(name, "must be an ISO 8601 UTC instant")
            out[name] = dt
        elif f.kind == "enum_array":
            if not isinstance(v, list) or not v:
                _bad(name, "must be a non-empty array")
            seen = []
            for m in v:
                if not isinstance(m, str) or m not in f.enum:
                    _bad(name, "members must be among %s" % ", ".join(f.enum))
                if m not in seen:
                    seen.append(m)
            out[name] = seen
        elif f.kind == "enum_array_opt":
            if v is None:
                out[name] = []
                continue
            if not isinstance(v, list):
                _bad(name, "must be an array")
            seen = []
            for m in v:
                if not isinstance(m, str) or m not in f.enum:
                    _bad(name, "members must be among %s" % ", ".join(f.enum))
                if m not in seen:
                    seen.append(m)
            out[name] = seen
        else:  # pragma: no cover
            raise AssertionError(f.kind)
    return out


# ==========================================================================
# list helpers
# ==========================================================================


def qarg(name):
    """Read a read-only parameter from the query string, or from a JSON body."""
    v = request.args.get(name)
    if v is not None:
        return v
    if request.data:
        d = request.get_json(silent=True)
        if isinstance(d, dict) and d.get(name) is not None:
            return str(d[name])
    return None


def pagination():
    limit, offset = 10, 0
    raw = qarg("limit")
    if raw is not None:
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    raw = qarg("offset")
    if raw is not None:
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be >= 0.")
    return limit, offset


def filtered(table, string_fields=(), int_fields=()):
    items = rows(table)
    for name in string_fields:
        v = qarg(name)
        if v is None:
            continue
        items = [r for r in items if r.get(name) == v]
    for name in int_fields:
        v = qarg(name)
        if v is None:
            continue
        try:
            iv = int(v)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "%s must be an integer." % name)
        items = [r for r in items if r.get(name) == iv]
    return items


def listing(table, string_fields=(), int_fields=()):
    limit, offset = pagination()
    items = filtered(table, string_fields, int_fields)
    total = len(items)
    page = items[offset : offset + limit]
    return jsonify_pair(ok_list([serialize(r) for r in page], limit, offset, total))


def jsonify_pair(pair):
    body, code = pair
    return jsonify(body), code


def one(row, code=200):
    return jsonify_pair(ok_object(serialize(row), code))


# ==========================================================================
# ownership resolution helpers
# ==========================================================================


def op_of_plan(plan):
    return get("operations", plan.get("operation_id"))


def op_of_row(table, row):
    if table == "operations":
        return row
    if table in ("permits", "plans", "fields", "storages", "transfers", "incidents",
                 "inspections", "reports"):
        return get("operations", row.get("operation_id"))
    if table == "soil_tests":
        f = get("fields", row.get("field_id"))
        return get("operations", f.get("operation_id")) if f else None
    if table == "budgets":
        p = get("plans", row.get("plan_id"))
        return get("operations", p.get("operation_id")) if p else None
    if table == "storage_inspections":
        s = get("storages", row.get("storage_id"))
        return get("operations", s.get("operation_id")) if s else None
    if table == "events":
        p = get("plans", row.get("plan_id"))
        return get("operations", p.get("operation_id")) if p else None
    return None


def own_op_id(table, row):
    op = op_of_row(table, row)
    return None if op is None else op["id"]


def read_one(table, rid, *roles):
    auth(*roles)
    row = get(table, rid)
    if row is not None:
        require_owner(own_op_id(table, row))
    row = need(table, rid)
    if table == "haulers":
        refresh_hauler(row)
    elif table == "soil_tests":
        refresh_soil_test(row)
    return one(row)


# ==========================================================================
# shared validation blocks
# ==========================================================================


def check_not_future(dt, label="record date"):
    if dt > now():
        fail("ERR_FUTURE_DATED_RECORD", "%s is after the logical clock." % label)


def check_not_suspended(op):
    if op["compliance_posture"] == "SUSPENDED":
        fail("ERR_OPERATION_SUSPENDED", "The operation's compliance posture is SUSPENDED.")


def check_open(op):
    if op["compliance_posture"] != "OPEN":
        fail("ERR_OPERATION_RESTRICTED", "The operation's compliance posture is not OPEN.")


def check_hauler_active(h):
    refresh_hauler(h)
    if h["hauler_status"] != "ACTIVE":
        fail("ERR_HAULER_LICENSE_LAPSED", "The hauler's licence has lapsed.")


def permits_of(op_id):
    return [p for p in rows("permits") if p.get("operation_id") == op_id]


def check_coverage_not_expired(op_id):
    ps = permits_of(op_id)
    if ps and all(p["coverage_status"] == "EXPIRED" for p in ps):
        fail("ERR_PERMIT_COVERAGE_EXPIRED", "The operation's permit coverage has expired.")


def bump_operation_version(op):
    """Derived recomputes never bump version, so an explicit mutation bumps once."""
    touch("operations", op)


# ==========================================================================
# Operation
# ==========================================================================

OPERATION_SPEC = {
    "name": F("string"),
    "county": F("string"),
    "animal_type": F("enum", enum=("DAIRY_COW", "BEEF_FEEDER", "SWINE_FINISHING", "LAYER_HEN")),
    "head_count": F("int", ge=1),
    "manure_handling": F("enum", enum=("LIQUID", "DRY")),
    "open_lot_area_sqft": F("number", required=False, default=D(0), ge=0),
    "discharge_potential": F("enum", enum=("NONE", "STORMWATER_ONLY", "CONTINUOUS")),
    "has_conservation_plan": F("bool", required=False, default=False),
}


@app.post("/cafo/operations")
def create_operation():
    auth("ComplianceAdmin")
    data = validate(raw_body(), OPERATION_SPEC)
    fields = {
        "name": data["name"],
        "county": data["county"],
        "animal_type": data["animal_type"],
        "head_count": data["head_count"],
        "manure_handling": data["manure_handling"],
        "open_lot_area_sqft": q2(data["open_lot_area_sqft"]),
        "discharge_potential": data["discharge_potential"],
        "has_conservation_plan": data["has_conservation_plan"],
    }
    fields.update(operation_animal_units_and_class(fields))
    fields.update(operation_design_production(fields))
    fields.update(
        {
            "recorded_annual_manure_gallons": q2(0),
            "design_storage_days": 0,
            "compliance_posture": "OPEN",
            "open_finding_count": 0,
            "open_discharge_incident_count": 0,
        }
    )
    op = new_row("operations", fields)
    return one(op, 201)


PATCH_OPERATION_SPEC = {
    "county": F("string", required=False),
    "head_count": F("int", required=False, ge=1),
    "manure_handling": F("enum", required=False, enum=("LIQUID", "DRY")),
    "open_lot_area_sqft": F("number", required=False, ge=0),
    "discharge_potential": F("enum", required=False, enum=("NONE", "STORMWATER_ONLY", "CONTINUOUS")),
    "has_conservation_plan": F("bool", required=False),
}


@app.patch("/cafo/operations/<rid>")
def patch_operation(rid):
    auth("Operator", "ComplianceAdmin")
    require_owner(rid)
    op = need("operations", rid)
    body = raw_body()
    data = validate(body, PATCH_OPERATION_SPEC)
    for key in PATCH_OPERATION_SPEC:
        if key in body and data[key] is not None:
            op[key] = q2(data[key]) if key == "open_lot_area_sqft" else data[key]
    recompute_operation(op)
    bump_operation_version(op)
    return one(op)


@app.get("/cafo/operations/<rid>")
def get_operation(rid):
    return read_one("operations", rid, "Operator", "CertifiedPlanner", "StateReviewer", "ComplianceAdmin")


@app.get("/cafo/operations")
def list_operations():
    auth("StateReviewer", "ComplianceAdmin")
    return listing("operations", ("county", "size_class", "compliance_posture"))


@app.get("/cafo/operations/<rid>/nutrient-summary")
def operation_nutrient_summary(rid):
    auth("Operator", "CertifiedPlanner", "StateReviewer", "ComplianceAdmin")
    op = get("operations", rid)
    if op is not None:
        require_owner(op["id"])
    op = need("operations", rid)
    basis = qarg("basis") or "DESIGN_BASIS"
    if basis not in ("DESIGN_BASIS", "RECORDS_BASIS"):
        fail("ERR_INVALID_REQUEST", "basis must be DESIGN_BASIS or RECORDS_BASIS.")
    raw_year = qarg("year")
    if raw_year is not None:
        try:
            year = int(raw_year)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "year must be an integer.")
    else:
        year = now().year
    land, transferred = records_basis(op["id"], year)
    n, p = nutrient_rollup(op["id"], year)
    data = {
        "basis": basis,
        "year": year,
        "design_annual_manure_gallons": op["design_annual_manure_gallons"],
        "recorded_annual_manure_gallons": q2(land + transferred),
        "recorded_land_applied_gallons": land,
        "recorded_transferred_gallons": transferred,
        "total_n_applied_lbs": n,
        "total_p2o5_applied_lbs": p,
        "design_storage_days": op["design_storage_days"],
        "compliance_posture": op["compliance_posture"],
    }
    return jsonify_pair(ok_object(data))


# ==========================================================================
# Hauler
# ==========================================================================

HAULER_SPEC = {
    "business_name": F("string"),
    "license_number": F("string"),
    "license_expires_on": F("datetime"),
    "certified_applicator": F("bool", required=False, default=False),
}


@app.post("/cafo/haulers")
def create_hauler():
    auth("ComplianceAdmin")
    data = validate(raw_body(), HAULER_SPEC)
    h = new_row(
        "haulers",
        {
            "business_name": data["business_name"],
            "license_number": data["license_number"],
            "license_expires_on": fmt_dt(data["license_expires_on"]),
            "certified_applicator": data["certified_applicator"],
            "hauler_status": "ACTIVE",
        },
    )
    h["hauler_status"] = calc.hauler_status_of(h)
    return one(h, 201)


@app.get("/cafo/haulers/<rid>")
def get_hauler(rid):
    auth("Operator", "StateReviewer", "ComplianceAdmin", "Hauler")
    if get("haulers", rid) is not None:
        require_hauler(rid)
    h = need("haulers", rid)
    refresh_hauler(h)
    return one(h)


@app.get("/cafo/haulers")
def list_haulers():
    auth("Operator", "StateReviewer", "ComplianceAdmin")
    for h in rows("haulers"):
        refresh_hauler(h)
    return listing("haulers", ("hauler_status",))


# ==========================================================================
# Permit
# ==========================================================================

PERMIT_SPEC = {
    "operation_id": F("id"),
    "permit_type": F("enum", enum=("INDIVIDUAL", "GENERAL")),
    "effective_on": F("datetime"),
}


@app.post("/cafo/permits")
def create_permit():
    auth("Operator")
    body = raw_body()
    require_owner(body.get("operation_id") if isinstance(body.get("operation_id"), str) else None)
    op = fk("operations", body, "operation_id")
    data = validate(body, PERMIT_SPEC)
    if op is None:
        fail("ERR_OPERATION_NOT_FOUND", "operation_id is required.")
    p = new_row(
        "permits",
        {
            "operation_id": op["id"],
            "permit_type": data["permit_type"],
            "effective_on": fmt_dt(data["effective_on"]),
            "expiration_on": None,
            "renewal_window_opens_on": None,
            "renewal_due_on": None,
            "coverage_status": "DRAFT_APPLICATION",
            "compliance_status": "IN_GOOD_STANDING",
            "renewal_submitted_at": None,
            "is_late_renewal": False,
            "gross_fee": None,
            "conservation_discount_pct": None,
            "conservation_discount_amount": None,
            "net_fee": None,
            "late_surcharge_amount": None,
            "total_due": None,
        },
    )
    return one(p, 201)


def _permit_interval(p):
    start = parse_dt(p["effective_on"])
    end = parse_dt(p["expiration_on"]) if p.get("expiration_on") else add_years(
        start, calc.COVERAGE_TERM_YEARS
    )
    return start, end


@app.post("/cafo/permits/<rid>/submit")
def permit_submit(rid):
    auth("Operator")
    p = get("permits", rid)
    if p is not None:
        require_owner(p.get("operation_id"))
    p = need("permits", rid)
    no_body(raw_body())
    if p["coverage_status"] != "DRAFT_APPLICATION":
        fail("ERR_PERMIT_STATE_INVALID", "submit is not declared from %s." % p["coverage_status"])
    a_start, a_end = _permit_interval(p)
    for other in permits_of(p["operation_id"]):
        if other["id"] == p["id"]:
            continue
        if other["coverage_status"] not in ("SUBMITTED", "COVERED", "RENEWAL_PENDING"):
            continue
        b_start, b_end = _permit_interval(other)
        if a_start < b_end and b_start < a_end:
            fail(
                "ERR_PERMIT_COVERAGE_OVERLAP",
                "The requested coverage interval intersects an existing active coverage interval.",
            )
    set_fields("permits", p, {"coverage_status": "SUBMITTED"})
    return one(p)


@app.post("/cafo/permits/<rid>/issue-coverage")
def permit_issue_coverage(rid):
    auth("StateReviewer")
    p = need("permits", rid)
    no_body(raw_body())
    if p["coverage_status"] != "SUBMITTED":
        fail("ERR_PERMIT_STATE_INVALID", "issue-coverage is not declared from %s." % p["coverage_status"])
    op = need("operations", p["operation_id"])
    check_not_suspended(op)
    stamp_coverage_dates(p, parse_dt(p["effective_on"]))
    p["coverage_status"] = "COVERED"
    touch("permits", p)
    return one(p)


@app.post("/cafo/permits/<rid>/initiate-renewal")
def permit_initiate_renewal(rid):
    auth("Operator")
    p = get("permits", rid)
    if p is not None:
        require_owner(p.get("operation_id"))
    p = need("permits", rid)
    no_body(raw_body())
    if p["coverage_status"] != "COVERED":
        fail("ERR_PERMIT_STATE_INVALID", "initiate-renewal is not declared from %s." % p["coverage_status"])
    opens = parse_dt(p["renewal_window_opens_on"]) if p.get("renewal_window_opens_on") else None
    if opens is None or now() < opens:
        fail("ERR_RENEWAL_WINDOW_NOT_OPEN", "The renewal window is not open yet.")
    op = need("operations", p["operation_id"])
    p["renewal_submitted_at"] = fmt_dt(now())
    due = parse_dt(p["renewal_due_on"]) if p.get("renewal_due_on") else None
    p["is_late_renewal"] = bool(due is not None and now() > due)
    p.update(permit_renewal_fee(p, op))
    p["coverage_status"] = "RENEWAL_PENDING"
    touch("permits", p)
    return one(p)


@app.post("/cafo/permits/<rid>/complete-renewal")
def permit_complete_renewal(rid):
    auth("StateReviewer")
    p = need("permits", rid)
    no_body(raw_body())
    if p["coverage_status"] != "RENEWAL_PENDING":
        fail("ERR_PERMIT_STATE_INVALID", "complete-renewal is not declared from %s." % p["coverage_status"])
    op = need("operations", p["operation_id"])
    check_not_suspended(op)
    if not any(
        pl.get("operation_id") == op["id"] and pl["plan_status"] == "APPROVED"
        for pl in DB["plans"].values()
    ):
        fail(
            "ERR_PLAN_NOT_APPROVED",
            "The operation has no APPROVED nutrient management plan.",
        )
    prior_expiration = parse_dt(p["expiration_on"])
    stamp_coverage_dates(p, prior_expiration)
    p["coverage_status"] = "COVERED"
    touch("permits", p)
    return one(p)


@app.get("/cafo/permits/<rid>")
def get_permit(rid):
    return read_one("permits", rid, "Operator", "CertifiedPlanner", "StateReviewer", "ComplianceAdmin")


@app.get("/cafo/permits")
def list_permits():
    auth("Operator", "CertifiedPlanner", "StateReviewer", "ComplianceAdmin")
    return listing("permits", ("operation_id", "coverage_status", "compliance_status"))


# ==========================================================================
# NutrientManagementPlan
# ==========================================================================

PLAN_SPEC = {
    "operation_id": F("id"),
    "permit_id": F("id"),
    "plan_year": F("int"),
    "allowed_application_methods": F("enum_array", enum=METHODS),
    "winter_application_allowed": F("bool", required=False, default=False),
    "supersedes_plan_id": F("id", required=False, default=None, nullable=True),
    "expected_operation_version": F("int"),
}


@app.post("/cafo/nutrient-plans")
def create_plan():
    auth("Operator", "CertifiedPlanner")
    body = raw_body()
    require_owner(body.get("operation_id") if isinstance(body.get("operation_id"), str) else None)
    op = fk("operations", body, "operation_id")
    permit = fk("permits", body, "permit_id")
    fk("plans", body, "supersedes_plan_id")
    data = validate(body, PLAN_SPEC)
    if op is None:
        fail("ERR_OPERATION_NOT_FOUND", "operation_id is required.")
    if permit is None:
        fail("ERR_PERMIT_NOT_FOUND", "permit_id is required.")
    if data["expected_operation_version"] != op["version"]:
        fail(
            "ERR_STALE_OPERATION_VERSION",
            "expected_operation_version %s does not match the current operation version %s."
            % (data["expected_operation_version"], op["version"]),
        )
    plan = new_row(
        "plans",
        {
            "operation_id": op["id"],
            "permit_id": permit["id"],
            "plan_year": data["plan_year"],
            "supersedes_plan_id": data["supersedes_plan_id"],
            "allowed_application_methods": data["allowed_application_methods"],
            "winter_application_allowed": data["winter_application_allowed"],
            "plan_status": "DRAFT",
            "certifying_planner_user_id": None,
            "certified_at": None,
            "approved_at": None,
            "revision_count": 0,
        },
    )
    bump_operation_version(op)
    return one(plan, 201)


PATCH_PLAN_SPEC = {
    "plan_year": F("int", required=False),
    "allowed_application_methods": F("enum_array", required=False, enum=METHODS),
    "winter_application_allowed": F("bool", required=False),
}


@app.patch("/cafo/nutrient-plans/<rid>")
def patch_plan(rid):
    auth("CertifiedPlanner")
    plan = need("plans", rid)
    body = raw_body()
    data = validate(body, PATCH_PLAN_SPEC)
    if plan["plan_status"] not in ("DRAFT", "REVISION_REQUIRED"):
        fail("ERR_PLAN_STATE_INVALID", "A plan in %s cannot be revised." % plan["plan_status"])
    for key in PATCH_PLAN_SPEC:
        if key in body and data[key] is not None:
            plan[key] = data[key]
    plan["plan_status"] = "DRAFT"
    plan["certifying_planner_user_id"] = None
    plan["certified_at"] = None
    touch("plans", plan)
    return one(plan)


@app.post("/cafo/nutrient-plans/<rid>/certify")
def plan_certify(rid):
    auth("CertifiedPlanner")
    plan = need("plans", rid)
    no_body(raw_body())
    if plan["plan_status"] != "DRAFT":
        fail("ERR_PLAN_STATE_INVALID", "certify is not declared from %s." % plan["plan_status"])
    permit = need("permits", plan["permit_id"])
    if permit["coverage_status"] not in ("COVERED", "RENEWAL_PENDING"):
        fail("ERR_PERMIT_COVERAGE_REQUIRED", "The plan's permit is not in force.")
    op = need("operations", plan["operation_id"])
    if int(op["design_storage_days"]) < MIN_STORAGE_DAYS:
        fail(
            "ERR_INSUFFICIENT_STORAGE_DAYS",
            "design_storage_days %s is below the %s day minimum."
            % (op["design_storage_days"], MIN_STORAGE_DAYS),
        )
    if not any(b.get("plan_id") == plan["id"] for b in DB["budgets"].values()):
        fail("ERR_NO_FIELD_BUDGETS", "The plan has no field nutrient budgets.")
    plan["plan_status"] = "CERTIFIED"
    plan["certifying_planner_user_id"] = g.user_id
    plan["certified_at"] = fmt_dt(now())
    touch("plans", plan)
    return one(plan)


@app.post("/cafo/nutrient-plans/<rid>/submit")
def plan_submit(rid):
    auth("Operator")
    plan = get("plans", rid)
    if plan is not None:
        require_owner(plan.get("operation_id"))
    plan = need("plans", rid)
    no_body(raw_body())
    if plan["plan_status"] != "CERTIFIED":
        fail("ERR_PLAN_STATE_INVALID", "submit is not declared from %s." % plan["plan_status"])
    set_fields("plans", plan, {"plan_status": "SUBMITTED"})
    return one(plan)


@app.post("/cafo/nutrient-plans/<rid>/approve")
def plan_approve(rid):
    auth("StateReviewer")
    plan = need("plans", rid)
    no_body(raw_body())
    if plan["plan_status"] != "SUBMITTED":
        fail("ERR_PLAN_STATE_INVALID", "approve is not declared from %s." % plan["plan_status"])
    op = need("operations", plan["operation_id"])
    check_not_suspended(op)
    check_open(op)
    plan["plan_status"] = "APPROVED"
    plan["approved_at"] = fmt_dt(now())
    touch("plans", plan)
    lock_budgets(plan["id"], "ACTIVE")
    prior_id = plan.get("supersedes_plan_id")
    if prior_id:
        prior = get("plans", prior_id)
        if prior is not None and prior["plan_status"] == "APPROVED":
            set_fields("plans", prior, {"plan_status": "SUPERSEDED"})
            lock_budgets(prior["id"], "LOCKED")
    recompute_operation(op)
    return one(plan)


@app.post("/cafo/nutrient-plans/<rid>/require-revision")
def plan_require_revision(rid):
    auth("StateReviewer")
    plan = need("plans", rid)
    no_body(raw_body())
    if plan["plan_status"] != "SUBMITTED":
        fail("ERR_PLAN_STATE_INVALID", "require-revision is not declared from %s." % plan["plan_status"])
    plan["plan_status"] = "REVISION_REQUIRED"
    plan["revision_count"] = int(plan.get("revision_count", 0)) + 1
    touch("plans", plan)
    lock_budgets(plan["id"], "LOCKED")
    return one(plan)


@app.get("/cafo/nutrient-plans/<rid>")
def get_plan(rid):
    return read_one("plans", rid, "Operator", "CertifiedPlanner", "StateReviewer", "ComplianceAdmin")


@app.get("/cafo/nutrient-plans")
def list_plans():
    auth("Operator", "CertifiedPlanner", "StateReviewer", "ComplianceAdmin")
    return listing(
        "plans",
        ("operation_id", "permit_id", "supersedes_plan_id", "plan_status"),
        ("plan_year",),
    )


# ==========================================================================
# Field
# ==========================================================================

FIELD_SPEC = {
    "operation_id": F("id"),
    "field_name": F("string"),
    "total_acres": F("number", gt=0),
    "distance_to_water_ft": F("number", ge=0),
    "has_tile_inlet": F("bool", required=False, default=False),
    "slope_pct": F("number", ge=0),
    "water_frontage_ft": F("number", ge=0),
}


@app.post("/cafo/fields")
def create_field():
    auth("Operator", "CertifiedPlanner")
    body = raw_body()
    require_owner(body.get("operation_id") if isinstance(body.get("operation_id"), str) else None)
    op = fk("operations", body, "operation_id")
    data = validate(body, FIELD_SPEC)
    if op is None:
        fail("ERR_OPERATION_NOT_FOUND", "operation_id is required.")
    fields = {
        "operation_id": op["id"],
        "field_name": data["field_name"],
        "total_acres": q2(data["total_acres"]),
        "distance_to_water_ft": q2(data["distance_to_water_ft"]),
        "has_tile_inlet": data["has_tile_inlet"],
        "slope_pct": q2(data["slope_pct"]),
        "water_frontage_ft": q2(data["water_frontage_ft"]),
    }
    fields.update(field_setback_and_net_acres(fields))
    fields["last_application_on"] = None
    f = new_row("fields", fields)
    return one(f, 201)


@app.get("/cafo/fields/<rid>")
def get_field(rid):
    return read_one("fields", rid, "Operator", "CertifiedPlanner", "StateReviewer", "ComplianceAdmin")


@app.get("/cafo/fields")
def list_fields():
    auth("Operator", "CertifiedPlanner", "StateReviewer", "ComplianceAdmin")
    return listing("fields", ("operation_id",))


# ==========================================================================
# SoilTest
# ==========================================================================

SOIL_TEST_SPEC = {
    "field_id": F("id"),
    "sampled_on": F("datetime"),
    "lab_name": F("string"),
    "soil_test_p_ppm": F("number", ge=0),
    "soil_test_k_ppm": F("number", ge=0),
    "organic_matter_pct": F("number", ge=0),
}


@app.post("/cafo/soil-tests")
def create_soil_test():
    auth("Operator", "CertifiedPlanner")
    body = raw_body()
    probe = get("fields", body.get("field_id")) if isinstance(body.get("field_id"), str) else None
    if probe is not None:
        require_owner(probe.get("operation_id"))
    field = fk("fields", body, "field_id")
    data = validate(body, SOIL_TEST_SPEC)
    if field is None:
        fail("ERR_FIELD_NOT_FOUND", "field_id is required.")
    check_not_future(data["sampled_on"], "sampled_on")
    fields = {
        "field_id": field["id"],
        "sampled_on": fmt_dt(data["sampled_on"]),
        "lab_name": data["lab_name"],
        "soil_test_p_ppm": q2(data["soil_test_p_ppm"]),
        "soil_test_k_ppm": q2(data["soil_test_k_ppm"]),
        "organic_matter_pct": q2(data["organic_matter_pct"]),
    }
    fields.update(soil_test_p_index(fields, field))
    st = new_row("soil_tests", fields)
    return one(st, 201)


@app.get("/cafo/soil-tests/<rid>")
def get_soil_test(rid):
    return read_one("soil_tests", rid, "Operator", "CertifiedPlanner", "StateReviewer", "ComplianceAdmin")


@app.get("/cafo/soil-tests")
def list_soil_tests():
    auth("Operator", "CertifiedPlanner", "StateReviewer", "ComplianceAdmin")
    for st in rows("soil_tests"):
        refresh_soil_test(st)
    return listing("soil_tests", ("field_id",))


# ==========================================================================
# FieldNutrientBudget
# ==========================================================================

BUDGET_SPEC = {
    "plan_id": F("id"),
    "field_id": F("id"),
    "soil_test_id": F("id"),
    "crop": F("enum", enum=("CORN_GRAIN", "SOYBEAN", "ALFALFA", "GRASS_HAY")),
    "yield_goal": F("number", gt=0),
    "previous_crop": F("enum", enum=("CORN_GRAIN", "SOYBEAN", "ALFALFA", "GRASS_HAY", "NONE")),
    "planned_application_method": F("enum", enum=METHODS),
}


@app.post("/cafo/field-budgets")
def create_budget():
    auth("CertifiedPlanner")
    body = raw_body()
    plan = fk("plans", body, "plan_id")
    field = fk("fields", body, "field_id")
    soil = fk("soil_tests", body, "soil_test_id")
    data = validate(body, BUDGET_SPEC)
    if plan is None:
        fail("ERR_PLAN_NOT_FOUND", "plan_id is required.")
    if field is None:
        fail("ERR_FIELD_NOT_FOUND", "field_id is required.")
    if soil is None:
        fail("ERR_SOIL_TEST_NOT_FOUND", "soil_test_id is required.")
    if plan["plan_status"] not in ("DRAFT", "APPROVED"):
        fail(
            "ERR_PLAN_STATE_INVALID",
            "A budget cannot be added to a plan in %s." % plan["plan_status"],
        )
    refresh_soil_test(soil)
    if not soil.get("is_valid") or soil.get("field_id") != field["id"]:
        fail(
            "ERR_NO_VALID_SOIL_TEST",
            "The soil test is expired or belongs to a different field.",
        )
    op = need("operations", plan["operation_id"])
    derived = budget_allowable_rate(
        op,
        field,
        soil,
        data["crop"],
        data["yield_goal"],
        data["previous_crop"],
        data["planned_application_method"],
    )
    if derived["allowable_rate_gal_per_acre"] <= 0:
        fail("ERR_ZERO_ALLOWABLE_RATE", "The computed allowable application rate is zero.")
    fields = {
        "plan_id": plan["id"],
        "field_id": field["id"],
        "soil_test_id": soil["id"],
        "crop": data["crop"],
        "yield_goal": q2(data["yield_goal"]),
        "previous_crop": data["previous_crop"],
        "planned_application_method": data["planned_application_method"],
    }
    fields.update(derived)
    fields["applied_gallons_to_date"] = q2(0)
    fields["remaining_gallons"] = q2(derived["allowable_total_gallons"])
    fields["budget_status"] = "LOCKED"
    b = new_row("budgets", fields)
    return one(b, 201)


@app.get("/cafo/field-budgets/<rid>")
def get_budget(rid):
    return read_one("budgets", rid, "Operator", "CertifiedPlanner", "StateReviewer", "ComplianceAdmin")


@app.get("/cafo/field-budgets")
def list_budgets():
    auth("Operator", "CertifiedPlanner", "StateReviewer", "ComplianceAdmin")
    return listing("budgets", ("plan_id", "field_id", "soil_test_id", "budget_status"))


# ==========================================================================
# ManureStorage
# ==========================================================================

STORAGE_SPEC = {
    "operation_id": F("id"),
    "structure_name": F("string"),
    "structure_type": F("enum", enum=("EARTHEN_LAGOON", "CONCRETE_TANK", "STACKING_PAD")),
    "surface_area_sqft": F("number", gt=0),
    "total_depth_in": F("number", gt=0),
    "required_freeboard_in": F("number", required=False, default=D(24), ge=0),
}


@app.post("/cafo/manure-storages")
def create_storage():
    auth("Operator")
    body = raw_body()
    require_owner(body.get("operation_id") if isinstance(body.get("operation_id"), str) else None)
    op = fk("operations", body, "operation_id")
    data = validate(body, STORAGE_SPEC)
    if op is None:
        fail("ERR_OPERATION_NOT_FOUND", "operation_id is required.")
    if data["required_freeboard_in"] >= data["total_depth_in"]:
        fail("ERR_INVALID_REQUEST", "required_freeboard_in must be less than total_depth_in.")
    fields = {
        "operation_id": op["id"],
        "structure_name": data["structure_name"],
        "structure_type": data["structure_type"],
        "surface_area_sqft": q2(data["surface_area_sqft"]),
        "total_depth_in": q2(data["total_depth_in"]),
        "required_freeboard_in": q2(data["required_freeboard_in"]),
    }
    fields.update(storage_geometry(fields))
    fields.update(
        {
            "cumulative_intake_gallons": q2(0),
            "precipitation_adjustment_gallons": q2(0),
            "cumulative_outflow_gallons": q2(0),
            "current_volume_gallons": q2(0),
            "committed_outflow_gallons": q2(0),
            "available_capacity_gallons": fields["operating_capacity_gallons"],
            "days_of_storage_available": 0,
            "storage_status": "IN_SERVICE",
            "last_inspected_on": None,
        }
    )
    st = new_row("storages", fields)
    recompute_storage(st, op)
    calc.set_derived("operations", op, {"design_storage_days": design_storage_days(op)})
    return one(st, 201)


@app.post("/cafo/manure-storages/<rid>/intake")
def storage_intake(rid):
    auth("Operator")
    st = get("storages", rid)
    if st is not None:
        require_owner(st.get("operation_id"))
    st = need("storages", rid)
    data = validate(raw_body(), {"gallons": F("number", gt=0)})
    op = need("operations", st["operation_id"])
    check_not_suspended(op)
    gallons = q2(data["gallons"])
    if D(st["current_volume_gallons"]) + gallons > D(st["operating_capacity_gallons"]):
        fail(
            "ERR_STORAGE_OPERATING_CAPACITY_EXCEEDED",
            "The intake would push the structure above its operating capacity.",
        )
    st["cumulative_intake_gallons"] = q2(D(st["cumulative_intake_gallons"]) + gallons)
    touch("storages", st)
    recompute_operation(op)
    return one(st)


@app.post("/cafo/manure-storages/<rid>/return-to-service")
def storage_return_to_service(rid):
    auth("Operator")
    st = get("storages", rid)
    if st is not None:
        require_owner(st.get("operation_id"))
    st = need("storages", rid)
    no_body(raw_body())
    if st["storage_status"] not in ("FREEBOARD_ALERT", "OVERFLOW_IMMINENT"):
        fail("ERR_STORAGE_STATE_INVALID", "The structure is already IN_SERVICE.")
    insp = latest_inspection(st["id"])
    if (
        insp is None
        or D(insp["freeboard_deficit_in"]) != 0
        or insp["visual_condition"] != "NORMAL"
    ):
        fail(
            "ERR_STORAGE_STATE_INVALID",
            "The latest inspection still shows a freeboard deficit or an abnormal condition.",
        )
    set_fields("storages", st, {"storage_status": "IN_SERVICE"})
    op = need("operations", st["operation_id"])
    recompute_operation(op)
    return one(st)


@app.get("/cafo/manure-storages/<rid>")
def get_storage(rid):
    return read_one("storages", rid, "Operator", "CertifiedPlanner", "StateReviewer", "ComplianceAdmin")


@app.get("/cafo/manure-storages")
def list_storages():
    auth("Operator", "CertifiedPlanner", "StateReviewer", "ComplianceAdmin")
    return listing("storages", ("operation_id", "storage_status"))


@app.get("/cafo/manure-storages/<rid>/capacity-projection")
def storage_capacity_projection(rid):
    auth("Operator", "CertifiedPlanner", "StateReviewer", "ComplianceAdmin")
    st = get("storages", rid)
    if st is not None:
        require_owner(st.get("operation_id"))
    st = need("storages", rid)
    basis = qarg("basis") or "AVAILABLE_BASIS"
    if basis not in ("AVAILABLE_BASIS", "DESIGN_BASIS"):
        fail("ERR_INVALID_REQUEST", "basis must be AVAILABLE_BASIS or DESIGN_BASIS.")
    op = need("operations", st["operation_id"])
    factor = seasonal_factor_for(st["structure_type"])
    eff = effective_daily(op, factor)
    if basis == "AVAILABLE_BASIS":
        numerator = D(st["available_capacity_gallons"])
        if numerator < 0:
            numerator = D(0)
        days = 0 if eff <= 0 else ifloor(numerator / eff)
    else:
        total = sum((D(s["operating_capacity_gallons"]) for s in storages_of(op["id"])), D(0))
        days = 0 if eff <= 0 else ifloor(total / eff)
    data = {
        "basis": basis,
        "seasonal_factor": q2(factor),
        "effective_daily_gallons": eff,
        "operating_capacity_gallons": st["operating_capacity_gallons"],
        "available_capacity_gallons": st["available_capacity_gallons"],
        "days_of_storage": days,
        "min_storage_days_met": days >= MIN_STORAGE_DAYS,
    }
    return jsonify_pair(ok_object(data))


# ==========================================================================
# StorageInspection
# ==========================================================================

STORAGE_INSPECTION_SPEC = {
    "storage_id": F("id"),
    "inspected_on": F("datetime"),
    "inspector_name": F("string"),
    "measured_freeboard_in": F("number", ge=0),
    "visual_condition": F("enum", enum=("NORMAL", "SEEPAGE", "EROSION", "CRACKING")),
}


@app.post("/cafo/storage-inspections")
def create_storage_inspection():
    auth("Operator", "ComplianceAdmin")
    body = raw_body()
    probe = get("storages", body.get("storage_id")) if isinstance(body.get("storage_id"), str) else None
    if probe is not None:
        require_owner(probe.get("operation_id"))
    st = fk("storages", body, "storage_id")
    data = validate(body, STORAGE_INSPECTION_SPEC)
    if st is None:
        fail("ERR_STORAGE_NOT_FOUND", "storage_id is required.")
    if data["measured_freeboard_in"] > D(st["total_depth_in"]):
        fail("ERR_INVALID_REQUEST", "measured_freeboard_in must not exceed total_depth_in.")
    check_not_future(data["inspected_on"], "inspected_on")

    freeboard = q2(data["measured_freeboard_in"])
    deficit = D(st["required_freeboard_in"]) - freeboard
    if deficit < 0:
        deficit = D(0)
    deficit = q2(deficit)
    volume = measured_volume(st, freeboard)
    insp = new_row(
        "storage_inspections",
        {
            "storage_id": st["id"],
            "inspected_on": fmt_dt(data["inspected_on"]),
            "inspector_name": data["inspector_name"],
            "measured_freeboard_in": freeboard,
            "visual_condition": data["visual_condition"],
            "measured_volume_gallons": volume,
            "freeboard_deficit_in": deficit,
            "alert_raised": bool(deficit > 0 or data["visual_condition"] != "NORMAL"),
        },
    )
    op = need("operations", st["operation_id"])
    recompute_storage(st, op)
    st["precipitation_adjustment_gallons"] = q2(
        volume - D(st["cumulative_intake_gallons"]) + D(st["cumulative_outflow_gallons"])
    )
    recompute_storage(st, op)
    if freeboard <= OVERFLOW_FREEBOARD_IN:
        set_fields("storages", st, {"storage_status": "OVERFLOW_IMMINENT"})
    elif deficit > 0 and st["storage_status"] == "IN_SERVICE":
        set_fields("storages", st, {"storage_status": "FREEBOARD_ALERT"})
    recompute_operation(op)
    return one(insp, 201)


@app.get("/cafo/storage-inspections/<rid>")
def get_storage_inspection(rid):
    return read_one(
        "storage_inspections", rid, "Operator", "CertifiedPlanner", "StateReviewer", "ComplianceAdmin"
    )


@app.get("/cafo/storage-inspections")
def list_storage_inspections():
    auth("Operator", "CertifiedPlanner", "StateReviewer", "ComplianceAdmin")
    return listing("storage_inspections", ("storage_id",))


# ==========================================================================
# LandApplicationEvent
# ==========================================================================

EVENT_SPEC = {
    "plan_id": F("id"),
    "budget_id": F("id"),
    "storage_id": F("id"),
    "applied_on": F("datetime"),
    "gallons_applied": F("number", gt=0),
    "acres_treated": F("number", gt=0),
    "application_method": F("enum", enum=METHODS),
    "setback_maintained_ft": F("number", ge=0),
    "soil_condition": F("enum", enum=("DRY", "MOIST", "SATURATED", "FROZEN", "SNOW_COVERED")),
    "precipitation_forecast_in_24h": F("number", required=False, default=D(0), ge=0),
    "applicator_name": F("string"),
}


@app.post("/cafo/application-events")
def create_event():
    auth("Operator")
    body = raw_body()
    probe = get("plans", body.get("plan_id")) if isinstance(body.get("plan_id"), str) else None
    if probe is not None:
        require_owner(probe.get("operation_id"))
    probe_st = get("storages", body.get("storage_id")) if isinstance(body.get("storage_id"), str) else None
    if probe_st is not None:
        require_owner(probe_st.get("operation_id"))

    plan = fk("plans", body, "plan_id")
    budget = fk("budgets", body, "budget_id")
    storage = fk("storages", body, "storage_id")
    data = validate(body, EVENT_SPEC)
    if plan is None:
        fail("ERR_PLAN_NOT_FOUND", "plan_id is required.")
    if budget is None:
        fail("ERR_BUDGET_NOT_FOUND", "budget_id is required.")
    if storage is None:
        fail("ERR_STORAGE_NOT_FOUND", "storage_id is required.")

    op = need("operations", plan["operation_id"])
    permit = get("permits", plan.get("permit_id"))
    if permit is not None and permit["coverage_status"] == "EXPIRED":
        fail("ERR_PERMIT_COVERAGE_EXPIRED", "The permit coverage has expired.")
    if plan["plan_status"] != "APPROVED":
        fail("ERR_PLAN_NOT_APPROVED", "The plan is not APPROVED.")
    if budget["budget_status"] != "ACTIVE":
        fail("ERR_BUDGET_NOT_ACTIVE", "The field nutrient budget is LOCKED.")
    check_not_suspended(op)
    check_open(op)
    if data["soil_condition"] == "FROZEN":
        fail("ERR_FROZEN_GROUND_APPLICATION", "Application on frozen ground is prohibited.")
    if data["soil_condition"] == "SATURATED":
        fail("ERR_SATURATED_SOIL_APPLICATION", "Application on saturated soil is prohibited.")
    applied_on = data["applied_on"]
    if applied_on.month in (12, 1, 2) and not plan.get("winter_application_allowed"):
        fail("ERR_WINTER_WINDOW_APPLICATION", "The plan does not authorise winter application.")
    if data["precipitation_forecast_in_24h"] >= PRECIPITATION_LIMIT_IN:
        fail("ERR_PRECIPITATION_RISK", "The 24-hour precipitation forecast is too high.")
    field = need("fields", budget["field_id"])
    required = q2(
        D(field["required_setback_ft"]) * METHOD_SETBACK_MULTIPLIER[data["application_method"]]
    )
    if D(data["setback_maintained_ft"]) < required:
        fail("ERR_SETBACK_VIOLATION", "setback_maintained_ft is below the required %s ft." % required)
    check_not_future(applied_on, "applied_on")
    last = field.get("last_application_on")
    if last:
        delta = abs((applied_on - parse_dt(last)).total_seconds())
        if delta < REAPPLICATION_INTERVAL_DAYS * 86400:
            fail(
                "ERR_REAPPLICATION_INTERVAL_CONFLICT",
                "The application is within %s days of another application on this field."
                % REAPPLICATION_INTERVAL_DAYS,
            )
    if data["application_method"] not in (plan.get("allowed_application_methods") or []):
        fail(
            "ERR_APPLICATION_METHOD_NOT_IN_PLAN",
            "%s is not authorised by the plan." % data["application_method"],
        )
    acres = q2(data["acres_treated"])
    if acres > D(field["net_applicable_acres"]):
        fail("ERR_ACRES_EXCEED_NET_APPLICABLE", "acres_treated exceeds the field's net applicable acres.")
    gallons = q2(data["gallons_applied"])
    rate = q2(gallons / acres)
    if rate > D(budget["allowable_rate_gal_per_acre"]):
        fail("ERR_RATE_EXCEEDS_LIMIT", "The per-acre rate exceeds the budget's allowable rate.")
    if gallons > D(budget["remaining_gallons"]):
        fail("ERR_FIELD_ALLOWANCE_EXCEEDED", "gallons_applied exceeds the budget's remaining gallons.")
    headroom = D(storage["current_volume_gallons"]) - D(storage["committed_outflow_gallons"])
    if gallons > headroom:
        fail(
            "ERR_INSUFFICIENT_STORAGE_VOLUME",
            "The structure holds only %s uncommitted gallons." % headroom,
        )

    n, p = application_load(op, gallons, data["application_method"])
    ev = new_row(
        "events",
        {
            "plan_id": plan["id"],
            "budget_id": budget["id"],
            "storage_id": storage["id"],
            "applied_on": fmt_dt(applied_on),
            "gallons_applied": gallons,
            "acres_treated": acres,
            "application_method": data["application_method"],
            "setback_maintained_ft": q2(data["setback_maintained_ft"]),
            "soil_condition": data["soil_condition"],
            "precipitation_forecast_in_24h": q2(data["precipitation_forecast_in_24h"]),
            "applicator_name": data["applicator_name"],
            "rate_gal_per_acre": rate,
            "n_applied_lbs": n,
            "p2o5_applied_lbs": p,
            "event_status": "RECORDED",
        },
    )
    recompute_operation(op)
    return one(ev, 201)


@app.post("/cafo/application-events/<rid>/verify")
def event_verify(rid):
    auth("CertifiedPlanner")
    ev = need("events", rid)
    no_body(raw_body())
    if ev["event_status"] == "VOIDED":
        fail("ERR_EVENT_ALREADY_TERMINAL", "The event is already VOIDED.")
    plan = need("plans", ev["plan_id"])
    if plan["plan_status"] != "APPROVED":
        fail("ERR_PLAN_NOT_APPROVED", "The plan is not APPROVED.")
    set_fields("events", ev, {"event_status": "VERIFIED"})
    return one(ev)


@app.post("/cafo/application-events/<rid>/void")
def event_void(rid):
    auth("ComplianceAdmin")
    ev = need("events", rid)
    no_body(raw_body())
    if ev["event_status"] == "VOIDED":
        fail("ERR_EVENT_ALREADY_TERMINAL", "The event is already VOIDED.")
    set_fields("events", ev, {"event_status": "VOIDED"})
    plan = need("plans", ev["plan_id"])
    op = need("operations", plan["operation_id"])
    recompute_operation(op)
    return one(ev)


@app.get("/cafo/application-events/<rid>")
def get_event(rid):
    return read_one("events", rid, "Operator", "CertifiedPlanner", "StateReviewer", "ComplianceAdmin")


@app.get("/cafo/application-events")
def list_events():
    auth("Operator", "CertifiedPlanner", "StateReviewer", "ComplianceAdmin")
    return listing("events", ("plan_id", "budget_id", "storage_id", "event_status"))


# ==========================================================================
# ManureTransfer
# ==========================================================================

TRANSFER_SPEC = {
    "operation_id": F("id"),
    "storage_id": F("id"),
    "hauler_id": F("id"),
    "recipient_name": F("string"),
    "recipient_address": F("string"),
    "transferred_on": F("datetime"),
    "gallons_transferred": F("number", gt=0),
    "nutrient_analysis_provided": F("bool", required=False, default=False),
}


@app.post("/cafo/manure-transfers")
def create_transfer():
    auth("Operator")
    body = raw_body()
    require_owner(body.get("operation_id") if isinstance(body.get("operation_id"), str) else None)
    op = fk("operations", body, "operation_id")
    storage = fk("storages", body, "storage_id")
    hauler = fk("haulers", body, "hauler_id")
    data = validate(body, TRANSFER_SPEC)
    if op is None:
        fail("ERR_OPERATION_NOT_FOUND", "operation_id is required.")
    if storage is None:
        fail("ERR_STORAGE_NOT_FOUND", "storage_id is required.")
    if hauler is None:
        fail("ERR_HAULER_NOT_FOUND", "hauler_id is required.")
    check_coverage_not_expired(op["id"])
    check_not_suspended(op)
    check_open(op)
    check_not_future(data["transferred_on"], "transferred_on")
    check_hauler_active(hauler)
    gallons = q2(data["gallons_transferred"])
    headroom = D(storage["current_volume_gallons"]) - D(storage["committed_outflow_gallons"])
    if gallons > headroom:
        fail(
            "ERR_INSUFFICIENT_STORAGE_VOLUME",
            "The structure holds only %s uncommitted gallons." % headroom,
        )
    n, p = transfer_load(op, gallons)
    t = new_row(
        "transfers",
        {
            "operation_id": op["id"],
            "storage_id": storage["id"],
            "hauler_id": hauler["id"],
            "recipient_name": data["recipient_name"],
            "recipient_address": data["recipient_address"],
            "transferred_on": fmt_dt(data["transferred_on"]),
            "gallons_transferred": gallons,
            "nutrient_analysis_provided": data["nutrient_analysis_provided"],
            "recipient_n_lbs": n,
            "recipient_p2o5_lbs": p,
            "recipient_ack_signed_at": None,
            "transfer_status": "INITIATED",
        },
    )
    recompute_operation(op)
    return one(t, 201)


@app.post("/cafo/manure-transfers/<rid>/acknowledge")
def transfer_acknowledge(rid):
    auth("Hauler")
    t = get("transfers", rid)
    if t is not None:
        require_hauler(t.get("hauler_id"))
    t = need("transfers", rid)
    no_body(raw_body())
    if t["transfer_status"] != "INITIATED":
        fail("ERR_TRANSFER_STATE_INVALID", "acknowledge is not declared from %s." % t["transfer_status"])
    hauler = need("haulers", t["hauler_id"])
    check_hauler_active(hauler)
    if (
        not t.get("nutrient_analysis_provided")
        or not (t.get("recipient_name") or "").strip()
        or not (t.get("recipient_address") or "").strip()
    ):
        fail(
            "ERR_RECIPIENT_DOCUMENTATION_MISSING",
            "The recipient documentation is incomplete.",
        )
    t["transfer_status"] = "ACKNOWLEDGED"
    t["recipient_ack_signed_at"] = fmt_dt(now())
    touch("transfers", t)
    recompute_operation(need("operations", t["operation_id"]))
    return one(t)


@app.post("/cafo/manure-transfers/<rid>/complete")
def transfer_complete(rid):
    auth("Hauler")
    t = get("transfers", rid)
    if t is not None:
        require_hauler(t.get("hauler_id"))
    t = need("transfers", rid)
    no_body(raw_body())
    if t["transfer_status"] != "ACKNOWLEDGED":
        fail("ERR_TRANSFER_STATE_INVALID", "complete is not declared from %s." % t["transfer_status"])
    set_fields("transfers", t, {"transfer_status": "COMPLETED"})
    recompute_operation(need("operations", t["operation_id"]))
    return one(t)


@app.post("/cafo/manure-transfers/<rid>/cancel")
def transfer_cancel(rid):
    auth("Operator")
    t = get("transfers", rid)
    if t is not None:
        require_owner(t.get("operation_id"))
    t = need("transfers", rid)
    no_body(raw_body())
    if t["transfer_status"] not in ("INITIATED", "SUSPENDED"):
        fail("ERR_TRANSFER_STATE_INVALID", "cancel is not declared from %s." % t["transfer_status"])
    set_fields("transfers", t, {"transfer_status": "CANCELLED"})
    recompute_operation(need("operations", t["operation_id"]))
    return one(t)


@app.post("/cafo/manure-transfers/<rid>/resume")
def transfer_resume(rid):
    auth("Operator")
    t = get("transfers", rid)
    if t is not None:
        require_owner(t.get("operation_id"))
    t = need("transfers", rid)
    no_body(raw_body())
    if t["transfer_status"] != "SUSPENDED":
        fail("ERR_TRANSFER_STATE_INVALID", "resume is not declared from %s." % t["transfer_status"])
    op = need("operations", t["operation_id"])
    check_open(op)
    hauler = need("haulers", t["hauler_id"])
    check_hauler_active(hauler)
    storage = need("storages", t["storage_id"])
    headroom = D(storage["current_volume_gallons"]) - D(storage["committed_outflow_gallons"])
    if D(t["gallons_transferred"]) > headroom:
        fail(
            "ERR_INSUFFICIENT_STORAGE_VOLUME",
            "The structure holds only %s uncommitted gallons." % headroom,
        )
    set_fields("transfers", t, {"transfer_status": "INITIATED"})
    recompute_operation(op)
    return one(t)


@app.get("/cafo/manure-transfers/<rid>")
def get_transfer(rid):
    auth("Operator", "CertifiedPlanner", "StateReviewer", "ComplianceAdmin", "Hauler")
    t = get("transfers", rid)
    if t is not None:
        require_owner(t.get("operation_id"))
        require_hauler(t.get("hauler_id"))
    t = need("transfers", rid)
    return one(t)


@app.get("/cafo/manure-transfers")
def list_transfers():
    auth("Operator", "CertifiedPlanner", "StateReviewer", "ComplianceAdmin", "Hauler")
    return listing("transfers", ("operation_id", "storage_id", "hauler_id", "transfer_status"))


# ==========================================================================
# IncidentReport
# ==========================================================================

INCIDENT_SPEC = {
    "operation_id": F("id"),
    "incident_type": F("enum", enum=("MORTALITY", "DISCHARGE", "SPILL")),
    "subject_storage_id": F("id", required=False, default=None, nullable=True),
    "subject_field_id": F("id", required=False, default=None, nullable=True),
    "discovered_at": F("datetime"),
    "description": F("string"),
    "mortality_head_count": F("int", required=False, default=0, ge=0),
    "disposal_method": F(
        "enum",
        required=False,
        default=None,
        nullable=True,
        enum=("COMPOSTING", "BURIAL", "INCINERATION", "RENDERING"),
    ),
    "released_gallons": F("number", required=False, default=D(0), ge=0),
    "reached_water": F("bool", required=False, default=False),
}


@app.post("/cafo/incident-reports")
def create_incident():
    auth("Operator")
    body = raw_body()
    require_owner(body.get("operation_id") if isinstance(body.get("operation_id"), str) else None)
    op = fk("operations", body, "operation_id")
    fk("storages", body, "subject_storage_id")
    fk("fields", body, "subject_field_id")
    data = validate(body, INCIDENT_SPEC)
    if op is None:
        fail("ERR_OPERATION_NOT_FOUND", "operation_id is required.")
    kind = data["incident_type"]
    if kind in ("DISCHARGE", "SPILL"):
        if not data["subject_storage_id"] or data["subject_field_id"]:
            fail(
                "ERR_INVALID_REQUEST",
                "A %s report requires subject_storage_id and a null subject_field_id." % kind,
            )
    else:
        if not data["subject_field_id"] or data["subject_storage_id"]:
            fail(
                "ERR_INVALID_REQUEST",
                "A MORTALITY report requires subject_field_id and a null subject_storage_id.",
            )
    check_not_future(data["discovered_at"], "discovered_at")
    fields = {
        "operation_id": op["id"],
        "incident_type": kind,
        "subject_storage_id": data["subject_storage_id"],
        "subject_field_id": data["subject_field_id"],
        "discovered_at": fmt_dt(data["discovered_at"]),
        "description": data["description"],
        "mortality_head_count": data["mortality_head_count"],
        "disposal_method": data["disposal_method"],
        "released_gallons": q2(data["released_gallons"]),
        "reached_water": data["reached_water"],
    }
    fields.update(incident_notification_deadlines(fields, op))
    fields["oral_notified_at"] = None
    fields["notification_late"] = False
    fields["incident_status"] = "OPEN"
    inc = new_row("incidents", fields)
    recompute_operation(op)
    return one(inc, 201)


@app.post("/cafo/incident-reports/<rid>/record-oral-notification")
def incident_record_oral(rid):
    auth("Operator")
    inc = get("incidents", rid)
    if inc is not None:
        require_owner(inc.get("operation_id"))
    inc = need("incidents", rid)
    no_body(raw_body())
    if inc["incident_status"] != "OPEN" or not inc.get("requires_oral_notification"):
        fail(
            "ERR_INCIDENT_STATE_INVALID",
            "record-oral-notification is not declared from %s." % inc["incident_status"],
        )
    inc["incident_status"] = "NOTIFIED"
    inc["oral_notified_at"] = fmt_dt(now())
    deadline = inc.get("oral_notification_deadline_at")
    inc["notification_late"] = bool(deadline and now() > parse_dt(deadline))
    touch("incidents", inc)
    recompute_operation(need("operations", inc["operation_id"]))
    return one(inc)


@app.post("/cafo/incident-reports/<rid>/submit-written-report")
def incident_submit_written(rid):
    auth("Operator")
    inc = get("incidents", rid)
    if inc is not None:
        require_owner(inc.get("operation_id"))
    inc = need("incidents", rid)
    no_body(raw_body())
    if inc["incident_status"] != "NOTIFIED":
        fail(
            "ERR_INCIDENT_STATE_INVALID",
            "submit-written-report is not declared from %s." % inc["incident_status"],
        )
    set_fields("incidents", inc, {"incident_status": "WRITTEN_SUBMITTED"})
    recompute_operation(need("operations", inc["operation_id"]))
    return one(inc)


@app.post("/cafo/incident-reports/<rid>/close")
def incident_close(rid):
    auth("StateReviewer")
    inc = need("incidents", rid)
    no_body(raw_body())
    status = inc["incident_status"]
    ok = status == "WRITTEN_SUBMITTED" or (
        status == "OPEN" and not inc.get("requires_oral_notification")
    )
    if not ok:
        fail("ERR_INCIDENT_STATE_INVALID", "close is not declared from %s." % status)
    set_fields("incidents", inc, {"incident_status": "CLOSED"})
    recompute_operation(need("operations", inc["operation_id"]))
    return one(inc)


@app.get("/cafo/incident-reports/<rid>")
def get_incident(rid):
    return read_one("incidents", rid, "Operator", "CertifiedPlanner", "StateReviewer", "ComplianceAdmin")


@app.get("/cafo/incident-reports")
def list_incidents():
    auth("Operator", "CertifiedPlanner", "StateReviewer", "ComplianceAdmin")
    return listing(
        "incidents",
        ("operation_id", "subject_storage_id", "subject_field_id", "incident_type", "incident_status"),
    )


# ==========================================================================
# Inspection
# ==========================================================================

INSPECTION_SPEC = {
    "operation_id": F("id"),
    "permit_id": F("id"),
    "scheduled_on": F("datetime"),
    "inspection_kind": F("enum", enum=("ROUTINE", "COMPLAINT", "FOLLOW_UP")),
}


@app.post("/cafo/inspections")
def create_inspection():
    auth("StateReviewer")
    body = raw_body()
    op = fk("operations", body, "operation_id")
    permit = fk("permits", body, "permit_id")
    data = validate(body, INSPECTION_SPEC)
    if op is None:
        fail("ERR_OPERATION_NOT_FOUND", "operation_id is required.")
    if permit is None:
        fail("ERR_PERMIT_NOT_FOUND", "permit_id is required.")
    insp = new_row(
        "inspections",
        {
            "operation_id": op["id"],
            "permit_id": permit["id"],
            "scheduled_on": fmt_dt(data["scheduled_on"]),
            "inspection_kind": data["inspection_kind"],
            "inspector_user_id": None,
            "conducted_on": None,
            "findings_count": 0,
            "deficiency_categories": [],
            "response_due_on": None,
            "corrective_action_summary": None,
            "closed_by_user_id": None,
            "inspection_status": "SCHEDULED",
        },
    )
    return one(insp, 201)


@app.post("/cafo/inspections/<rid>/conduct")
def inspection_conduct(rid):
    auth("StateReviewer")
    insp = need("inspections", rid)
    data = validate(
        raw_body(),
        {
            "findings_count": F("int", ge=0),
            "deficiency_categories": F(
                "enum_array_opt", required=False, default=[], nullable=True, enum=DEFICIENCY_CATEGORIES
            ),
        },
    )
    if insp["inspection_status"] != "SCHEDULED":
        fail("ERR_INSPECTION_STATE_INVALID", "conduct is not declared from %s." % insp["inspection_status"])
    permit = need("permits", insp["permit_id"])
    if permit["coverage_status"] not in ("COVERED", "RENEWAL_PENDING"):
        fail("ERR_PERMIT_COVERAGE_REQUIRED", "The permit is not in force.")
    insp["inspection_status"] = "CONDUCTED"
    insp["inspector_user_id"] = g.user_id
    insp["conducted_on"] = fmt_dt(now())
    insp["findings_count"] = data["findings_count"]
    insp["deficiency_categories"] = data["deficiency_categories"] or []
    touch("inspections", insp)
    return one(insp)


@app.post("/cafo/inspections/<rid>/issue-nov")
def inspection_issue_nov(rid):
    auth("StateReviewer")
    insp = need("inspections", rid)
    no_body(raw_body())
    if insp["inspection_status"] != "CONDUCTED":
        fail("ERR_INSPECTION_STATE_INVALID", "issue-nov is not declared from %s." % insp["inspection_status"])
    if int(insp["findings_count"]) < 1:
        fail("ERR_NOV_NOT_WARRANTED", "The inspection recorded no findings.")
    insp["inspection_status"] = "NOV_ISSUED"
    insp["response_due_on"] = fmt_dt(add_days(parse_dt(insp["conducted_on"]), RESPONSE_DAYS))
    touch("inspections", insp)
    permit = get("permits", insp["permit_id"])
    if permit is not None and permit["compliance_status"] == "IN_GOOD_STANDING":
        set_fields("permits", permit, {"compliance_status": "NOTICE_ISSUED"})
    recompute_operation(need("operations", insp["operation_id"]))
    return one(insp)


@app.post("/cafo/inspections/<rid>/submit-response")
def inspection_submit_response(rid):
    auth("Operator")
    insp = get("inspections", rid)
    if insp is not None:
        require_owner(insp.get("operation_id"))
    insp = need("inspections", rid)
    data = validate(raw_body(), {"corrective_action_summary": F("string")})
    if insp["inspection_status"] != "NOV_ISSUED":
        fail(
            "ERR_INSPECTION_STATE_INVALID",
            "submit-response is not declared from %s." % insp["inspection_status"],
        )
    insp["inspection_status"] = "RESPONSE_SUBMITTED"
    insp["corrective_action_summary"] = data["corrective_action_summary"]
    touch("inspections", insp)
    permit = get("permits", insp["permit_id"])
    if permit is not None and permit["compliance_status"] == "NOTICE_ISSUED":
        set_fields("permits", permit, {"compliance_status": "CORRECTIVE_ACTION"})
    recompute_operation(need("operations", insp["operation_id"]))
    return one(insp)


@app.post("/cafo/inspections/<rid>/close")
def inspection_close(rid):
    auth("StateReviewer", "ComplianceAdmin")
    insp = get("inspections", rid)
    if insp is not None and insp.get("inspector_user_id") == g.user_id:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The closing actor must differ from the inspector of record.",
        )
    insp = need("inspections", rid)
    no_body(raw_body())
    status = insp["inspection_status"]
    ok = status == "RESPONSE_SUBMITTED" or (
        status == "CONDUCTED" and int(insp["findings_count"]) == 0
    )
    if not ok:
        fail("ERR_INSPECTION_STATE_INVALID", "close is not declared from %s." % status)
    insp["inspection_status"] = "CLOSED"
    insp["closed_by_user_id"] = g.user_id
    touch("inspections", insp)
    op = need("operations", insp["operation_id"])
    permit = get("permits", insp["permit_id"])
    if permit is not None and permit["compliance_status"] == "CORRECTIVE_ACTION":
        others = [
            i
            for i in DB["inspections"].values()
            if i.get("operation_id") == op["id"]
            and i["id"] != insp["id"]
            and i["inspection_status"] in ("NOV_ISSUED", "RESPONSE_SUBMITTED")
        ]
        if not others:
            set_fields("permits", permit, {"compliance_status": "IN_GOOD_STANDING"})
    recompute_operation(op)
    return one(insp)


@app.get("/cafo/inspections/<rid>")
def get_inspection(rid):
    return read_one("inspections", rid, "Operator", "CertifiedPlanner", "StateReviewer", "ComplianceAdmin")


@app.get("/cafo/inspections")
def list_inspections():
    auth("Operator", "CertifiedPlanner", "StateReviewer", "ComplianceAdmin")
    return listing("inspections", ("operation_id", "permit_id", "inspection_status"))


# ==========================================================================
# AnnualReport
# ==========================================================================

REPORT_SPEC = {
    "operation_id": F("id"),
    "plan_id": F("id"),
    "report_year": F("int"),
    "beginning_storage_gallons": F("number", ge=0),
    "ending_storage_gallons": F("number", ge=0),
    "variance_explanation": F("string", required=False, default=None, nullable=True),
}


@app.post("/cafo/annual-reports")
def create_report():
    auth("Operator")
    body = raw_body()
    require_owner(body.get("operation_id") if isinstance(body.get("operation_id"), str) else None)
    op = fk("operations", body, "operation_id")
    plan = fk("plans", body, "plan_id")
    data = validate(body, REPORT_SPEC)
    if op is None:
        fail("ERR_OPERATION_NOT_FOUND", "operation_id is required.")
    if plan is None:
        fail("ERR_PLAN_NOT_FOUND", "plan_id is required.")
    for r in DB["reports"].values():
        if r.get("operation_id") == op["id"] and r.get("report_year") == data["report_year"]:
            fail(
                "ERR_REPORT_PERIOD_DUPLICATE",
                "An annual report already exists for %s." % data["report_year"],
            )
    fields = {
        "operation_id": op["id"],
        "plan_id": plan["id"],
        "report_year": data["report_year"],
        "beginning_storage_gallons": q2(data["beginning_storage_gallons"]),
        "ending_storage_gallons": q2(data["ending_storage_gallons"]),
        "variance_explanation": data["variance_explanation"],
    }
    fields.update(annual_report_mass_balance(fields, op))
    fields["submitted_at"] = None
    fields["accepted_at"] = None
    fields["return_reason"] = None
    fields["report_status"] = "DRAFT"
    rep = new_row("reports", fields)
    return one(rep, 201)


@app.post("/cafo/annual-reports/<rid>/submit")
def report_submit(rid):
    auth("Operator")
    rep = get("reports", rid)
    if rep is not None:
        require_owner(rep.get("operation_id"))
    rep = need("reports", rid)
    no_body(raw_body())
    if rep["report_status"] not in ("DRAFT", "RETURNED"):
        fail("ERR_REPORT_STATE_INVALID", "submit is not declared from %s." % rep["report_status"])
    op = need("operations", rep["operation_id"])
    rep.update(annual_report_mass_balance(rep, op))
    if rep["variance_classification"] == "EXCEEDS_TOLERANCE" and not (
        rep.get("variance_explanation") or ""
    ).strip():
        fail(
            "ERR_VARIANCE_EXPLANATION_REQUIRED",
            "A variance outside tolerance requires a variance_explanation.",
        )
    rep["report_status"] = "SUBMITTED"
    rep["submitted_at"] = fmt_dt(now())
    touch("reports", rep)
    return one(rep)


@app.post("/cafo/annual-reports/<rid>/accept")
def report_accept(rid):
    auth("StateReviewer")
    rep = need("reports", rid)
    no_body(raw_body())
    if rep["report_status"] != "SUBMITTED":
        fail("ERR_REPORT_STATE_INVALID", "accept is not declared from %s." % rep["report_status"])
    rep["report_status"] = "ACCEPTED"
    rep["accepted_at"] = fmt_dt(now())
    touch("reports", rep)
    return one(rep)


@app.post("/cafo/annual-reports/<rid>/return")
def report_return(rid):
    auth("StateReviewer")
    rep = need("reports", rid)
    data = validate(raw_body(), {"return_reason": F("string")})
    if rep["report_status"] != "SUBMITTED":
        fail("ERR_REPORT_STATE_INVALID", "return is not declared from %s." % rep["report_status"])
    rep["report_status"] = "RETURNED"
    rep["return_reason"] = data["return_reason"]
    touch("reports", rep)
    return one(rep)


@app.get("/cafo/annual-reports/<rid>")
def get_report(rid):
    return read_one("reports", rid, "Operator", "CertifiedPlanner", "StateReviewer", "ComplianceAdmin")


@app.get("/cafo/annual-reports")
def list_reports():
    auth("Operator", "CertifiedPlanner", "StateReviewer", "ComplianceAdmin")
    return listing("reports", ("operation_id", "plan_id", "report_status"), ("report_year",))


# ==========================================================================
# test-driving surface
# ==========================================================================


@app.post("/cafo/_clock/set_current_utc")
def clock_set():
    auth("ComplianceAdmin")
    data = validate(raw_body(), {"to_iso8601": F("datetime")})
    set_clock(data["to_iso8601"])

    permits_expired = 0
    for p in rows("permits"):
        if p["coverage_status"] in ("COVERED", "RENEWAL_PENDING") and p.get("expiration_on"):
            if now() >= parse_dt(p["expiration_on"]):
                set_fields("permits", p, {"coverage_status": "EXPIRED"})
                permits_expired += 1

    haulers_lapsed = 0
    for h in rows("haulers"):
        before = h["hauler_status"]
        refresh_hauler(h)
        if before != "LAPSED" and h["hauler_status"] == "LAPSED":
            haulers_lapsed += 1

    for st in rows("soil_tests"):
        refresh_soil_test(st)

    storages = rows("storages")
    ops = rows("operations")
    for op in ops:
        recompute_operation(op)

    data_out = {
        "current_utc": fmt_dt(now()),
        "permits_expired_count": permits_expired,
        "haulers_lapsed_count": haulers_lapsed,
        "storages_recomputed_count": len(storages),
        "operations_recomputed_count": len(ops),
    }
    return jsonify_pair(ok_object(data_out))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
