"""
Municipal Broadband & Digital-Equity Program API.

In-memory Flask implementation. All state is process-local and wiped on every
boot. Nothing is seeded at startup — tests build all preconditions via the API.
"""
import os
import re
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# ============================================================================
# Logical clock
# ============================================================================
CLOCK_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
CLOCK = CLOCK_DEFAULT


def now():
    return CLOCK


# ============================================================================
# In-memory store
# ============================================================================
DB = {
    "grant": {},
    "service_area": {},
    "service_plan": {},
    "subsidy_program": {},
    "subscriber": {},
    "subscription": {},
    "enrollment": {},
    "technician": {},
    "install_order": {},
    "device": {},
    "outage": {},
    "sla_credit": {},
    "invoice": {},
    "grant_claim": {},
}
_SEQ = 0


def next_seq():
    global _SEQ
    _SEQ += 1
    return _SEQ


# ============================================================================
# Constants
# ============================================================================
VALID_ROLES = {
    "ProgramAdmin", "ComplianceAnalyst", "ComplianceOfficer", "CustomerCare",
    "EligibilityWorker", "Dispatcher", "FieldTech", "NocOperator", "Billing",
}
ANY_ROLE = "__ANY__"

MINUTES_IN_BILLING_PERIOD = 43200
OUTAGE_MERGE_BUFFER_MINUTES = 60
FEDERAL_SHARE_PCT = Decimal("33.34")
CERT_PERIOD_DAYS = 365
FPL_BASE_CENTS = {1: 1506000, 2: 2034000, 3: 2562000, 4: 3090000, 5: 3618000}

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_VALIDATION": 400,
    "ERR_GRANT_NOT_FOUND": 404,
    "ERR_SERVICE_AREA_NOT_FOUND": 404,
    "ERR_SERVICE_PLAN_NOT_FOUND": 404,
    "ERR_SUBSIDY_PROGRAM_NOT_FOUND": 404,
    "ERR_SUBSCRIBER_NOT_FOUND": 404,
    "ERR_SUBSCRIPTION_NOT_FOUND": 404,
    "ERR_ENROLLMENT_NOT_FOUND": 404,
    "ERR_TECHNICIAN_NOT_FOUND": 404,
    "ERR_INSTALL_ORDER_NOT_FOUND": 404,
    "ERR_DEVICE_NOT_FOUND": 404,
    "ERR_OUTAGE_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_GRANT_CLAIM_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_AREA_NOT_SERVICEABLE": 409,
    "ERR_TECHNICIAN_INACTIVE": 409,
    "ERR_INSTALL_NOT_COMPLETED": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_TECHNICIAN_DOUBLE_BOOKED": 409,
    "ERR_OUTAGE_OVERLAP": 409,
    "ERR_PERIOD_INVALID": 422,
    "ERR_OUTAGE_NOT_ENDED": 422,
    "ERR_DEVICE_NOT_AVAILABLE": 409,
    "ERR_DUPLICATE_ACTIVE_ENROLLMENT": 409,
    "ERR_INVOICE_NOT_PAYABLE": 409,
    "ERR_INSUFFICIENT_GRANT_FUNDS": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or error_id


