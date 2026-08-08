import os
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, make_response

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
CLOCK = {"now": DEFAULT_CLOCK}


def now():
    return CLOCK["now"]


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
STORE = {
    "host_sites": {},
    "host_agreements": {},
    "grant_programs": {},
    "stations": {},
    "ports": {},
    "charging_sessions": {},
    "reservations": {},
    "maintenance_windows": {},
    "work_orders": {},
    "rebate_claims": {},
    "revenue_statements": {},
}
SEQ = {"n": 0}

NOT_FOUND = {
    "host_sites": "ERR_HOST_SITE_NOT_FOUND",
    "host_agreements": "ERR_HOST_AGREEMENT_NOT_FOUND",
    "grant_programs": "ERR_GRANT_PROGRAM_NOT_FOUND",
    "stations": "ERR_STATION_NOT_FOUND",
    "ports": "ERR_PORT_NOT_FOUND",
    "charging_sessions": "ERR_CHARGING_SESSION_NOT_FOUND",
    "reservations": "ERR_RESERVATION_NOT_FOUND",
    "maintenance_windows": "ERR_MAINTENANCE_WINDOW_NOT_FOUND",
    "work_orders": "ERR_WORK_ORDER_NOT_FOUND",
    "rebate_claims": "ERR_REBATE_CLAIM_NOT_FOUND",
    "revenue_statements": "ERR_REVENUE_STATEMENT_NOT_FOUND",
}

ROLES = {"ProgramAdmin", "HostOperator", "FieldTechnician", "Driver"}
MW_BUFFER_MIN = 60

# calculation constants
PEAK_RATE = 48
SHOULDER_RATE = 36
OFFPEAK_RATE = 24
DEMAND_KW_THRESHOLD = 150
DEMAND_SURCHARGE_CENTS = 5
ENERGY_COST_CAP_CENTS = 50000
SESSION_FEE_CENTS = 100
IDLE_GRACE_MIN = 10
IDLE_RATE_CENTS_PER_MIN = 40
IDLE_CAP_CENTS = 3000
SLA_HOURS = {"CRITICAL": 4, "MEDIUM": 24, "LOW": 72}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def parse_dt(value):
    if not isinstance(value, str):
        raise ApiError("ERR_VALIDATION", 400, "invalid datetime")
    s = value.strip()
    try:
        s2 = s
        if s2.endswith("Z") or s2.endswith("z"):
            s2 = s2[:-1] + "+00:00"
        dt = datetime.fromisoformat(s2)
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, "invalid datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def render_ts(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def round_half_up(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------
def new_record(rtype):
    SEQ["n"] += 1
    ts = now()
    return {
        "_type": rtype,
        "_seq": SEQ["n"],
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def touch(rec):
    rec["updated_at"] = now()
    rec["version"] += 1


def get_or_404(rtype, rid):
    rec = STORE[rtype].get(rid)
    if rec is None:
        raise ApiError(NOT_FOUND[rtype], 404, "%s not found" % rtype)
    return rec


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing or invalid auth headers")
    return uid, role


def require(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted")


# ---------------------------------------------------------------------------
# Body parsing / validation
# ---------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 400, "body must be an object")
    return data


def req_str(b, field):
    v = b.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", 400, "missing/invalid %s" % field)
    return v


def req_num(b, field):
    v = b.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", 400, "missing/invalid %s" % field)
    return v


def req_int(b, field):
    v = b.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 400, "missing/invalid %s" % field)
    return v


def opt_num(b, field, default):
    if field not in b or b[field] is None:
        return default
    v = b[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", 400, "invalid %s" % field)
    return v


def opt_int(b, field, default):
    if field not in b or b[field] is None:
        return default
    v = b[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 400, "invalid %s" % field)
    return v


def opt_bool(b, field, default):
    if field not in b or b[field] is None:
        return default
    v = b[field]
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 400, "invalid %s" % field)
    return v


def req_enum(b, field, choices):
    v = req_str(b, field)
    if v not in choices:
        raise ApiError("ERR_VALIDATION", 400, "invalid %s" % field)
    return v


def req_dt(b, field):
    v = b.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", 400, "missing/invalid %s" % field)
    parse_dt(v)  # validate parseable
    return v


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _meta():
    rid = "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return {"api_request_id": rid, "api_request_timestamp": render_ts(now())}


def success(data, response_type="object", status=200, pagination=None):
    meta = _meta()
    if pagination:
        meta.update(pagination)
    resp = make_response(jsonify({"meta": meta, "response_type": response_type, "data": data}), status)
    return resp


@app.errorhandler(ApiError)
def handle_api_error(err):
    meta = _meta()
    return make_response(
        jsonify({"meta": meta, "response_type": "error",
                 "data": {"error_id": err.error_id, "message": err.message}}),
        err.http_status,
    )


@app.errorhandler(404)
def handle_404(err):
    meta = _meta()
    return make_response(
        jsonify({"meta": meta, "response_type": "error",
                 "data": {"error_id": "ERR_NOT_FOUND", "message": "not found"}}), 404)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return handle_api_error(err)
    meta = _meta()
    return make_response(
        jsonify({"meta": meta, "response_type": "error",
                 "data": {"error_id": "ERR_INTERNAL", "message": str(err)}}), 500)


@app.after_request
def add_conn_close(resp):
    resp.headers["Connection"] = "close"
    return resp


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def paginate(items):
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {"limit": limit, "offset": offset, "total_count": total,
                  "has_more": offset + limit < total}
    return page, pagination


def sort_created(items):
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def count_ports(station_id):
    return [p for p in STORE["ports"].values() if p["station_id"] == station_id]


def serialize(rec):
    t = rec["_type"]
    base = {
        "id": rec["id"],
        "created_at": render_ts(rec["created_at"]),
        "updated_at": render_ts(rec["updated_at"]),
        "version": rec["version"],
    }
    if t == "host_sites":
        stations = [s for s in STORE["stations"].values() if s["site_id"] == rec["id"]]
        base.update({
            "name": rec["name"], "address": rec["address"], "state_code": rec["state_code"],
            "ada_required": rec["ada_required"], "revenue_share_pct": rec["revenue_share_pct"],
            "transaction_fee_pct": rec["transaction_fee_pct"],
            "transaction_fee_flat_cents": rec["transaction_fee_flat_cents"],
            "lifetime_gross_revenue_cents": rec["lifetime_gross_revenue_cents"],
            "station_count": len(stations),
        })
    elif t == "host_agreements":
        base.update({
            "site_id": rec["site_id"], "term_start_date": rec["term_start_date"],
            "term_end_date": rec["term_end_date"],
            "proposed_revenue_share_pct": rec["proposed_revenue_share_pct"],
            "counter_revenue_share_pct": rec["counter_revenue_share_pct"],
            "round_count": rec["round_count"], "status": rec["status"],
        })
    elif t == "grant_programs":
        base.update({
            "name": rec["name"], "program_code": rec["program_code"],
            "min_uptime_pct": rec["min_uptime_pct"], "min_ports": rec["min_ports"],
            "min_power_kw": rec["min_power_kw"],
            "reimbursement_rate_cents_per_kwh": rec["reimbursement_rate_cents_per_kwh"],
            "reimbursement_cap_cents": rec["reimbursement_cap_cents"],
        })
    elif t == "stations":
        ports = count_ports(rec["id"])
        avail = [p for p in ports if p["operational_status"] == "IN_SERVICE"
                 and p["occupancy_status"] == "AVAILABLE"]
        base.update({
            "site_id": rec["site_id"], "grant_id": rec["grant_id"], "name": rec["name"],
            "ada_accessible": rec["ada_accessible"], "total_ports": len(ports),
            "available_ports": len(avail), "operational_status": rec["operational_status"],
        })
    elif t == "ports":
        base.update({
            "station_id": rec["station_id"], "connector_type": rec["connector_type"],
            "power_kw": rec["power_kw"], "ada_accessible": rec["ada_accessible"],
            "operational_status": rec["operational_status"],
            "occupancy_status": rec["occupancy_status"],
            "oos_opened_at": render_ts(rec["oos_opened_at"]),
        })
    elif t == "charging_sessions":
        base.update({
            "port_id": rec["port_id"], "driver_id": rec["driver_id"],
            "started_at": render_ts(rec["started_at"]),
            "stopped_at": render_ts(rec["stopped_at"]),
            "unplugged_at": render_ts(rec["unplugged_at"]),
            "energy_kwh": rec["energy_kwh"], "tou_period": rec["tou_period"],
            "idle_minutes": rec["idle_minutes"], "energy_cost_cents": rec["energy_cost_cents"],
            "idle_fee_cents": rec["idle_fee_cents"], "session_fee_cents": rec["session_fee_cents"],
            "preliminary_cost_cents": rec["preliminary_cost_cents"],
            "final_cost_cents": rec["final_cost_cents"], "status": rec["status"],
        })
    elif t == "reservations":
        base.update({
            "port_id": rec["port_id"], "driver_id": rec["driver_id"],
            "window_start": rec["window_start"], "window_end": rec["window_end"],
            "status": rec["status"],
        })
    elif t == "maintenance_windows":
        base.update({
            "station_id": rec["station_id"], "window_start": rec["window_start"],
            "window_end": rec["window_end"], "reason": rec["reason"], "status": rec["status"],
        })
    elif t == "work_orders":
        base.update({
            "port_id": rec["port_id"], "severity": rec["severity"],
            "description": rec["description"], "opened_at": render_ts(rec["opened_at"]),
            "resolved_at": render_ts(rec["resolved_at"]),
            "sla_due_at": render_ts(rec["sla_due_at"]),
            "sla_breached": compute_sla_breached(rec), "status": rec["status"],
        })
    elif t == "rebate_claims":
        base.update({
            "station_id": rec["station_id"], "grant_id": rec["grant_id"],
            "period_start": rec["period_start"], "period_end": rec["period_end"],
            "reported_energy_kwh": rec["reported_energy_kwh"],
            "reported_uptime_pct": rec["reported_uptime_pct"],
            "measured_uptime_pct": rec["measured_uptime_pct"],
            "estimated_amount_cents": rec["estimated_amount_cents"],
            "audited_amount_cents": rec["audited_amount_cents"],
            "compliance_status": rec["compliance_status"],
            "submitted_by_user_id": rec["submitted_by_user_id"], "status": rec["status"],
        })
    elif t == "revenue_statements":
        base.update({
            "site_id": rec["site_id"], "period_start": rec["period_start"],
            "period_end": rec["period_end"], "basis": rec["basis"],
            "gross_revenue_cents": rec["gross_revenue_cents"],
            "transaction_fees_cents": rec["transaction_fees_cents"],
            "host_share_cents": rec["host_share_cents"],
            "program_share_cents": rec["program_share_cents"],
            "session_count": rec["session_count"], "status": rec["status"],
        })
    return base


def compute_sla_breached(wo):
    ref = wo["resolved_at"] if wo["status"] == "RESOLVED" else now()
    return ref > wo["sla_due_at"]


# ---------------------------------------------------------------------------
# Shared cascade / occupancy helpers
# ---------------------------------------------------------------------------
def active_session_on_port(port_id):
    for s in STORE["charging_sessions"].values():
        if s["port_id"] == port_id and s["status"] == "ACTIVE":
            return s
    return None


def drive_port_out_of_service(port):
    """Take a port OUT_OF_SERVICE: stamp oos, abort active session, free occupancy."""
    if port["operational_status"] != "IN_SERVICE":
        return
    port["operational_status"] = "OUT_OF_SERVICE"
    port["oos_opened_at"] = now()
    sess = active_session_on_port(port["id"])
    if sess is not None:
        sess["status"] = "ABORTED"
        sess["final_cost_cents"] = 0
        touch(sess)
        port["occupancy_status"] = "AVAILABLE"
    touch(port)


# ===========================================================================
# HostSite
# ===========================================================================
@app.route("/host-sites", methods=["POST"])
def create_host_site():
    _, role = auth()
    require(role, {"ProgramAdmin"})
    b = body()
    rec = new_record("host_sites")
    rec["name"] = req_str(b, "name")
    rec["address"] = req_str(b, "address")
    rec["state_code"] = req_str(b, "state_code")
    rec["ada_required"] = opt_bool(b, "ada_required", False)
    rec["revenue_share_pct"] = req_num(b, "revenue_share_pct")
    rec["transaction_fee_pct"] = opt_num(b, "transaction_fee_pct", 0.029)
    rec["transaction_fee_flat_cents"] = opt_int(b, "transaction_fee_flat_cents", 30)
    rec["lifetime_gross_revenue_cents"] = 0
    STORE["host_sites"][rec["id"]] = rec
    return success(serialize(rec), status=201)


@app.route("/host-sites/<rid>", methods=["GET"])
def get_host_site(rid):
    uid, role = auth()
    require(role, {"ProgramAdmin", "HostOperator"})
    rec = get_or_404("host_sites", rid)
    if role == "HostOperator" and uid != rec["id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not owner")
    return success(serialize(rec))


# ===========================================================================
# HostAgreement
# ===========================================================================
@app.route("/host-agreements", methods=["POST"])
def create_host_agreement():
    _, role = auth()
    require(role, {"ProgramAdmin"})
    b = body()
    site_id = req_str(b, "site_id")
    term_start = req_dt(b, "term_start_date")
    term_end = req_dt(b, "term_end_date")
    proposed = req_num(b, "proposed_revenue_share_pct")
    get_or_404("host_sites", site_id)
    rec = new_record("host_agreements")
    rec.update({
        "site_id": site_id, "term_start_date": term_start, "term_end_date": term_end,
        "proposed_revenue_share_pct": proposed, "counter_revenue_share_pct": None,
        "round_count": 0, "status": "DRAFT",
    })
    STORE["host_agreements"][rec["id"]] = rec
    return success(serialize(rec), status=201)


@app.route("/host-agreements/<rid>", methods=["GET"])
def get_host_agreement(rid):
    uid, role = auth()
    require(role, {"ProgramAdmin", "HostOperator"})
    rec = get_or_404("host_agreements", rid)
    if role == "HostOperator" and uid != rec["site_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not owner")
    return success(serialize(rec))


@app.route("/host-agreements", methods=["GET"])
def list_host_agreements():
    uid, role = auth()
    require(role, {"ProgramAdmin", "HostOperator"})
    items = list(STORE["host_agreements"].values())
    site_id = request.args.get("site_id")
    status = request.args.get("status")
    if site_id:
        items = [r for r in items if r["site_id"] == site_id]
    if status:
        items = [r for r in items if r["status"] == status]
    if role == "HostOperator":
        items = [r for r in items if r["site_id"] == uid]
    items = sort_created(items)
    page, pg = paginate(items)
    return success([serialize(r) for r in page], "array", pagination=pg)


@app.route("/host-agreements/<rid>/propose", methods=["POST"])
def propose_agreement(rid):
    _, role = auth()
    require(role, {"ProgramAdmin"})
    rec = get_or_404("host_agreements", rid)
    if rec["status"] not in ("DRAFT", "COUNTERED"):
        raise ApiError("ERR_INVALID_STATE", 409, "cannot propose")
    b = body()
    if "proposed_revenue_share_pct" in b and b["proposed_revenue_share_pct"] is not None:
        rec["proposed_revenue_share_pct"] = req_num(b, "proposed_revenue_share_pct")
    rec["status"] = "PROPOSED"
    touch(rec)
    return success(serialize(rec))


@app.route("/host-agreements/<rid>/counter", methods=["POST"])
def counter_agreement(rid):
    uid, role = auth()
    require(role, {"HostOperator"})
    rec = get_or_404("host_agreements", rid)
    if uid != rec["site_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not owner")
    if rec["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "cannot counter")
    b = body()
    rec["counter_revenue_share_pct"] = req_num(b, "counter_revenue_share_pct")
    rec["round_count"] += 1
    rec["status"] = "COUNTERED"
    touch(rec)
    return success(serialize(rec))


@app.route("/host-agreements/<rid>/activate", methods=["POST"])
def activate_agreement(rid):
    _, role = auth()
    require(role, {"ProgramAdmin"})
    rec = get_or_404("host_agreements", rid)
    if rec["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "cannot activate")
    for other in STORE["host_agreements"].values():
        if other["id"] != rec["id"] and other["site_id"] == rec["site_id"] \
                and other["status"] == "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409, "active agreement exists")
    rec["status"] = "ACTIVE"
    touch(rec)
    return success(serialize(rec))


@app.route("/host-agreements/<rid>/terminate", methods=["POST"])
def terminate_agreement(rid):
    _, role = auth()
    require(role, {"ProgramAdmin"})
    rec = get_or_404("host_agreements", rid)
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "cannot terminate")
    rec["status"] = "TERMINATED"
    touch(rec)
    # cascade
    for st in STORE["stations"].values():
        if st["site_id"] == rec["site_id"] and st["operational_status"] in \
                ("PENDING", "COMMISSIONED", "SUSPENDED"):
            st["operational_status"] = "DECOMMISSIONED"
            touch(st)
            for p in count_ports(st["id"]):
                drive_port_out_of_service(p)
    return success(serialize(rec))


# ===========================================================================
# GrantProgram
# ===========================================================================
@app.route("/grant-programs", methods=["POST"])
def create_grant_program():
    _, role = auth()
    require(role, {"ProgramAdmin"})
    b = body()
    rec = new_record("grant_programs")
    rec.update({
        "name": req_str(b, "name"),
        "program_code": req_str(b, "program_code"),
        "min_uptime_pct": req_num(b, "min_uptime_pct"),
        "min_ports": req_int(b, "min_ports"),
        "min_power_kw": req_num(b, "min_power_kw"),
        "reimbursement_rate_cents_per_kwh": req_int(b, "reimbursement_rate_cents_per_kwh"),
        "reimbursement_cap_cents": req_int(b, "reimbursement_cap_cents"),
    })
    STORE["grant_programs"][rec["id"]] = rec
    return success(serialize(rec), status=201)


@app.route("/grant-programs/<rid>", methods=["GET"])
def get_grant_program(rid):
    _, role = auth()
    require(role, {"ProgramAdmin", "HostOperator"})
    rec = get_or_404("grant_programs", rid)
    return success(serialize(rec))


# ===========================================================================
# Station
# ===========================================================================
@app.route("/stations", methods=["POST"])
def create_station():
    _, role = auth()
    require(role, {"ProgramAdmin"})
    b = body()
    site_id = req_str(b, "site_id")
    name = req_str(b, "name")
    grant_id = b.get("grant_id")
    if grant_id is not None and not isinstance(grant_id, str):
        raise ApiError("ERR_VALIDATION", 400, "invalid grant_id")
    ada = opt_bool(b, "ada_accessible", False)
    get_or_404("host_sites", site_id)
    if grant_id:
        get_or_404("grant_programs", grant_id)
    rec = new_record("stations")
    rec.update({
        "site_id": site_id, "grant_id": grant_id if grant_id else None, "name": name,
        "ada_accessible": ada, "operational_status": "PENDING",
    })
    STORE["stations"][rec["id"]] = rec
    return success(serialize(rec), status=201)


@app.route("/stations/<rid>", methods=["GET"])
def get_station(rid):
    uid, role = auth()
    require(role, {"ProgramAdmin", "HostOperator", "FieldTechnician"})
    rec = get_or_404("stations", rid)
    if role == "HostOperator" and uid != rec["site_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not owner")
    return success(serialize(rec))


@app.route("/stations", methods=["GET"])
def list_stations():
    uid, role = auth()
    require(role, {"ProgramAdmin", "HostOperator"})
    items = list(STORE["stations"].values())
    site_id = request.args.get("site_id")
    grant_id = request.args.get("grant_id")
    status = request.args.get("status")
    if site_id:
        items = [r for r in items if r["site_id"] == site_id]
    if grant_id:
        items = [r for r in items if r["grant_id"] == grant_id]
    if status:
        items = [r for r in items if r["operational_status"] == status]
    if role == "HostOperator":
        items = [r for r in items if r["site_id"] == uid]
    items = sort_created(items)
    page, pg = paginate(items)
    return success([serialize(r) for r in page], "array", pagination=pg)


@app.route("/stations/<rid>/ports", methods=["GET"])
def list_station_ports(rid):
    uid, role = auth()
    require(role, {"ProgramAdmin", "HostOperator", "FieldTechnician"})
    st = get_or_404("stations", rid)
    if role == "HostOperator" and uid != st["site_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not owner")
    items = sort_created(count_ports(rid))
    page, pg = paginate(items)
    return success([serialize(r) for r in page], "array", pagination=pg)


@app.route("/stations/<rid>/commission", methods=["POST"])
def commission_station(rid):
    _, role = auth()
    require(role, {"ProgramAdmin"})
    st = get_or_404("stations", rid)
    if st["operational_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "cannot commission")
    # active agreement for site
    has_active = any(a["site_id"] == st["site_id"] and a["status"] == "ACTIVE"
                     for a in STORE["host_agreements"].values())
    if not has_active:
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE", 409, "no active agreement")
    site = STORE["host_sites"].get(st["site_id"])
    ports = count_ports(st["id"])
    if (site and site["ada_required"]) or st["grant_id"]:
        if not any(p["ada_accessible"] for p in ports):
            raise ApiError("ERR_ADA_PORT_REQUIRED", 409, "ada port required")
    if st["grant_id"]:
        grant = STORE["grant_programs"].get(st["grant_id"])
        if grant and len(ports) < grant["min_ports"]:
            raise ApiError("ERR_INSUFFICIENT_PORTS", 422, "insufficient ports")
    st["operational_status"] = "COMMISSIONED"
    touch(st)
    return success(serialize(st))


@app.route("/stations/<rid>/decommission", methods=["POST"])
def decommission_station(rid):
    _, role = auth()
    require(role, {"ProgramAdmin"})
    st = get_or_404("stations", rid)
    if st["operational_status"] not in ("PENDING", "COMMISSIONED", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", 409, "cannot decommission")
    prev = st["operational_status"]
    st["operational_status"] = "DECOMMISSIONED"
    touch(st)
    if prev in ("COMMISSIONED", "SUSPENDED"):
        for p in count_ports(st["id"]):
            drive_port_out_of_service(p)
    return success(serialize(st))


# ===========================================================================
# Port
# ===========================================================================
@app.route("/ports", methods=["POST"])
def create_port():
    _, role = auth()
    require(role, {"ProgramAdmin"})
    b = body()
    station_id = req_str(b, "station_id")
    connector = req_enum(b, "connector_type", {"CCS1", "CCS2", "NACS", "CHADEMO"})
    power_kw = req_num(b, "power_kw")
    ada = opt_bool(b, "ada_accessible", False)
    get_or_404("stations", station_id)
    rec = new_record("ports")
    rec.update({
        "station_id": station_id, "connector_type": connector, "power_kw": power_kw,
        "ada_accessible": ada, "operational_status": "IN_SERVICE",
        "occupancy_status": "AVAILABLE", "oos_opened_at": None,
    })
    STORE["ports"][rec["id"]] = rec
    return success(serialize(rec), status=201)


@app.route("/ports/<rid>", methods=["GET"])
def get_port(rid):
    _, role = auth()
    require(role, {"ProgramAdmin", "HostOperator", "FieldTechnician", "Driver"})
    rec = get_or_404("ports", rid)
    return success(serialize(rec))


@app.route("/ports/<rid>/out-of-service", methods=["POST"])
def port_oos(rid):
    _, role = auth()
    require(role, {"FieldTechnician"})
    port = get_or_404("ports", rid)
    if port["operational_status"] != "IN_SERVICE":
        raise ApiError("ERR_INVALID_STATE", 409, "not in service")
    drive_port_out_of_service(port)
    return success(serialize(port))


@app.route("/ports/<rid>/in-service", methods=["POST"])
def port_in_service(rid):
    _, role = auth()
    require(role, {"FieldTechnician"})
    port = get_or_404("ports", rid)
    if port["operational_status"] != "OUT_OF_SERVICE":
        raise ApiError("ERR_INVALID_STATE", 409, "not out of service")
    for wo in STORE["work_orders"].values():
        if wo["port_id"] == port["id"] and wo["severity"] == "CRITICAL" \
                and wo["status"] == "OPEN":
            raise ApiError("ERR_INVALID_STATE", 409, "open critical work order")
    port["operational_status"] = "IN_SERVICE"
    port["oos_opened_at"] = None
    touch(port)
    return success(serialize(port))


# ===========================================================================
# ChargingSession
# ===========================================================================
def tou_period_for(started_at):
    h = started_at.astimezone(timezone.utc).hour
    if 16 <= h < 21:
        return "PEAK"
    if 0 <= h < 7:
        return "OFFPEAK"
    return "SHOULDER"


@app.route("/charging-sessions", methods=["POST"])
def create_session():
    uid, role = auth()
    require(role, {"Driver"})
    b = body()
    port_id = req_str(b, "port_id")
    driver_id = req_str(b, "driver_id")
    port = get_or_404("ports", port_id)
    if port["operational_status"] != "IN_SERVICE":
        raise ApiError("ERR_PORT_OUT_OF_SERVICE", 409, "port out of service")
    if port["occupancy_status"] != "AVAILABLE":
        raise ApiError("ERR_PORT_NOT_AVAILABLE", 409, "port not available")
    rec = new_record("charging_sessions")
    rec.update({
        "port_id": port_id, "driver_id": driver_id, "started_at": now(),
        "stopped_at": None, "unplugged_at": None, "energy_kwh": None, "tou_period": None,
        "idle_minutes": 0, "energy_cost_cents": 0, "idle_fee_cents": 0,
        "session_fee_cents": 0, "preliminary_cost_cents": 0, "final_cost_cents": 0,
        "status": "ACTIVE",
    })
    STORE["charging_sessions"][rec["id"]] = rec
    port["occupancy_status"] = "OCCUPIED"
    touch(port)
    return success(serialize(rec), status=201)


@app.route("/charging-sessions/<rid>", methods=["GET"])
def get_session(rid):
    _, role = auth()
    require(role, {"ProgramAdmin", "Driver"})
    rec = get_or_404("charging_sessions", rid)
    return success(serialize(rec))


@app.route("/charging-sessions", methods=["GET"])
def list_sessions():
    _, role = auth()
    require(role, {"ProgramAdmin", "Driver"})
    items = list(STORE["charging_sessions"].values())
    port_id = request.args.get("port_id")
    driver_id = request.args.get("driver_id")
    status = request.args.get("status")
    if port_id:
        items = [r for r in items if r["port_id"] == port_id]
    if driver_id:
        items = [r for r in items if r["driver_id"] == driver_id]
    if status:
        items = [r for r in items if r["status"] == status]
    items = sort_created(items)
    page, pg = paginate(items)
    return success([serialize(r) for r in page], "array", pagination=pg)


@app.route("/charging-sessions/<rid>/stop", methods=["POST"])
def stop_session(rid):
    uid, role = auth()
    require(role, {"Driver"})
    sess = get_or_404("charging_sessions", rid)
    if uid != sess["driver_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not owner")
    if sess["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "not active")
    b = body()
    energy = req_num(b, "energy_kwh")
    if energy <= 0:
        raise ApiError("ERR_ENERGY_INVALID", 422, "energy must be > 0")
    sess["stopped_at"] = now()
    sess["energy_kwh"] = energy
    port = STORE["ports"].get(sess["port_id"])
    tou = tou_period_for(sess["started_at"])
    sess["tou_period"] = tou
    base_rate = {"PEAK": PEAK_RATE, "SHOULDER": SHOULDER_RATE, "OFFPEAK": OFFPEAK_RATE}[tou]
    surcharge = DEMAND_SURCHARGE_CENTS if (port and port["power_kw"] >= DEMAND_KW_THRESHOLD) else 0
    raw = Decimal(str(energy)) * (base_rate + surcharge)
    energy_cost = min(round_half_up(raw), ENERGY_COST_CAP_CENTS)
    sess["energy_cost_cents"] = energy_cost
    sess["session_fee_cents"] = SESSION_FEE_CENTS
    sess["preliminary_cost_cents"] = energy_cost + SESSION_FEE_CENTS
    sess["status"] = "STOPPED"
    touch(sess)
    return success(serialize(sess))


@app.route("/charging-sessions/<rid>/finalize", methods=["POST"])
def finalize_session(rid):
    _, role = auth()
    require(role, {"ProgramAdmin"})
    sess = get_or_404("charging_sessions", rid)
    if sess["status"] != "STOPPED":
        raise ApiError("ERR_INVALID_STATE", 409, "not stopped")
    sess["unplugged_at"] = now()
    elapsed = (sess["unplugged_at"] - sess["stopped_at"]).total_seconds()
    idle_minutes = int(elapsed // 60)
    if idle_minutes < 0:
        idle_minutes = 0
    sess["idle_minutes"] = idle_minutes
    if idle_minutes > IDLE_GRACE_MIN:
        idle_fee = min((idle_minutes - IDLE_GRACE_MIN) * IDLE_RATE_CENTS_PER_MIN, IDLE_CAP_CENTS)
    else:
        idle_fee = 0
    sess["idle_fee_cents"] = idle_fee
    sess["final_cost_cents"] = sess["energy_cost_cents"] + sess["session_fee_cents"] + idle_fee
    sess["status"] = "FINALIZED"
    touch(sess)
    port = STORE["ports"].get(sess["port_id"])
    if port:
        port["occupancy_status"] = "AVAILABLE"
        touch(port)
        st = STORE["stations"].get(port["station_id"])
        if st:
            site = STORE["host_sites"].get(st["site_id"])
            if site:
                site["lifetime_gross_revenue_cents"] += sess["final_cost_cents"]
    return success(serialize(sess))


@app.route("/charging-sessions/<rid>/void", methods=["POST"])
def void_session(rid):
    _, role = auth()
    require(role, {"ProgramAdmin"})
    sess = get_or_404("charging_sessions", rid)
    if sess["status"] != "FINALIZED":
        raise ApiError("ERR_INVALID_STATE", 409, "not finalized")
    sess["status"] = "VOIDED"
    touch(sess)
    port = STORE["ports"].get(sess["port_id"])
    if port:
        st = STORE["stations"].get(port["station_id"])
        if st:
            site = STORE["host_sites"].get(st["site_id"])
            if site:
                site["lifetime_gross_revenue_cents"] -= sess["final_cost_cents"]
    return success(serialize(sess))


# ===========================================================================
# Reservation
# ===========================================================================
@app.route("/reservations", methods=["POST"])
def create_reservation():
    uid, role = auth()
    require(role, {"Driver"})
    b = body()
    port_id = req_str(b, "port_id")
    driver_id = req_str(b, "driver_id")
    ws = req_dt(b, "window_start")
    we = req_dt(b, "window_end")
    port = get_or_404("ports", port_id)
    if parse_dt(we) <= parse_dt(ws):
        raise ApiError("ERR_INVALID_WINDOW", 409, "window_end <= window_start")
    rec = new_record("reservations")
    rec.update({
        "port_id": port_id, "driver_id": driver_id, "window_start": ws,
        "window_end": we, "status": "PENDING",
    })
    STORE["reservations"][rec["id"]] = rec
    return success(serialize(rec), status=201)


@app.route("/reservations/<rid>", methods=["GET"])
def get_reservation(rid):
    _, role = auth()
    require(role, {"ProgramAdmin", "Driver"})
    rec = get_or_404("reservations", rid)
    return success(serialize(rec))


@app.route("/reservations", methods=["GET"])
def list_reservations():
    _, role = auth()
    require(role, {"ProgramAdmin", "Driver"})
    items = list(STORE["reservations"].values())
    port_id = request.args.get("port_id")
    driver_id = request.args.get("driver_id")
    status = request.args.get("status")
    if port_id:
        items = [r for r in items if r["port_id"] == port_id]
    if driver_id:
        items = [r for r in items if r["driver_id"] == driver_id]
    if status:
        items = [r for r in items if r["status"] == status]
    items = sort_created(items)
    page, pg = paginate(items)
    return success([serialize(r) for r in page], "array", pagination=pg)


@app.route("/reservations/<rid>/confirm", methods=["POST"])
def confirm_reservation(rid):
    uid, role = auth()
    require(role, {"Driver"})
    rec = get_or_404("reservations", rid)
    if uid != rec["driver_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not owner")
    if rec["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "not pending")
    port = STORE["ports"].get(rec["port_id"])
    # temporal overlap (priority 9) before port availability (priority 10)
    ws, we = parse_dt(rec["window_start"]), parse_dt(rec["window_end"])
    for other in STORE["reservations"].values():
        if other["id"] != rec["id"] and other["port_id"] == rec["port_id"] \
                and other["status"] == "CONFIRMED":
            ows, owe = parse_dt(other["window_start"]), parse_dt(other["window_end"])
            if ws < owe and ows < we:
                raise ApiError("ERR_RESERVATION_OVERLAP", 409, "reservation overlap")
    if port["operational_status"] != "IN_SERVICE":
        raise ApiError("ERR_PORT_OUT_OF_SERVICE", 409, "port out of service")
    if port["occupancy_status"] != "AVAILABLE":
        raise ApiError("ERR_PORT_NOT_AVAILABLE", 409, "port not available")
    rec["status"] = "CONFIRMED"
    touch(rec)
    port["occupancy_status"] = "RESERVED"
    touch(port)
    return success(serialize(rec))


@app.route("/reservations/<rid>/cancel", methods=["POST"])
def cancel_reservation(rid):
    uid, role = auth()
    require(role, {"Driver"})
    rec = get_or_404("reservations", rid)
    if uid != rec["driver_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not owner")
    if rec["status"] not in ("PENDING", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", 409, "cannot cancel")
    was_confirmed = rec["status"] == "CONFIRMED"
    rec["status"] = "CANCELLED"
    touch(rec)
    if was_confirmed:
        port = STORE["ports"].get(rec["port_id"])
        if port and port["occupancy_status"] == "RESERVED":
            port["occupancy_status"] = "AVAILABLE"
            touch(port)
    return success(serialize(rec))


@app.route("/reservations/<rid>/check-in", methods=["POST"])
def checkin_reservation(rid):
    uid, role = auth()
    require(role, {"Driver"})
    rec = get_or_404("reservations", rid)
    if uid != rec["driver_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not owner")
    if rec["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", 409, "not confirmed")
    rec["status"] = "FULFILLED"
    touch(rec)
    port = STORE["ports"].get(rec["port_id"])
    if port:
        port["occupancy_status"] = "OCCUPIED"
        touch(port)
    return success(serialize(rec))


# ===========================================================================
# MaintenanceWindow
# ===========================================================================
@app.route("/maintenance-windows", methods=["POST"])
def create_maintenance_window():
    _, role = auth()
    require(role, {"ProgramAdmin"})
    b = body()
    station_id = req_str(b, "station_id")
    ws = req_dt(b, "window_start")
    we = req_dt(b, "window_end")
    reason = req_str(b, "reason")
    get_or_404("stations", station_id)
    ws_dt, we_dt = parse_dt(ws), parse_dt(we)
    if we_dt <= ws_dt:
        raise ApiError("ERR_INVALID_WINDOW", 409, "window_end <= window_start")
    buffer = timedelta(minutes=MW_BUFFER_MIN)
    for other in STORE["maintenance_windows"].values():
        if other["station_id"] == station_id and other["status"] in ("SCHEDULED", "IN_PROGRESS"):
            ows, owe = parse_dt(other["window_start"]), parse_dt(other["window_end"])
            latest_start = max(ws_dt, ows)
            earliest_end = min(we_dt, owe)
            if latest_start <= earliest_end:
                gap = timedelta(0)
            else:
                gap = latest_start - earliest_end
            if gap < buffer:
                raise ApiError("ERR_MAINTENANCE_WINDOW_OVERLAP", 409, "window too close")
    rec = new_record("maintenance_windows")
    rec.update({
        "station_id": station_id, "window_start": ws, "window_end": we,
        "reason": reason, "status": "SCHEDULED",
    })
    STORE["maintenance_windows"][rec["id"]] = rec
    return success(serialize(rec), status=201)


@app.route("/maintenance-windows/<rid>", methods=["GET"])
def get_maintenance_window(rid):
    _, role = auth()
    require(role, {"ProgramAdmin", "FieldTechnician"})
    rec = get_or_404("maintenance_windows", rid)
    return success(serialize(rec))


@app.route("/maintenance-windows", methods=["GET"])
def list_maintenance_windows():
    _, role = auth()
    require(role, {"ProgramAdmin", "FieldTechnician"})
    items = list(STORE["maintenance_windows"].values())
    station_id = request.args.get("station_id")
    status = request.args.get("status")
    if station_id:
        items = [r for r in items if r["station_id"] == station_id]
    if status:
        items = [r for r in items if r["status"] == status]
    items = sort_created(items)
    page, pg = paginate(items)
    return success([serialize(r) for r in page], "array", pagination=pg)


@app.route("/maintenance-windows/<rid>/start", methods=["POST"])
def start_maintenance(rid):
    _, role = auth()
    require(role, {"FieldTechnician"})
    rec = get_or_404("maintenance_windows", rid)
    if rec["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "not scheduled")
    st = STORE["stations"].get(rec["station_id"])
    if not st or st["operational_status"] != "COMMISSIONED":
        raise ApiError("ERR_INVALID_STATE", 409, "station not commissioned")
    rec["status"] = "IN_PROGRESS"
    touch(rec)
    st["operational_status"] = "SUSPENDED"
    touch(st)
    return success(serialize(rec))


@app.route("/maintenance-windows/<rid>/complete", methods=["POST"])
def complete_maintenance(rid):
    _, role = auth()
    require(role, {"FieldTechnician"})
    rec = get_or_404("maintenance_windows", rid)
    if rec["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409, "not in progress")
    rec["status"] = "COMPLETED"
    touch(rec)
    st = STORE["stations"].get(rec["station_id"])
    if st and st["operational_status"] == "SUSPENDED":
        st["operational_status"] = "COMMISSIONED"
        touch(st)
    return success(serialize(rec))


# ===========================================================================
# WorkOrder
# ===========================================================================
@app.route("/work-orders", methods=["POST"])
def create_work_order():
    _, role = auth()
    require(role, {"FieldTechnician"})
    b = body()
    port_id = req_str(b, "port_id")
    severity = req_enum(b, "severity", {"LOW", "MEDIUM", "CRITICAL"})
    description = req_str(b, "description")
    port = get_or_404("ports", port_id)
    rec = new_record("work_orders")
    opened = now()
    rec.update({
        "port_id": port_id, "severity": severity, "description": description,
        "opened_at": opened, "resolved_at": None,
        "sla_due_at": opened + timedelta(hours=SLA_HOURS[severity]),
        "status": "OPEN",
    })
    STORE["work_orders"][rec["id"]] = rec
    if severity == "CRITICAL":
        drive_port_out_of_service(port)
    return success(serialize(rec), status=201)


@app.route("/work-orders/<rid>", methods=["GET"])
def get_work_order(rid):
    _, role = auth()
    require(role, {"ProgramAdmin", "FieldTechnician"})
    rec = get_or_404("work_orders", rid)
    return success(serialize(rec))


@app.route("/work-orders", methods=["GET"])
def list_work_orders():
    _, role = auth()
    require(role, {"ProgramAdmin", "FieldTechnician"})
    items = list(STORE["work_orders"].values())
    port_id = request.args.get("port_id")
    status = request.args.get("status")
    if port_id:
        items = [r for r in items if r["port_id"] == port_id]
    if status:
        items = [r for r in items if r["status"] == status]
    items = sort_created(items)
    page, pg = paginate(items)
    return success([serialize(r) for r in page], "array", pagination=pg)


@app.route("/work-orders/<rid>/resolve", methods=["POST"])
def resolve_work_order(rid):
    _, role = auth()
    require(role, {"FieldTechnician"})
    rec = get_or_404("work_orders", rid)
    if rec["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "not open")
    rec["resolved_at"] = now()
    rec["status"] = "RESOLVED"
    touch(rec)
    return success(serialize(rec))


# ===========================================================================
# RebateClaim
# ===========================================================================
@app.route("/rebate-claims", methods=["POST"])
def create_rebate_claim():
    _, role = auth()
    require(role, {"ProgramAdmin"})
    b = body()
    station_id = req_str(b, "station_id")
    grant_id = req_str(b, "grant_id")
    period_start = req_dt(b, "period_start")
    period_end = req_dt(b, "period_end")
    reported_energy = req_num(b, "reported_energy_kwh")
    reported_uptime = req_num(b, "reported_uptime_pct")
    expected_version = req_int(b, "expected_station_version")
    st = get_or_404("stations", station_id)
    get_or_404("grant_programs", grant_id)
    if parse_dt(period_end) <= parse_dt(period_start):
        raise ApiError("ERR_INVALID_PERIOD", 409, "period_end <= period_start")
    if expected_version != st["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "stale station version")
    rec = new_record("rebate_claims")
    rec.update({
        "station_id": station_id, "grant_id": grant_id, "period_start": period_start,
        "period_end": period_end, "reported_energy_kwh": reported_energy,
        "reported_uptime_pct": reported_uptime, "measured_uptime_pct": None,
        "estimated_amount_cents": 0, "audited_amount_cents": 0,
        "compliance_status": "PENDING", "submitted_by_user_id": None, "status": "DRAFT",
    })
    STORE["rebate_claims"][rec["id"]] = rec
    touch(st)  # increment station version
    return success(serialize(rec), status=201)


@app.route("/rebate-claims/<rid>", methods=["GET"])
def get_rebate_claim(rid):
    _, role = auth()
    require(role, {"ProgramAdmin"})
    rec = get_or_404("rebate_claims", rid)
    return success(serialize(rec))


@app.route("/rebate-claims", methods=["GET"])
def list_rebate_claims():
    _, role = auth()
    require(role, {"ProgramAdmin"})
    items = list(STORE["rebate_claims"].values())
    station_id = request.args.get("station_id")
    grant_id = request.args.get("grant_id")
    status = request.args.get("status")
    if station_id:
        items = [r for r in items if r["station_id"] == station_id]
    if grant_id:
        items = [r for r in items if r["grant_id"] == grant_id]
    if status:
        items = [r for r in items if r["status"] == status]
    items = sort_created(items)
    page, pg = paginate(items)
    return success([serialize(r) for r in page], "array", pagination=pg)


@app.route("/rebate-claims/<rid>/submit", methods=["POST"])
def submit_rebate_claim(rid):
    _, role = auth()
    require(role, {"ProgramAdmin"})
    uid = request.headers.get("X-User-ID")
    rec = get_or_404("rebate_claims", rid)
    if rec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "not draft")
    grant = STORE["grant_programs"].get(rec["grant_id"])
    if rec["reported_uptime_pct"] < grant["min_uptime_pct"]:
        raise ApiError("ERR_UPTIME_BELOW_THRESHOLD", 422, "uptime below threshold")
    raw = Decimal(str(rec["reported_energy_kwh"])) * grant["reimbursement_rate_cents_per_kwh"]
    estimated = min(round_half_up(raw), grant["reimbursement_cap_cents"])
    rec["estimated_amount_cents"] = estimated
    rec["compliance_status"] = "COMPLIANT"
    rec["submitted_by_user_id"] = uid
    rec["status"] = "SUBMITTED"
    touch(rec)
    return success(serialize(rec))


@app.route("/rebate-claims/<rid>/audit", methods=["POST"])
def audit_rebate_claim(rid):
    _, role = auth()
    require(role, {"ProgramAdmin"})
    rec = get_or_404("rebate_claims", rid)
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "not submitted")
    grant = STORE["grant_programs"].get(rec["grant_id"])
    ps, pe = parse_dt(rec["period_start"]), parse_dt(rec["period_end"])
    period_minutes = (pe - ps).total_seconds() / 60.0
    station_id = rec["station_id"]
    station_port_ids = {p["id"] for p in count_ports(station_id)}
    downtime = 0.0
    for wo in STORE["work_orders"].values():
        if wo["severity"] != "CRITICAL" or wo["port_id"] not in station_port_ids:
            continue
        if wo["resolved_at"] is None:
            continue
        o, r = wo["opened_at"], wo["resolved_at"]
        if o < pe and ps < r:  # [o,r) intersects [ps,pe)
            overlap_start = max(o, ps)
            overlap_end = min(r, pe)
            if overlap_end > overlap_start:
                downtime += (overlap_end - overlap_start).total_seconds() / 60.0
    if period_minutes > 0:
        measured = round_half_up_2(100 * (1 - downtime / period_minutes))
    else:
        measured = 100.0
    if measured < 0:
        measured = 0.0
    if measured > 100:
        measured = 100.0
    rec["measured_uptime_pct"] = measured
    if measured >= grant["min_uptime_pct"]:
        rec["audited_amount_cents"] = rec["estimated_amount_cents"]
        rec["compliance_status"] = "COMPLIANT"
    else:
        rec["audited_amount_cents"] = 0
        rec["compliance_status"] = "NON_COMPLIANT"
    rec["status"] = "AUDITED"
    touch(rec)
    return success(serialize(rec))


@app.route("/rebate-claims/<rid>/approve", methods=["POST"])
def approve_rebate_claim(rid):
    _, role = auth()
    require(role, {"ProgramAdmin"})
    uid = request.headers.get("X-User-ID")
    rec = get_or_404("rebate_claims", rid)
    if rec["status"] != "AUDITED":
        raise ApiError("ERR_INVALID_STATE", 409, "not audited")
    if uid == rec["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409, "four-eyes control")
    rec["status"] = "APPROVED"
    touch(rec)
    return success(serialize(rec))


@app.route("/rebate-claims/<rid>/reject", methods=["POST"])
def reject_rebate_claim(rid):
    _, role = auth()
    require(role, {"ProgramAdmin"})
    rec = get_or_404("rebate_claims", rid)
    if rec["status"] not in ("SUBMITTED", "AUDITED"):
        raise ApiError("ERR_INVALID_STATE", 409, "cannot reject")
    rec["status"] = "REJECTED"
    touch(rec)
    return success(serialize(rec))


# ===========================================================================
# RevenueStatement
# ===========================================================================
@app.route("/revenue-statements", methods=["POST"])
def create_revenue_statement():
    _, role = auth()
    require(role, {"ProgramAdmin"})
    b = body()
    site_id = req_str(b, "site_id")
    period_start = req_dt(b, "period_start")
    period_end = req_dt(b, "period_end")
    basis = req_enum(b, "basis", {"GROSS", "NET"})
    expected_version = req_int(b, "expected_site_version")
    site = get_or_404("host_sites", site_id)
    ps, pe = parse_dt(period_start), parse_dt(period_end)
    if pe <= ps:
        raise ApiError("ERR_INVALID_PERIOD", 409, "period_end <= period_start")
    if expected_version != site["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "stale site version")

    # collect included sessions
    station_ids = {s["id"] for s in STORE["stations"].values() if s["site_id"] == site_id}
    port_to_station = {p["id"]: p["station_id"] for p in STORE["ports"].values()}
    included = []
    for s in STORE["charging_sessions"].values():
        if s["status"] != "FINALIZED":
            continue
        st_id = port_to_station.get(s["port_id"])
        if st_id not in station_ids:
            continue
        if s["started_at"] is None:
            continue
        if ps <= s["started_at"] < pe:
            included.append(s)
    included.sort(key=lambda s: (s["started_at"], s["created_at"], s["_seq"]))

    txn_pct = site["transaction_fee_pct"]
    flat = site["transaction_fee_flat_cents"]
    rev_pct = site["revenue_share_pct"]
    gross = 0
    txn_fees = 0
    host_share = 0
    for s in included:
        fc = s["final_cost_cents"]
        gross += fc
        per_fee = round_half_up(Decimal(str(txn_pct)) * fc) + flat
        txn_fees += per_fee
        if basis == "GROSS":
            host_share += round_half_up(Decimal(str(rev_pct)) * fc)
        else:
            net_base = fc - per_fee
            host_share += round_half_up(Decimal(str(rev_pct)) * net_base)
    program_share = gross - host_share - txn_fees

    rec = new_record("revenue_statements")
    rec.update({
        "site_id": site_id, "period_start": period_start, "period_end": period_end,
        "basis": basis, "gross_revenue_cents": gross, "transaction_fees_cents": txn_fees,
        "host_share_cents": host_share, "program_share_cents": program_share,
        "session_count": len(included), "status": "DRAFT",
    })
    STORE["revenue_statements"][rec["id"]] = rec
    touch(site)  # increment site version
    return success(serialize(rec), status=201)


@app.route("/revenue-statements/<rid>", methods=["GET"])
def get_revenue_statement(rid):
    uid, role = auth()
    require(role, {"ProgramAdmin", "HostOperator"})
    rec = get_or_404("revenue_statements", rid)
    if role == "HostOperator" and uid != rec["site_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not owner")
    return success(serialize(rec))


@app.route("/revenue-statements", methods=["GET"])
def list_revenue_statements():
    uid, role = auth()
    require(role, {"ProgramAdmin", "HostOperator"})
    items = list(STORE["revenue_statements"].values())
    site_id = request.args.get("site_id")
    status = request.args.get("status")
    if site_id:
        items = [r for r in items if r["site_id"] == site_id]
    if status:
        items = [r for r in items if r["status"] == status]
    if role == "HostOperator":
        items = [r for r in items if r["site_id"] == uid]
    items = sort_created(items)
    page, pg = paginate(items)
    return success([serialize(r) for r in page], "array", pagination=pg)


@app.route("/revenue-statements/<rid>/finalize", methods=["POST"])
def finalize_revenue_statement(rid):
    _, role = auth()
    require(role, {"ProgramAdmin"})
    rec = get_or_404("revenue_statements", rid)
    if rec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "not draft")
    rec["status"] = "FINALIZED"
    touch(rec)
    return success(serialize(rec))


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = auth()
    require(role, {"ProgramAdmin"})
    b = body()
    to_iso = req_str(b, "to_iso8601")
    CLOCK["now"] = parse_dt(to_iso)
    return success({}, status=200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