# ============================================================================
# Time helpers
# ============================================================================
def parse_dt(s):
    if not isinstance(s, str):
        raise ValueError("not a datetime string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def render_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


# ============================================================================
# Numeric helpers
# ============================================================================
def d_round2(dec):
    return float(dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def money_round(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ============================================================================
# Entity helpers
# ============================================================================
def new_id():
    return str(uuid.uuid4())


def base_fields(etype):
    ts = render_dt(CLOCK)
    return {
        "_type": etype,
        "_seq": next_seq(),
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def bump(ent):
    ent["version"] += 1
    ent["updated_at"] = render_dt(CLOCK)


# ============================================================================
# Response envelope
# ============================================================================
def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(pagination=None):
    m = {"api_request_id": _req_id(), "api_request_timestamp": render_dt(CLOCK)}
    if pagination is not None:
        m.update(pagination)
    return m


def ok(data, status=200, response_type="object", pagination=None):
    body = {"meta": _meta(pagination), "response_type": response_type, "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return ok(items, 200, "array", pagination)


@app.errorhandler(ApiError)
def _handle_api_error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.after_request
def _close_conn(resp):
    resp.headers["Connection"] = "close"
    return resp


# ============================================================================
# Auth
# ============================================================================
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    g.user_id = uid
    g.user_role = role
    return uid, role


def authorize(allowed):
    authenticate()
    if allowed != ANY_ROLE:
        allowed_set = allowed if isinstance(allowed, (set, list, tuple)) else {allowed}
        if g.user_role not in allowed_set:
            raise ApiError("ERR_UNAUTHORIZED", "Role not permitted for this operation")


# ============================================================================
# Body / validation helpers
# ============================================================================
def json_body():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def _check_type(name, val, typ):
    if typ == "int":
        if isinstance(val, bool) or not isinstance(val, int):
            raise ApiError("ERR_VALIDATION", "Field %s must be an integer" % name)
    elif typ == "number":
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise ApiError("ERR_VALIDATION", "Field %s must be a number" % name)
    elif typ == "str":
        if not isinstance(val, str):
            raise ApiError("ERR_VALIDATION", "Field %s must be a string" % name)
    elif typ == "bool":
        if not isinstance(val, bool):
            raise ApiError("ERR_VALIDATION", "Field %s must be a boolean" % name)
    elif typ == "array":
        if not isinstance(val, list):
            raise ApiError("ERR_VALIDATION", "Field %s must be an array" % name)
    elif typ == "datetime":
        if not isinstance(val, str):
            raise ApiError("ERR_VALIDATION", "Field %s must be a datetime string" % name)
        try:
            parse_dt(val)
        except Exception:
            raise ApiError("ERR_VALIDATION", "Field %s is not a valid datetime" % name)
    elif isinstance(typ, tuple) and typ[0] == "enum":
        if not isinstance(val, str) or val not in typ[1]:
            raise ApiError("ERR_VALIDATION", "Field %s has an invalid value" % name)


def validate(body, specs):
    """specs: list of (name, type, required)."""
    for name, typ, required in specs:
        if name not in body or body[name] is None:
            if required:
                raise ApiError("ERR_VALIDATION", "Missing required field: %s" % name)
            continue
        _check_type(name, body[name], typ)


def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args["limit"])
        except Exception:
            raise ApiError("ERR_VALIDATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", "limit out of range")
    if "offset" in args:
        try:
            offset = int(args["offset"])
        except Exception:
            raise ApiError("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset out of range")
    return limit, offset


def paginate(items):
    limit, offset = parse_pagination()
    items = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


# ============================================================================
# Existence helpers
# ============================================================================
NOT_FOUND = {
    "grant": "ERR_GRANT_NOT_FOUND",
    "service_area": "ERR_SERVICE_AREA_NOT_FOUND",
    "service_plan": "ERR_SERVICE_PLAN_NOT_FOUND",
    "subsidy_program": "ERR_SUBSIDY_PROGRAM_NOT_FOUND",
    "subscriber": "ERR_SUBSCRIBER_NOT_FOUND",
    "subscription": "ERR_SUBSCRIPTION_NOT_FOUND",
    "enrollment": "ERR_ENROLLMENT_NOT_FOUND",
    "technician": "ERR_TECHNICIAN_NOT_FOUND",
    "install_order": "ERR_INSTALL_ORDER_NOT_FOUND",
    "device": "ERR_DEVICE_NOT_FOUND",
    "outage": "ERR_OUTAGE_NOT_FOUND",
    "invoice": "ERR_INVOICE_NOT_FOUND",
    "grant_claim": "ERR_GRANT_CLAIM_NOT_FOUND",
}


def must_get(etype, ident):
    ent = DB[etype].get(ident)
    if ent is None:
        raise ApiError(NOT_FOUND[etype], "%s not found" % etype)
    return ent


# ============================================================================
# Serialization
# ============================================================================
def serialize(ent):
    out = {k: v for k, v in ent.items() if not k.startswith("_")}
    t = ent["_type"]
    if t == "grant":
        out["available_balance_cents"] = (
            ent["award_amount_cents"] - ent["committed_balance_cents"] - ent["disbursed_balance_cents"]
        )
    elif t == "service_area":
        out["reported_take_rate_pct"] = area_reported_take_rate(ent)
        out["verified_take_rate_pct"] = area_verified_take_rate(ent)
    return out


def serialize_list(items):
    return [serialize(e) for e in items]


# ============================================================================
# Domain computations
# ============================================================================
def area_reported_take_rate(area):
    hp = area["homes_passed"]
    if not hp:
        return 0.0
    n = sum(
        1 for s in DB["subscription"].values()
        if s["service_area_id"] == area["id"] and s["service_status"] in ("PENDING_INSTALL", "ACTIVE")
    )
    return d_round2(Decimal(n) / Decimal(hp) * 100)


def area_verified_take_rate(area):
    hp = area["homes_passed"]
    if not hp:
        return 0.0
    n = area_active_count(area["id"])
    return d_round2(Decimal(n) / Decimal(hp) * 100)


def area_active_count(area_id):
    return sum(
        1 for s in DB["subscription"].values()
        if s["service_area_id"] == area_id and s["service_status"] == "ACTIVE"
    )


def observe_enrollment(e):
    """Lazily flip an ACTIVE enrollment to RECERT_DUE once the clock reaches expiry."""
    if e["status"] == "ACTIVE" and e.get("certification_expires_at"):
        if CLOCK >= parse_dt(e["certification_expires_at"]):
            e["status"] = "RECERT_DUE"
            bump(e)
    return e


def get_active_enrollment(subscriber_id):
    for e in DB["enrollment"].values():
        if e["subscriber_id"] == subscriber_id:
            observe_enrollment(e)
            if e["status"] == "ACTIVE":
                return e
    return None


def subscription_outstanding(sub_id):
    """Any ISSUED invoice for the subscription with amount_paid below total_due."""
    for inv in DB["invoice"].values():
        if inv["subscription_id"] == sub_id and inv["status"] == "ISSUED" and inv["amount_paid_cents"] < inv["total_due_cents"]:
            return True
    return False


def maybe_clear_past_due(sub):
    if sub["billing_status"] == "PAST_DUE" and not subscription_outstanding(sub["id"]):
        sub["billing_status"] = "CURRENT"
        bump(sub)


def recompute_invoice(inv):
    base = inv["base_amount_cents"]
    subsidy = inv["subsidy_discount_cents"]
    net = base - subsidy
    if net < 0:
        net = 0
    applied = sum(
        c["credit_cents"] for c in DB["sla_credit"].values()
        if c.get("applied_invoice_id") == inv["id"] and c["status"] == "APPLIED"
    )
    credit = min(applied, net)
    inv["sla_credit_cents"] = credit
    inv["total_due_cents"] = base - subsidy - credit


# ============================================================================
# Cascade helpers
# ============================================================================
def unassign_cpe_for_subscription(sub_id):
    for dev in DB["device"].values():
        if dev.get("subscription_id") == sub_id and dev["device_class"] == "CPE_MODEM" and dev["status"] == "ASSIGNED":
            dev["status"] = "IN_STOCK"
            dev["subscription_id"] = None
            bump(dev)


def cancel_install_order(io):
    io["status"] = "CANCELLED"
    bump(io)
    unassign_cpe_for_subscription(io["subscription_id"])


def void_issued_invoices(sub_id):
    for inv in DB["invoice"].values():
        if inv["subscription_id"] == sub_id and inv["status"] == "ISSUED":
            inv["status"] = "VOID"
            bump(inv)
            for c in DB["sla_credit"].values():
                if c.get("applied_invoice_id") == inv["id"] and c["status"] == "APPLIED":
                    c["status"] = "REVERSED"
                    bump(c)


# ============================================================================
# Routes: clock
# ============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authorize(ANY_ROLE)
    body = json_body()
    validate(body, [("to_iso8601", "datetime", True)])
    global CLOCK
    CLOCK = parse_dt(body["to_iso8601"])
    return ok({}, 200, "object")


# ============================================================================
# Routes: Grant
# ============================================================================
@app.route("/grants", methods=["POST"])
def create_grant():
    authorize({"ProgramAdmin"})
    body = json_body()
    validate(body, [
        ("funding_source", ("enum", {"BEAD", "ARPA", "LOCAL"}), True),
        ("program_name", "str", True),
        ("award_amount_cents", "int", True),
        ("match_required_pct", "number", True),
        ("take_rate_milestone_pct", "number", True),
        ("take_rate_floor_pct", "number", False),
    ])
    g_ = base_fields("grant")
    g_.update({
        "funding_source": body["funding_source"],
        "program_name": body["program_name"],
        "award_amount_cents": body["award_amount_cents"],
        "match_required_pct": body["match_required_pct"],
        "take_rate_milestone_pct": body["take_rate_milestone_pct"],
        "take_rate_floor_pct": body.get("take_rate_floor_pct", 0),
        "committed_balance_cents": 0,
        "disbursed_balance_cents": 0,
        "status": "ACTIVE",
    })
    DB["grant"][g_["id"]] = g_
    return ok(serialize(g_), 201)


@app.route("/grants/<gid>", methods=["GET"])
def get_grant(gid):
    authorize(ANY_ROLE)
    return ok(serialize(must_get("grant", gid)))


@app.route("/grants/<gid>/claims", methods=["POST"])
def create_claim(gid):
    authorize({"ComplianceAnalyst"})
    body = json_body()
    validate(body, [
        ("claim_period_start", "datetime", True),
        ("claim_period_end", "datetime", True),
        ("service_area_ids", "array", True),
        ("expected_grant_version", "int", True),
    ])
    grant = must_get("grant", gid)
    # existence of body FK ids (left-to-right)
    for aid in body["service_area_ids"]:
        if not isinstance(aid, str) or aid not in DB["service_area"]:
            raise ApiError("ERR_SERVICE_AREA_NOT_FOUND", "service_area not found")
    # OCC
    if body["expected_grant_version"] != grant["version"]:
        raise ApiError("ERR_STALE_VERSION", "Grant version has advanced")
    # period
    if parse_dt(body["claim_period_end"]) <= parse_dt(body["claim_period_start"]):
        raise ApiError("ERR_PERIOD_INVALID", "claim_period_end must be after start")

    area_ids = list(body["service_area_ids"])
    amount, count = compute_claim_amount(area_ids)
    claim = base_fields("grant_claim")
    claim.update({
        "grant_id": gid,
        "claim_period_start": body["claim_period_start"],
        "claim_period_end": body["claim_period_end"],
        "service_area_ids": area_ids,
        "reported_take_rate_pct": None,
        "subsidized_subscriber_count": count,
        "amount_claimed_cents": amount,
        "submitted_by": None,
        "status": "DRAFT",
    })
    DB["grant_claim"][claim["id"]] = claim
    bump(grant)  # create serializes against the grant version
    return ok(serialize(claim), 201)


@app.route("/grants/<gid>/claims", methods=["GET"])
def list_claims(gid):
    authorize(ANY_ROLE)
    must_get("grant", gid)
    items = [c for c in DB["grant_claim"].values() if c["grant_id"] == gid]
    page, limit, offset, total = paginate(items)
    return ok_list(serialize_list(page), limit, offset, total)


def compute_claim_amount(area_ids):
    """Sum of per-subscriber federal share over ACTIVE subs with ACTIVE enrollment
    in the covered SERVICEABLE areas. Round each share, then sum."""
    covered = {
        aid for aid in area_ids
        if aid in DB["service_area"] and DB["service_area"][aid]["status"] == "SERVICEABLE"
    }
    amount = 0
    count = 0
    for sub in DB["subscription"].values():
        if sub["service_area_id"] in covered and sub["service_status"] == "ACTIVE":
            enr = get_active_enrollment(sub["subscriber_id"])
            if enr:
                prog = DB["subsidy_program"][enr["subsidy_program_id"]]
                per = money_round(Decimal(prog["monthly_discount_cents"]) * FEDERAL_SHARE_PCT / Decimal(100))
                amount += per
                count += 1
    return amount, count


def aggregate_verified_take_rate(area_ids):
    total_active = 0
    total_homes = 0
    for aid in area_ids:
        area = DB["service_area"].get(aid)
        if area is None:
            continue
        total_active += area_active_count(aid)
        total_homes += area["homes_passed"]
    if not total_homes:
        return 0.0
    return d_round2(Decimal(total_active) / Decimal(total_homes) * 100)


# ============================================================================
# Routes: ServiceArea
# ============================================================================
@app.route("/service-areas", methods=["POST"])
def create_service_area():
    authorize({"ProgramAdmin"})
    body = json_body()
    validate(body, [
        ("grant_id", "str", True),
        ("name", "str", True),
        ("census_block_group", "str", True),
        ("homes_passed", "int", True),
        ("fiber_ready", "bool", False),
    ])
    must_get("grant", body["grant_id"])
    a = base_fields("service_area")
    a.update({
        "grant_id": body["grant_id"],
        "name": body["name"],
        "census_block_group": body["census_block_group"],
        "homes_passed": body["homes_passed"],
        "fiber_ready": body.get("fiber_ready", False),
        "status": "PLANNED",
    })
    DB["service_area"][a["id"]] = a
    return ok(serialize(a), 201)


@app.route("/service-areas/<aid>", methods=["GET"])
def get_service_area(aid):
    authorize(ANY_ROLE)
    return ok(serialize(must_get("service_area", aid)))


@app.route("/service-areas", methods=["GET"])
def list_service_areas():
    authorize(ANY_ROLE)
    items = list(DB["service_area"].values())
    gid = request.args.get("grant_id")
    if gid is not None:
        items = [a for a in items if a["grant_id"] == gid]
    page, limit, offset, total = paginate(items)
    return ok_list(serialize_list(page), limit, offset, total)


@app.route("/service-areas/<aid>/advance", methods=["POST"])
def advance_service_area(aid):
    authorize({"ProgramAdmin"})
    a = must_get("service_area", aid)
    if a["status"] == "PLANNED":
        a["status"] = "CONSTRUCTION"
    elif a["status"] == "CONSTRUCTION":
        if not a["fiber_ready"]:
            raise ApiError("ERR_INVALID_STATE", "fiber_ready must be true to advance to SERVICEABLE")
        a["status"] = "SERVICEABLE"
    else:
        raise ApiError("ERR_INVALID_STATE", "Cannot advance from %s" % a["status"])
    bump(a)
    return ok(serialize(a))


@app.route("/service-areas/<aid>/suspend", methods=["POST"])
def suspend_service_area(aid):
    authorize({"ProgramAdmin"})
    a = must_get("service_area", aid)
    if a["status"] != "SERVICEABLE":
        raise ApiError("ERR_INVALID_STATE", "Only a SERVICEABLE area may be suspended")
    a["status"] = "SUSPENDED"
    bump(a)
    # Cascade L1: subscriptions PENDING_INSTALL|ACTIVE -> SUSPENDED
    for sub in DB["subscription"].values():
        if sub["service_area_id"] == aid and sub["service_status"] in ("PENDING_INSTALL", "ACTIVE"):
            sub["service_status"] = "SUSPENDED"
            bump(sub)
            # Cascade L2: SCHEDULED install orders -> CANCELLED
            for io in DB["install_order"].values():
                if io["subscription_id"] == sub["id"] and io["status"] == "SCHEDULED":
                    io["status"] = "CANCELLED"
                    bump(io)
                    # Cascade L3: ASSIGNED CPE_MODEM -> IN_STOCK
                    unassign_cpe_for_subscription(sub["id"])
    return ok(serialize(a))


@app.route("/service-areas/<aid>/reinstate", methods=["POST"])
def reinstate_service_area(aid):
    authorize({"ProgramAdmin"})
    a = must_get("service_area", aid)
    if a["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", "Only a SUSPENDED area may be reinstated")
    a["status"] = "SERVICEABLE"
    bump(a)
    return ok(serialize(a))


# ============================================================================
# Routes: ServicePlan
# ============================================================================
@app.route("/service-plans", methods=["POST"])
def create_service_plan():
    authorize({"ProgramAdmin"})
    body = json_body()
    validate(body, [
        ("tier", ("enum", {"BASIC", "STANDARD", "PREMIUM"}), True),
        ("name", "str", True),
        ("download_mbps", "int", True),
        ("upload_mbps", "int", True),
        ("monthly_price_cents", "int", True),
        ("sla_uptime_pct", "number", True),
    ])
    p = base_fields("service_plan")
    p.update({
        "tier": body["tier"],
        "name": body["name"],
        "download_mbps": body["download_mbps"],
        "upload_mbps": body["upload_mbps"],
        "monthly_price_cents": body["monthly_price_cents"],
        "sla_uptime_pct": body["sla_uptime_pct"],
    })
    DB["service_plan"][p["id"]] = p
    return ok(serialize(p), 201)


@app.route("/service-plans/<pid>", methods=["GET"])
def get_service_plan(pid):
    authorize(ANY_ROLE)
    return ok(serialize(must_get("service_plan", pid)))


# ============================================================================
# Routes: SubsidyProgram
# ============================================================================
@app.route("/subsidy-programs", methods=["POST"])
def create_subsidy_program():
    authorize({"ProgramAdmin"})
    body = json_body()
    validate(body, [
        ("name", "str", True),
        ("monthly_discount_cents", "int", True),
        ("device_benefit_cents", "int", True),
        ("eligibility_fpl_pct", "number", True),
    ])
    s = base_fields("subsidy_program")
    s.update({
        "name": body["name"],
        "monthly_discount_cents": body["monthly_discount_cents"],
        "device_benefit_cents": body["device_benefit_cents"],
        "eligibility_fpl_pct": body["eligibility_fpl_pct"],
    })
    DB["subsidy_program"][s["id"]] = s
    return ok(serialize(s), 201)


@app.route("/subsidy-programs/<sid>", methods=["GET"])
def get_subsidy_program(sid):
    authorize(ANY_ROLE)
    return ok(serialize(must_get("subsidy_program", sid)))


# ============================================================================
# Routes: Subscriber
# ============================================================================
@app.route("/subscribers", methods=["POST"])
def create_subscriber():
    authorize({"CustomerCare"})
    body = json_body()
    validate(body, [
        ("service_area_id", "str", True),
        ("full_name", "str", True),
        ("email", "str", True),
        ("service_address", "str", True),
        ("household_size", "int", True),
    ])
    must_get("service_area", body["service_area_id"])
    s = base_fields("subscriber")
    s.update({
        "service_area_id": body["service_area_id"],
        "full_name": body["full_name"],
        "email": body["email"],
        "service_address": body["service_address"],
        "household_size": body["household_size"],
        "status": "ACTIVE",
    })
    DB["subscriber"][s["id"]] = s
    return ok(serialize(s), 201)


@app.route("/subscribers/<sid>", methods=["GET"])
def get_subscriber(sid):
    authorize(ANY_ROLE)
    return ok(serialize(must_get("subscriber", sid)))


@app.route("/subscribers", methods=["GET"])
def list_subscribers():
    authorize(ANY_ROLE)
    items = list(DB["subscriber"].values())
    aid = request.args.get("service_area_id")
    if aid is not None:
        items = [s for s in items if s["service_area_id"] == aid]
    page, limit, offset, total = paginate(items)
    return ok_list(serialize_list(page), limit, offset, total)


# ============================================================================
# Routes: Subscription
# ============================================================================
@app.route("/subscriptions", methods=["POST"])
def create_subscription():
    authorize({"CustomerCare"})
    body = json_body()
    validate(body, [
        ("subscriber_id", "str", True),
        ("plan_id", "str", True),
        ("service_area_id", "str", True),
    ])
    subscriber = must_get("subscriber", body["subscriber_id"])
    plan = must_get("service_plan", body["plan_id"])
    area = must_get("service_area", body["service_area_id"])
    if area["status"] != "SERVICEABLE":
        raise ApiError("ERR_AREA_NOT_SERVICEABLE", "Service area is not SERVICEABLE")
    if subscriber["service_area_id"] != area["id"]:
        raise ApiError("ERR_VALIDATION", "service_area_id must match the subscriber's area")
    s = base_fields("subscription")
    s.update({
        "subscriber_id": body["subscriber_id"],
        "plan_id": body["plan_id"],
        "service_area_id": body["service_area_id"],
        "monthly_price_cents": plan["monthly_price_cents"],
        "service_status": "PENDING_INSTALL",
        "billing_status": "CURRENT",
    })
    DB["subscription"][s["id"]] = s
    return ok(serialize(s), 201)


@app.route("/subscriptions/<sid>", methods=["GET"])
def get_subscription(sid):
    authorize(ANY_ROLE)
    return ok(serialize(must_get("subscription", sid)))


@app.route("/subscriptions", methods=["GET"])
def list_subscriptions():
    authorize(ANY_ROLE)
    items = list(DB["subscription"].values())
    for key in ("subscriber_id", "plan_id", "service_area_id"):
        v = request.args.get(key)
        if v is not None:
            items = [s for s in items if s[key] == v]
    page, limit, offset, total = paginate(items)
    return ok_list(serialize_list(page), limit, offset, total)


@app.route("/subscriptions/<sid>/activate", methods=["POST"])
def activate_subscription(sid):
    authorize({"CustomerCare"})
    sub = must_get("subscription", sid)
    if sub["service_status"] != "PENDING_INSTALL":
        raise ApiError("ERR_INVALID_STATE", "Subscription is not PENDING_INSTALL")
    completed = any(
        io["subscription_id"] == sid and io["status"] == "COMPLETED"
        for io in DB["install_order"].values()
    )
    if not completed:
        raise ApiError("ERR_INSTALL_NOT_COMPLETED", "No COMPLETED install order for this subscription")
    area = DB["service_area"].get(sub["service_area_id"])
    if area is None or area["status"] != "SERVICEABLE":
        raise ApiError("ERR_INVALID_STATE", "Subscription area is not SERVICEABLE")
    sub["service_status"] = "ACTIVE"
    bump(sub)
    return ok(serialize(sub))


@app.route("/subscriptions/<sid>/suspend", methods=["POST"])
def suspend_subscription(sid):
    authorize({"CustomerCare"})
    sub = must_get("subscription", sid)
    if sub["service_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE subscription may be suspended")
    sub["service_status"] = "SUSPENDED"
    bump(sub)
    return ok(serialize(sub))


@app.route("/subscriptions/<sid>/cancel", methods=["POST"])
def cancel_subscription(sid):
    authorize({"CustomerCare"})
    sub = must_get("subscription", sid)
    prev = sub["service_status"]
    if prev not in ("PENDING_INSTALL", "ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", "Subscription cannot be cancelled from %s" % prev)
    sub["service_status"] = "CANCELLED"
    bump(sub)
    if prev == "PENDING_INSTALL":
        for io in DB["install_order"].values():
            if io["subscription_id"] == sid and io["status"] == "SCHEDULED":
                cancel_install_order(io)
        void_issued_invoices(sid)
    elif prev == "ACTIVE":
        void_issued_invoices(sid)
    return ok(serialize(sub))


@app.route("/subscriptions/<sid>/invoices", methods=["POST"])
def generate_invoice(sid):
    authorize({"Billing"})
    body = json_body()
    validate(body, [
        ("period_start", "datetime", True),
        ("period_end", "datetime", True),
    ])
    sub = must_get("subscription", sid)
    if parse_dt(body["period_end"]) <= parse_dt(body["period_start"]):
        raise ApiError("ERR_PERIOD_INVALID", "period_end must be after period_start")

    base = sub["monthly_price_cents"]
    enr = get_active_enrollment(sub["subscriber_id"])
    if enr:
        prog = DB["subsidy_program"][enr["subsidy_program_id"]]
        subsidy = min(prog["monthly_discount_cents"], base)
    else:
        subsidy = 0
    inv = base_fields("invoice")
    inv.update({
        "subscription_id": sid,
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "base_amount_cents": base,
        "subsidy_discount_cents": subsidy,
        "sla_credit_cents": 0,
        "total_due_cents": base - subsidy,
        "amount_paid_cents": 0,
        "status": "ISSUED",
    })
    DB["invoice"][inv["id"]] = inv

    # Billing axis: CURRENT -> PAST_DUE if a prior ISSUED invoice is overdue & unpaid.
    if sub["billing_status"] == "CURRENT":
        overdue = False
        for other in DB["invoice"].values():
            if other["id"] == inv["id"]:
                continue
            if other["subscription_id"] == sid and other["status"] == "ISSUED":
                if parse_dt(other["period_end"]) < CLOCK and other["amount_paid_cents"] < other["total_due_cents"]:
                    overdue = True
                    break
        if overdue:
            sub["billing_status"] = "PAST_DUE"
            bump(sub)
    return ok(serialize(inv), 201)


@app.route("/subscriptions/<sid>/invoices", methods=["GET"])
def list_invoices(sid):
    authorize(ANY_ROLE)
    must_get("subscription", sid)
    items = [i for i in DB["invoice"].values() if i["subscription_id"] == sid]
    page, limit, offset, total = paginate(items)
    return ok_list(serialize_list(page), limit, offset, total)


# ============================================================================
# Routes: Invoice
# ============================================================================
@app.route("/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    authorize(ANY_ROLE)
    return ok(serialize(must_get("invoice", iid)))


@app.route("/invoices/<iid>/payments", methods=["POST"])
def record_payment(iid):
    authorize({"Billing"})
    body = json_body()
    validate(body, [
        ("amount_cents", "int", True),
        ("expected_invoice_version", "int", True),
    ])
    inv = must_get("invoice", iid)
    if body["expected_invoice_version"] != inv["version"]:
        raise ApiError("ERR_STALE_VERSION", "Invoice version has advanced")
    if inv["status"] != "ISSUED":
        raise ApiError("ERR_INVOICE_NOT_PAYABLE", "Invoice is not payable")
    inv["amount_paid_cents"] += body["amount_cents"]
    bump(inv)
    if inv["amount_paid_cents"] >= inv["total_due_cents"]:
        inv["status"] = "PAID"
    sub = DB["subscription"].get(inv["subscription_id"])
    if sub:
        maybe_clear_past_due(sub)
    return ok(serialize(inv))


# ============================================================================
# Routes: Enrollment
# ============================================================================
@app.route("/enrollments", methods=["POST"])
def create_enrollment():
    authorize({"EligibilityWorker"})
    body = json_body()
    validate(body, [
        ("subscriber_id", "str", True),
        ("subsidy_program_id", "str", True),
        ("household_size", "int", True),
        ("annual_income_cents", "int", True),
    ])
    must_get("subscriber", body["subscriber_id"])
    must_get("subsidy_program", body["subsidy_program_id"])
    hs = body["household_size"]
    if hs not in FPL_BASE_CENTS:
        raise ApiError("ERR_VALIDATION", "household_size is out of supported range")
    fpl = d_round2(Decimal(body["annual_income_cents"]) / Decimal(FPL_BASE_CENTS[hs]) * 100)
    e = base_fields("enrollment")
    e.update({
        "subscriber_id": body["subscriber_id"],
        "subsidy_program_id": body["subsidy_program_id"],
        "household_size": hs,
        "annual_income_cents": body["annual_income_cents"],
        "fpl_pct": fpl,
        "certification_expires_at": None,
        "status": "SUBMITTED",
    })
    DB["enrollment"][e["id"]] = e
    return ok(serialize(e), 201)


@app.route("/enrollments/<eid>", methods=["GET"])
def get_enrollment(eid):
    authorize(ANY_ROLE)
    e = must_get("enrollment", eid)
    observe_enrollment(e)
    return ok(serialize(e))


@app.route("/enrollments", methods=["GET"])
def list_enrollments():
    authorize(ANY_ROLE)
    items = list(DB["enrollment"].values())
    for e in items:
        observe_enrollment(e)
    for key in ("subscriber_id", "subsidy_program_id"):
        v = request.args.get(key)
        if v is not None:
            items = [e for e in items if e[key] == v]
    page, limit, offset, total = paginate(items)
    return ok_list(serialize_list(page), limit, offset, total)


@app.route("/enrollments/<eid>/verify", methods=["POST"])
def verify_enrollment(eid):
    authorize({"EligibilityWorker"})
    e = must_get("enrollment", eid)
    if e["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Enrollment is not SUBMITTED")
    prog = DB["subsidy_program"][e["subsidy_program_id"]]
    eligible = e["fpl_pct"] <= prog["eligibility_fpl_pct"]
    if eligible:
        for other in DB["enrollment"].values():
            if other["id"] == eid:
                continue
            if other["subscriber_id"] == e["subscriber_id"]:
                observe_enrollment(other)
                if other["status"] == "ACTIVE":
                    raise ApiError("ERR_DUPLICATE_ACTIVE_ENROLLMENT", "Subscriber already has an ACTIVE enrollment")
        e["status"] = "ACTIVE"
        e["certification_expires_at"] = render_dt(CLOCK + timedelta(days=CERT_PERIOD_DAYS))
    else:
        e["status"] = "DENIED"
    bump(e)
    return ok(serialize(e))


@app.route("/enrollments/<eid>/recertify", methods=["POST"])
def recertify_enrollment(eid):
    authorize({"EligibilityWorker"})
    body = json_body()
    validate(body, [("annual_income_cents", "int", False)])
    e = must_get("enrollment", eid)
    observe_enrollment(e)
    if e["status"] != "RECERT_DUE":
        raise ApiError("ERR_INVALID_STATE", "Enrollment is not RECERT_DUE")
    if body.get("annual_income_cents") is not None:
        e["annual_income_cents"] = body["annual_income_cents"]
    hs = e["household_size"]
    e["fpl_pct"] = d_round2(Decimal(e["annual_income_cents"]) / Decimal(FPL_BASE_CENTS[hs]) * 100)
    prog = DB["subsidy_program"][e["subsidy_program_id"]]
    if e["fpl_pct"] <= prog["eligibility_fpl_pct"]:
        e["status"] = "ACTIVE"
        e["certification_expires_at"] = render_dt(CLOCK + timedelta(days=CERT_PERIOD_DAYS))
        bump(e)
    else:
        e["status"] = "TERMINATED"
        bump(e)
        terminate_enrollment_cascade(e)
    return ok(serialize(e))


@app.route("/enrollments/<eid>/terminate", methods=["POST"])
def terminate_enrollment(eid):
    authorize({"EligibilityWorker"})
    json_body()  # optional reason ignored
    e = must_get("enrollment", eid)
    observe_enrollment(e)
    if e["status"] not in ("ACTIVE", "RECERT_DUE"):
        raise ApiError("ERR_INVALID_STATE", "Enrollment cannot be terminated from %s" % e["status"])
    e["status"] = "TERMINATED"
    bump(e)
    terminate_enrollment_cascade(e)
    return ok(serialize(e))


def terminate_enrollment_cascade(e):
    for dev in DB["device"].values():
        if dev.get("enrollment_id") == e["id"] and dev["status"] == "DEPLOYED":
            dev["status"] = "RETURNED"
            bump(dev)


# ============================================================================
# Routes: Technician
# ============================================================================
@app.route("/technicians", methods=["POST"])
def create_technician():
    authorize({"ProgramAdmin"})
    body = json_body()
    validate(body, [
        ("name", "str", True),
        ("region", "str", True),
        ("job_duration_minutes", "int", False),
    ])
    t = base_fields("technician")
    t.update({
        "name": body["name"],
        "region": body["region"],
        "job_duration_minutes": body.get("job_duration_minutes", 120),
        "status": "AVAILABLE",
    })
    DB["technician"][t["id"]] = t
    return ok(serialize(t), 201)


@app.route("/technicians/<tid>", methods=["GET"])
def get_technician(tid):
    authorize(ANY_ROLE)
    return ok(serialize(must_get("technician", tid)))


@app.route("/technicians/<tid>/deactivate", methods=["POST"])
def deactivate_technician(tid):
    authorize({"ProgramAdmin"})
    t = must_get("technician", tid)
    if t["status"] != "AVAILABLE":
        raise ApiError("ERR_INVALID_STATE", "Technician is not AVAILABLE")
    t["status"] = "INACTIVE"
    bump(t)
    return ok(serialize(t))


# ============================================================================
# Routes: InstallOrder
# ============================================================================
def technician_overlap(tech_id, start, end, exclude_id=None):
    for io in DB["install_order"].values():
        if io["technician_id"] != tech_id or io["status"] != "SCHEDULED":
            continue
        if exclude_id is not None and io["id"] == exclude_id:
            continue
        io_start = parse_dt(io["scheduled_start_at"])
        io_end = parse_dt(io["scheduled_end_at"])
        if start < io_end and io_start < end:
            return True
    return False


@app.route("/install-orders", methods=["POST"])
def create_install_order():
    authorize({"Dispatcher"})
    body = json_body()
    validate(body, [
        ("subscription_id", "str", True),
        ("technician_id", "str", True),
        ("scheduled_start_at", "datetime", True),
    ])
    must_get("subscription", body["subscription_id"])
    tech = must_get("technician", body["technician_id"])
    if tech["status"] != "AVAILABLE":
        raise ApiError("ERR_TECHNICIAN_INACTIVE", "Technician is not AVAILABLE")
    start = parse_dt(body["scheduled_start_at"])
    end = start + timedelta(minutes=tech["job_duration_minutes"])
    if technician_overlap(tech["id"], start, end):
        raise ApiError("ERR_TECHNICIAN_DOUBLE_BOOKED", "Install window overlaps another scheduled install")
    io = base_fields("install_order")
    io.update({
        "subscription_id": body["subscription_id"],
        "technician_id": body["technician_id"],
        "scheduled_start_at": body["scheduled_start_at"],
        "scheduled_end_at": render_dt(end),
        "reschedule_count": 0,
        "status": "SCHEDULED",
    })
    DB["install_order"][io["id"]] = io
    return ok(serialize(io), 201)


@app.route("/install-orders/<iid>", methods=["GET"])
def get_install_order(iid):
    authorize(ANY_ROLE)
    return ok(serialize(must_get("install_order", iid)))


@app.route("/install-orders", methods=["GET"])
def list_install_orders():
    authorize(ANY_ROLE)
    items = list(DB["install_order"].values())
    for key in ("subscription_id", "technician_id"):
        v = request.args.get(key)
        if v is not None:
            items = [i for i in items if i[key] == v]
    page, limit, offset, total = paginate(items)
    return ok_list(serialize_list(page), limit, offset, total)


@app.route("/install-orders/<iid>/reschedule", methods=["POST"])
def reschedule_install_order(iid):
    authorize({"Dispatcher"})
    body = json_body()
    validate(body, [("scheduled_start_at", "datetime", True)])
    io = must_get("install_order", iid)
    if io["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED install may be rescheduled")
    tech = DB["technician"][io["technician_id"]]
    start = parse_dt(body["scheduled_start_at"])
    end = start + timedelta(minutes=tech["job_duration_minutes"])
    if technician_overlap(tech["id"], start, end, exclude_id=iid):
        raise ApiError("ERR_TECHNICIAN_DOUBLE_BOOKED", "Install window overlaps another scheduled install")
    io["scheduled_start_at"] = body["scheduled_start_at"]
    io["scheduled_end_at"] = render_dt(end)
    io["reschedule_count"] += 1
    bump(io)
    return ok(serialize(io))


@app.route("/install-orders/<iid>/complete", methods=["POST"])
def complete_install_order(iid):
    authorize({"FieldTech"})
    body = json_body()
    validate(body, [("device_id", "str", False)])
    io = must_get("install_order", iid)
    if g.user_id != io["technician_id"]:
        raise ApiError("ERR_UNAUTHORIZED", "FieldTech may only complete their own installs")
    device = None
    if body.get("device_id") is not None:
        device = must_get("device", body["device_id"])
    if io["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED install may be completed")
    sub = DB["subscription"].get(io["subscription_id"])
    if sub is None or sub["service_status"] != "PENDING_INSTALL":
        raise ApiError("ERR_INVALID_STATE", "Subscription is not PENDING_INSTALL")
    io["status"] = "COMPLETED"
    bump(io)
    if device is not None:
        device["status"] = "DEPLOYED"
        bump(device)
    return ok(serialize(io))


@app.route("/install-orders/<iid>/cancel", methods=["POST"])
def cancel_install_order_route(iid):
    authorize({"Dispatcher"})
    io = must_get("install_order", iid)
    if io["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED install may be cancelled")
    cancel_install_order(io)
    return ok(serialize(io))


# ============================================================================
# Routes: Device
# ============================================================================
@app.route("/devices", methods=["POST"])
def create_device():
    authorize({"Dispatcher"})
    body = json_body()
    validate(body, [
        ("device_class", ("enum", {"CPE_MODEM", "TABLET", "LAPTOP", "HOTSPOT"}), True),
        ("model", "str", True),
        ("serial_number", "str", True),
        ("value_cents", "int", True),
    ])
    d = base_fields("device")
    d.update({
        "device_class": body["device_class"],
        "model": body["model"],
        "serial_number": body["serial_number"],
        "value_cents": body["value_cents"],
        "subscription_id": None,
        "enrollment_id": None,
        "status": "IN_STOCK",
    })
    DB["device"][d["id"]] = d
    return ok(serialize(d), 201)


@app.route("/devices/<did>", methods=["GET"])
def get_device(did):
    authorize(ANY_ROLE)
    return ok(serialize(must_get("device", did)))


@app.route("/devices", methods=["GET"])
def list_devices():
    authorize(ANY_ROLE)
    items = list(DB["device"].values())
    for key in ("subscription_id", "enrollment_id", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [d for d in items if d.get(key) == v]
    page, limit, offset, total = paginate(items)
    return ok_list(serialize_list(page), limit, offset, total)


@app.route("/devices/<did>/assign", methods=["POST"])
def assign_device(did):
    authorize({"Dispatcher"})
    body = json_body()
    validate(body, [
        ("subscription_id", "str", False),
        ("enrollment_id", "str", False),
    ])
    dev = must_get("device", did)
    sub_id = body.get("subscription_id")
    enr_id = body.get("enrollment_id")
    if sub_id is not None:
        must_get("subscription", sub_id)
    if enr_id is not None:
        must_get("enrollment", enr_id)
    supplied = [x for x in (sub_id, enr_id) if x is not None]
    if len(supplied) != 1:
        raise ApiError("ERR_DEVICE_NOT_AVAILABLE", "Exactly one target id must be supplied")
    if dev["status"] != "IN_STOCK":
        raise ApiError("ERR_DEVICE_NOT_AVAILABLE", "Device is not IN_STOCK")
    if sub_id is not None:
        dev["subscription_id"] = sub_id
    else:
        dev["enrollment_id"] = enr_id
    dev["status"] = "ASSIGNED"
    bump(dev)
    return ok(serialize(dev))


@app.route("/devices/<did>/return", methods=["POST"])
def return_device(did):
    authorize({"Dispatcher"})
    dev = must_get("device", did)
    if dev["status"] == "ASSIGNED":
        dev["status"] = "IN_STOCK"
        dev["subscription_id"] = None
        dev["enrollment_id"] = None
        bump(dev)
    elif dev["status"] == "DEPLOYED":
        dev["status"] = "RETURNED"
        bump(dev)
    else:
        raise ApiError("ERR_INVALID_STATE", "Device cannot be returned from %s" % dev["status"])
    return ok(serialize(dev))


# ============================================================================
# Routes: OutageEvent
# ============================================================================
@app.route("/outages", methods=["POST"])
def report_outage():
    authorize({"NocOperator"})
    body = json_body()
    validate(body, [
        ("service_area_id", "str", True),
        ("started_at", "datetime", True),
        ("severity", ("enum", {"PARTIAL", "FULL"}), True),
    ])
    area = must_get("service_area", body["service_area_id"])
    started = parse_dt(body["started_at"])
    buffer = timedelta(minutes=OUTAGE_MERGE_BUFFER_MINUTES)
    for o in DB["outage"].values():
        if o["service_area_id"] == area["id"] and o["status"] == "OPEN":
            other_start = parse_dt(o["started_at"])
            if other_start - buffer <= started <= other_start + buffer:
                raise ApiError("ERR_OUTAGE_OVERLAP", "Outage overlaps an existing OPEN outage")

    active_subs = [
        s for s in DB["subscription"].values()
        if s["service_area_id"] == area["id"] and s["service_status"] == "ACTIVE"
    ]
    downtime = int((CLOCK - started).total_seconds() // 60)
    if downtime < 0:
        downtime = 0
    estimated = 0
    for s in active_subs:
        estimated += money_round(Decimal(s["monthly_price_cents"]) * Decimal(downtime) / Decimal(MINUTES_IN_BILLING_PERIOD))
    o = base_fields("outage")
    o.update({
        "service_area_id": body["service_area_id"],
        "started_at": body["started_at"],
        "ended_at": None,
        "severity": body["severity"],
        "estimated_credit_total_cents": estimated,
        "final_credit_total_cents": None,
        "affected_subscription_count": len(active_subs),
        "status": "OPEN",
    })
    DB["outage"][o["id"]] = o
    return ok(serialize(o), 201)


@app.route("/outages/<oid>", methods=["GET"])
def get_outage(oid):
    authorize(ANY_ROLE)
    return ok(serialize(must_get("outage", oid)))


@app.route("/outages", methods=["GET"])
def list_outages():
    authorize(ANY_ROLE)
    items = list(DB["outage"].values())
    v = request.args.get("service_area_id")
    if v is not None:
        items = [o for o in items if o["service_area_id"] == v]
    page, limit, offset, total = paginate(items)
    return ok_list(serialize_list(page), limit, offset, total)


@app.route("/outages/<oid>/resolve", methods=["POST"])
def resolve_outage(oid):
    authorize({"NocOperator"})
    body = json_body()
    validate(body, [("ended_at", "datetime", True)])
    o = must_get("outage", oid)
    if o["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Only an OPEN outage may be resolved")
    started = parse_dt(o["started_at"])
    ended = parse_dt(body["ended_at"])
    if ended <= started:
        raise ApiError("ERR_OUTAGE_NOT_ENDED", "ended_at must be after started_at")
    downtime = int((ended - started).total_seconds() // 60)

    active_subs = [
        s for s in DB["subscription"].values()
        if s["service_area_id"] == o["service_area_id"] and s["service_status"] == "ACTIVE"
    ]
    final_total = 0
    for sub in active_subs:
        credit_cents = money_round(Decimal(sub["monthly_price_cents"]) * Decimal(downtime) / Decimal(MINUTES_IN_BILLING_PERIOD))
        sc = base_fields("sla_credit")
        sc.update({
            "subscription_id": sub["id"],
            "outage_id": o["id"],
            "downtime_minutes": downtime,
            "credit_cents": credit_cents,
            "applied_invoice_id": None,
            "status": "PENDING",
        })
        DB["sla_credit"][sc["id"]] = sc
        final_total += credit_cents
        # Level 2: apply to latest ISSUED invoice
        issued = [
            i for i in DB["invoice"].values()
            if i["subscription_id"] == sub["id"] and i["status"] == "ISSUED"
        ]
        if issued:
            issued.sort(key=lambda i: (i["created_at"], i["_seq"]))
            target = issued[-1]
            sc["applied_invoice_id"] = target["id"]
            sc["status"] = "APPLIED"
            bump(sc)
            recompute_invoice(target)
            bump(target)
            # Level 3: settle invoice / clear billing
            if target["total_due_cents"] <= target["amount_paid_cents"]:
                target["status"] = "PAID"
            maybe_clear_past_due(sub)

    o["ended_at"] = body["ended_at"]
    o["final_credit_total_cents"] = final_total
    o["status"] = "RESOLVED"
    bump(o)
    return ok(serialize(o))


# ============================================================================
# Routes: SlaCredit
# ============================================================================
@app.route("/sla-credits/<cid>", methods=["GET"])
def get_sla_credit(cid):
    authorize(ANY_ROLE)
    return ok(serialize(must_get("sla_credit", cid)))


@app.route("/sla-credits", methods=["GET"])
def list_sla_credits():
    authorize(ANY_ROLE)
    items = list(DB["sla_credit"].values())
    for key in ("subscription_id", "outage_id"):
        v = request.args.get(key)
        if v is not None:
            items = [c for c in items if c[key] == v]
    page, limit, offset, total = paginate(items)
    return ok_list(serialize_list(page), limit, offset, total)


# ============================================================================
# Routes: GrantClaim actions
# ============================================================================
@app.route("/grant-claims/<cid>", methods=["GET"])
def get_grant_claim(cid):
    authorize(ANY_ROLE)
    return ok(serialize(must_get("grant_claim", cid)))


@app.route("/grant-claims/<cid>/submit", methods=["POST"])
def submit_grant_claim(cid):
    authorize({"ComplianceAnalyst"})
    claim = must_get("grant_claim", cid)
    if claim["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT claim may be submitted")
    for aid in claim["service_area_ids"]:
        area = DB["service_area"].get(aid)
        if area is None or area["status"] != "SERVICEABLE":
            raise ApiError("ERR_AREA_NOT_SERVICEABLE", "All covered areas must be SERVICEABLE")
    grant = DB["grant"][claim["grant_id"]]
    amount, count = compute_claim_amount(claim["service_area_ids"])
    available = grant["award_amount_cents"] - grant["committed_balance_cents"] - grant["disbursed_balance_cents"]
    if amount > available:
        raise ApiError("ERR_INSUFFICIENT_GRANT_FUNDS", "Claim exceeds available grant funds")
    claim["amount_claimed_cents"] = amount
    claim["subsidized_subscriber_count"] = count
    claim["reported_take_rate_pct"] = aggregate_verified_take_rate(claim["service_area_ids"])
    claim["submitted_by"] = g.user_id
    claim["status"] = "SUBMITTED"
    bump(claim)
    # Commit funds
    grant["committed_balance_cents"] += amount
    bump(grant)
    return ok(serialize(claim))


@app.route("/grant-claims/<cid>/approve", methods=["POST"])
def approve_grant_claim(cid):
    authorize({"ComplianceOfficer"})
    claim = must_get("grant_claim", cid)
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Only a SUBMITTED claim may be approved")
    if g.user_id == claim["submitted_by"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", "Approver must differ from submitter")
    grant = DB["grant"][claim["grant_id"]]
    amount = claim["amount_claimed_cents"]
    grant["committed_balance_cents"] -= amount
    grant["disbursed_balance_cents"] += amount
    claim["status"] = "APPROVED"
    bump(claim)
    # Milestone check
    aggregate = aggregate_verified_take_rate(claim["service_area_ids"])
    if grant["status"] == "ACTIVE" and aggregate >= grant["take_rate_milestone_pct"]:
        grant["status"] = "MILESTONE_MET"
    bump(grant)
    return ok(serialize(claim))


@app.route("/grant-claims/<cid>/reject", methods=["POST"])
def reject_grant_claim(cid):
    authorize({"ComplianceOfficer"})
    json_body()  # optional reason ignored
    claim = must_get("grant_claim", cid)
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Only a SUBMITTED claim may be rejected")
    if g.user_id == claim["submitted_by"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", "Rejecter must differ from submitter")
    grant = DB["grant"][claim["grant_id"]]
    grant["committed_balance_cents"] -= claim["amount_claimed_cents"]
    claim["status"] = "REJECTED"
    bump(claim)
    bump(grant)
    return ok(serialize(claim))


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
