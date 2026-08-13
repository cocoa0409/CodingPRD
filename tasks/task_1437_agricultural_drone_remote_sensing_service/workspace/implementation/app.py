#!/usr/bin/env python3
"""Agricultural Drone & Remote-Sensing Service API (/ag-drone).

In-memory Flask implementation of the PRD contract. The store starts empty on
every boot; the logical clock defaults to 2026-08-01T00:00:00Z and only moves
via POST /ag-drone/_clock/set_current_utc.
"""

import os
import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, jsonify, request

app = Flask(__name__)

# ============================== logical clock ==============================

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": DEFAULT_NOW}


def now_utc():
    return _clock["now"]


# ============================== store ==============================

STORE = {
    "plans": {},
    "growers": {},
    "fields": {},
    "pilots": {},
    "authorizations": {},
    "missions": {},
    "deliverables": {},
    "alerts": {},
    "spray_records": {},
    "claims": {},
}
_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


# ============================== time helpers ==============================

def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def fmt_instant(dt):
    """ISO 8601 UTC at seconds precision."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_instant(v, field):
    if not isinstance(v, str) or not v.strip():
        fail("ERR_INVALID_REQUEST", 400, field + " must be an ISO8601 timestamp string")
    s = v.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        fail("ERR_INVALID_REQUEST", 400, field + " is not a valid ISO8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date_value(v, field):
    if not isinstance(v, str):
        fail("ERR_INVALID_REQUEST", 400, field + " must be a YYYY-MM-DD date string")
    try:
        return datetime.strptime(v.strip(), "%Y-%m-%d").date()
    except ValueError:
        fail("ERR_INVALID_REQUEST", 400, field + " must be a YYYY-MM-DD date string")


# ============================== errors / envelope ==============================

class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def fail(error_id, status, message):
    raise ApiError(error_id, status, message)


def make_meta(pagination=None):
    meta = {
        "api_request_id": "req_" + "".join(
            secrets.choice(string.ascii_letters + string.digits) for _ in range(20)
        ),
        "api_request_timestamp": fmt_ts(datetime.now(timezone.utc)),
    }
    if pagination:
        meta.update(pagination)
    return meta


def success(data, status=200, response_type="object", pagination=None):
    body = {"meta": make_meta(pagination), "response_type": response_type, "data": data}
    return jsonify(body), status


@app.errorhandler(ApiError)
def _api_error(e):
    return jsonify({
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }), e.status


@app.errorhandler(404)
def _not_found(e):
    return jsonify({
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "resource not found"},
    }), 404


@app.errorhandler(405)
def _method_not_allowed(e):
    return jsonify({
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "resource not found"},
    }), 404


@app.errorhandler(Exception)
def _generic_error(e):
    if isinstance(e, ApiError):
        return _api_error(e)
    return jsonify({
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": str(e)},
    }), 500


# ============================== auth ==============================

def require_roles(allowed):
    uid = (request.headers.get("X-User-ID") or "").strip()
    role = (request.headers.get("X-User-Role") or "").strip()
    if not uid or not role:
        fail("ERR_MISSING_AUTH_CONTEXT", 401,
             "X-User-ID and X-User-Role headers are required and must be non-empty")
    if role not in allowed:
        fail("ERR_FORBIDDEN_ROLE", 403, "role " + role + " is not permitted on this endpoint")
    return uid, role


def check_grower_scope(role, uid, grower_id):
    """Grower-role callers only see their own account tree."""
    if role == "Grower" and uid != grower_id:
        fail("ERR_NOT_FOUND", 404, "resource not found")


# ============================== body / field validators ==============================

def body():
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        fail("ERR_INVALID_REQUEST", 400, "request body must be valid JSON")
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", 400, "request body must be a JSON object")
    return data


def req_str(b, name):
    v = b.get(name)
    if not isinstance(v, str) or not v:
        fail("ERR_INVALID_REQUEST", 400, name + " is required and must be a non-empty string")
    return v


def req_int(b, name):
    v = b.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        fail("ERR_INVALID_REQUEST", 400, name + " is required and must be an integer")
    return v


def opt_int(b, name, default):
    if name not in b or b[name] is None:
        return default
    v = b[name]
    if isinstance(v, bool) or not isinstance(v, int):
        fail("ERR_INVALID_REQUEST", 400, name + " must be an integer")
    return v


def opt_num(b, name, default):
    if name not in b or b[name] is None:
        return default
    v = b[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        fail("ERR_INVALID_REQUEST", 400, name + " must be a number")
    return v


def opt_str(b, name, default):
    if name not in b or b[name] is None:
        return default
    v = b[name]
    if not isinstance(v, str):
        fail("ERR_INVALID_REQUEST", 400, name + " must be a string")
    return v


def opt_bool(b, name, default):
    if name not in b or b[name] is None:
        return default
    v = b[name]
    if not isinstance(v, bool):
        fail("ERR_INVALID_REQUEST", 400, name + " must be a boolean")
    return v


def get_or_404(coll, rid, label="resource"):
    e = STORE[coll].get(rid)
    if e is None:
        fail("ERR_NOT_FOUND", 404, label + " not found")
    return e


def new_entity(common=True):
    e = {"id": str(uuid.uuid4()), "created_at": now_utc(), "_seq": next_seq()}
    if common:
        e["updated_at"] = e["created_at"]
        e["version"] = 1
    return e


def bump(e):
    e["version"] += 1
    e["updated_at"] = now_utc()


# ============================== pagination ==============================

def paginate(items):
    args = request.args
    try:
        limit = int(args.get("limit", 10))
        offset = int(args.get("offset", 0))
    except (ValueError, TypeError):
        fail("ERR_INVALID_REQUEST", 400, "limit and offset must be integers")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }


def list_response(items, serializer):
    items = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    page, pag = paginate(items)
    return success([serializer(e) for e in page], 200, "array", pag)


# ============================== serializers ==============================

def ser_plan(p):
    return {
        "id": p["id"],
        "plan_code": p["plan_code"],
        "included_acres_per_year": p["included_acres_per_year"],
        "base_fee_cents": p["base_fee_cents"],
        "overage_rate_cents_per_acre": p["overage_rate_cents_per_acre"],
        "spray_allowed": p["spray_allowed"],
        "ndvi_turnaround_hours": p["ndvi_turnaround_hours"],
        "storage_retention_days": p["storage_retention_days"],
        "created_at": fmt_ts(p["created_at"]),
        "updated_at": fmt_ts(p["updated_at"]),
        "version": p["version"],
    }


def ser_grower(g):
    return {
        "id": g["id"],
        "legal_name": g["legal_name"],
        "contact_email": g["contact_email"],
        "subscription_plan_id": g["subscription_plan_id"],
        "subscription_started_on": g["subscription_started_on"].isoformat(),
        "acres_included_ytd": g["acres_included_ytd"],
        "credit_balance_cents": g["credit_balance_cents"],
        "liability_coverage_cents": g["liability_coverage_cents"],
        "status": g["status"],
        "created_at": fmt_ts(g["created_at"]),
        "updated_at": fmt_ts(g["updated_at"]),
        "version": g["version"],
    }


def ser_field(f):
    return {
        "id": f["id"],
        "grower_id": f["grower_id"],
        "field_name": f["field_name"],
        "legal_acres": f["legal_acres"],
        "surveyed_acres": f["surveyed_acres"],
        "airspace_class": f["airspace_class"],
        "laanc_required": f["laanc_required"],
        "health_score": f["health_score"],
        "insurance_policy_no": f["insurance_policy_no"],
        "created_at": fmt_ts(f["created_at"]),
        "updated_at": fmt_ts(f["updated_at"]),
        "version": f["version"],
    }


def ser_pilot(p):
    return {
        "id": p["id"],
        "pilot_name": p["pilot_name"],
        "part107_certificate_no": p["part107_certificate_no"],
        "part107_expires_on": p["part107_expires_on"].isoformat(),
        "applicator_license_no": p["applicator_license_no"],
        "applicator_license_expires_on": p["applicator_license_expires_on"],
        "night_waiver": p["night_waiver"],
        "status": p["status"],
        "created_at": fmt_ts(p["created_at"]),
        "updated_at": fmt_ts(p["updated_at"]),
        "version": p["version"],
    }


def ser_authorization(a):
    return {
        "id": a["id"],
        "field_id": a["field_id"],
        "authorization_ref": a["authorization_ref"],
        "max_altitude_ft": a["max_altitude_ft"],
        "effective_from": fmt_instant(a["effective_from"]),
        "effective_until": fmt_instant(a["effective_until"]),
        "status": a["status"],
        "created_at": fmt_ts(a["created_at"]),
    }


def ser_mission(m):
    return {
        "id": m["id"],
        "field_id": m["field_id"],
        "mission_type": m["mission_type"],
        "pilot_id": m["pilot_id"],
        "authorization_id": m["authorization_id"],
        "scheduled_start": fmt_instant(m["scheduled_start"]),
        "scheduled_end": fmt_instant(m["scheduled_end"]),
        "acres_planned": m["acres_planned"],
        "acres_flown": m["acres_flown"],
        "wind_kt_max_observed": m["wind_kt_max_observed"],
        "chemical_product_label": m["chemical_product_label"],
        "gallons_dispensed": m["gallons_dispensed"],
        "status": m["status"],
        "created_at": fmt_ts(m["created_at"]),
        "updated_at": fmt_ts(m["updated_at"]),
        "version": m["version"],
    }


def ser_deliverable(d):
    return {
        "id": d["id"],
        "mission_id": d["mission_id"],
        "kind": d["kind"],
        "ndvi_mean": d["ndvi_mean"],
        "plant_count_per_acre": d["plant_count_per_acre"],
        "anomaly_count": d["anomaly_count"],
        "storage_uri": d["storage_uri"],
        "accessible_until": fmt_instant(d["accessible_until"]) if d["accessible_until"] else None,
        "status": d["status"],
        "created_at": fmt_ts(d["created_at"]),
        "updated_at": fmt_ts(d["updated_at"]),
        "version": d["version"],
    }


def ser_alert(a):
    return {
        "id": a["id"],
        "field_id": a["field_id"],
        "deliverable_id": a["deliverable_id"],
        "severity": a["severity"],
        "reviewing_agronomist_id": a["reviewing_agronomist_id"],
        "review_notes": a["review_notes"],
        "review_outcome": a["review_outcome"],
        "status": a["status"],
        "created_at": fmt_ts(a["created_at"]),
        "updated_at": fmt_ts(a["updated_at"]),
        "version": a["version"],
    }


def ser_spray_record(r):
    return {
        "id": r["id"],
        "mission_id": r["mission_id"],
        "applicator_license_no": r["applicator_license_no"],
        "chemical_product_label": r["chemical_product_label"],
        "gallons_dispensed": r["gallons_dispensed"],
        "restricted_entry_interval_hours": r["restricted_entry_interval_hours"],
        "record_locked": r["record_locked"],
        "created_at": fmt_ts(r["created_at"]),
    }


def ser_claim(c):
    return {
        "id": c["id"],
        "grower_id": c["grower_id"],
        "mission_id": c["mission_id"],
        "claim_amount_cents": c["claim_amount_cents"],
        "approved_amount_cents": c["approved_amount_cents"],
        "adjuster_user_id": c["adjuster_user_id"],
        "status": c["status"],
        "created_at": fmt_ts(c["created_at"]),
        "updated_at": fmt_ts(c["updated_at"]),
        "version": c["version"],
    }


# ============================== domain helpers ==============================

TERMINAL_MISSION_STATES = {"COMPLETED", "CANCELLED", "WEATHER_ABORTED"}
CONTROLLED_AIRSPACE = {"B", "C", "D"}
SEVERITY_WEIGHT = {"LOW": 2, "MEDIUM": 5, "HIGH": 12}
TIER1_OVERAGE_CAP = 200
TIER2_DISCOUNT = Decimal("0.8")
NDVI_STRESS_DIVISOR = Decimal(1000)
STAND_MIN_PLANTS = 20000
STAND_TARGET_PLANTS = 30000
WIND_LIMIT_KT = 20
WINDOW_BUFFER = timedelta(minutes=30)


def rhu(dec):
    """Round half-up to an integer."""
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def grower_of_field(field):
    return STORE["growers"].get(field["grower_id"])


def grower_id_of_mission(m):
    f = STORE["fields"].get(m["field_id"])
    return f["grower_id"] if f else None


def cancel_nonterminal_missions(missions):
    for m in missions:
        if m["status"] in ("PLANNED", "AUTHORIZED"):
            m["status"] = "CANCELLED"
            bump(m)


def field_missions(field_id):
    return [m for m in STORE["missions"].values() if m["field_id"] == field_id]


def window_conflict(field_id, start, end, exclude_id):
    """Buffered half-open overlap scan per calc mission_window_conflict."""
    s = start - WINDOW_BUFFER
    e = end + WINDOW_BUFFER
    for m in STORE["missions"].values():
        if m["field_id"] != field_id or m["id"] == exclude_id:
            continue
        if m["status"] in TERMINAL_MISSION_STATES:
            continue
        ms = m["scheduled_start"] - WINDOW_BUFFER
        me = m["scheduled_end"] + WINDOW_BUFFER
        if max(s, ms) < min(e, me):
            return True
    return False


def field_deliverables(field_id):
    out = []
    for d in STORE["deliverables"].values():
        m = STORE["missions"].get(d["mission_id"])
        if m and m["field_id"] == field_id:
            out.append(d)
    return out


def recompute_health(field, double_alert=None):
    cands = [d for d in field_deliverables(field["id"])
             if d["status"] in ("READY", "DELIVERED")]
    if cands:
        latest = max(cands, key=lambda d: (d["created_at"], d["_seq"]))
        if latest["kind"] == "NDVI":
            base = rhu(Decimal(str(latest["ndvi_mean"])) * Decimal(100))
        else:
            base = min(100, rhu(Decimal(latest["plant_count_per_acre"]) * Decimal(100)
                                / Decimal(STAND_TARGET_PLANTS)))
    else:
        base = 100
    penalty = 0
    for a in STORE["alerts"].values():
        if a["field_id"] == field["id"] and a["status"] in ("OPEN", "UNDER_REVIEW"):
            penalty += SEVERITY_WEIGHT[a["severity"]]
    if double_alert is not None:
        penalty += 2 * SEVERITY_WEIGHT[double_alert["severity"]]
    field["health_score"] = max(0, min(100, base - penalty))
    bump(field)


def run_sweeps():
    now = now_utc()
    for a in STORE["authorizations"].values():
        if a["status"] == "ACTIVE" and now >= a["effective_until"]:
            a["status"] = "EXPIRED"
            for m in STORE["missions"].values():
                if (m["authorization_id"] == a["id"] and m["status"] == "AUTHORIZED"
                        and m["scheduled_start"] >= now):
                    m["status"] = "CANCELLED"
                    bump(m)
    for d in STORE["deliverables"].values():
        if (d["status"] in ("READY", "DELIVERED") and d["accessible_until"]
                and now >= d["accessible_until"]):
            d["status"] = "EXPIRED"
            bump(d)


# ============================== SubscriptionPlan ==============================

@app.post("/ag-drone/subscription-plans")
def create_plan():
    require_roles({"OpsAdmin"})
    b = body()
    plan_code = req_str(b, "plan_code")
    for p in STORE["plans"].values():
        if p["plan_code"] == plan_code:
            fail("ERR_INVALID_REQUEST", 400, "plan_code must be unique")
    p = new_entity()
    p.update({
        "plan_code": plan_code,
        "included_acres_per_year": req_int(b, "included_acres_per_year"),
        "base_fee_cents": req_int(b, "base_fee_cents"),
        "overage_rate_cents_per_acre": req_int(b, "overage_rate_cents_per_acre"),
        "spray_allowed": _req_bool(b, "spray_allowed"),
        "ndvi_turnaround_hours": req_int(b, "ndvi_turnaround_hours"),
        "storage_retention_days": req_int(b, "storage_retention_days"),
    })
    STORE["plans"][p["id"]] = p
    return success(ser_plan(p), 201)


def _req_bool(b, name):
    v = b.get(name)
    if not isinstance(v, bool):
        fail("ERR_INVALID_REQUEST", 400, name + " is required and must be a boolean")
    return v


@app.get("/ag-drone/subscription-plans/<pid>")
def get_plan(pid):
    require_roles({"OpsAdmin", "FlightCoordinator", "Grower"})
    return success(ser_plan(get_or_404("plans", pid, "subscription plan")))


@app.get("/ag-drone/subscription-plans")
def list_plans():
    require_roles({"OpsAdmin", "FlightCoordinator", "Grower"})
    return list_response(list(STORE["plans"].values()), ser_plan)


# ============================== Grower ==============================

@app.post("/ag-drone/growers")
def create_grower():
    require_roles({"OpsAdmin"})
    b = body()
    legal_name = req_str(b, "legal_name")
    contact_email = req_str(b, "contact_email")
    plan_id = req_str(b, "subscription_plan_id")
    plan = get_or_404("plans", plan_id, "subscription plan")
    started = parse_date_value(b.get("subscription_started_on"), "subscription_started_on")
    coverage = req_int(b, "liability_coverage_cents")
    if coverage < 50000000:
        fail("ERR_INVALID_REQUEST", 400,
             "liability_coverage_cents must be at least 50000000")
    g = new_entity()
    g.update({
        "legal_name": legal_name,
        "contact_email": contact_email,
        "subscription_plan_id": plan["id"],
        "subscription_started_on": started,
        "acres_included_ytd": 0,
        "credit_balance_cents": 0,
        "liability_coverage_cents": coverage,
        "status": "ACTIVE",
    })
    STORE["growers"][g["id"]] = g
    return success(ser_grower(g), 201)


@app.get("/ag-drone/growers/<gid>")
def get_grower(gid):
    uid, role = require_roles({"OpsAdmin", "FlightCoordinator", "Grower", "ClaimsAdjuster"})
    g = get_or_404("growers", gid, "grower")
    check_grower_scope(role, uid, g["id"])
    return success(ser_grower(g))


@app.get("/ag-drone/growers")
def list_growers():
    require_roles({"OpsAdmin", "FlightCoordinator"})
    items = list(STORE["growers"].values())
    status = request.args.get("status")
    if status:
        items = [g for g in items if g["status"] == status]
    plan_id = request.args.get("subscription_plan_id")
    if plan_id:
        items = [g for g in items if g["subscription_plan_id"] == plan_id]
    return list_response(items, ser_grower)


@app.patch("/ag-drone/growers/<gid>")
def patch_grower(gid):
    require_roles({"OpsAdmin"})
    g = get_or_404("growers", gid, "grower")
    b = body()
    expected = req_int(b, "expected_grower_version")
    new_plan_id = None
    if "subscription_plan_id" in b and b["subscription_plan_id"] is not None:
        if not isinstance(b["subscription_plan_id"], str):
            fail("ERR_INVALID_REQUEST", 400, "subscription_plan_id must be a string")
        new_plan_id = get_or_404("plans", b["subscription_plan_id"],
                                 "subscription plan")["id"]
    new_coverage = None
    if "liability_coverage_cents" in b and b["liability_coverage_cents"] is not None:
        new_coverage = req_int(b, "liability_coverage_cents")
        if new_coverage < 50000000:
            fail("ERR_INVALID_REQUEST", 400,
                 "liability_coverage_cents must be at least 50000000")
    if expected != g["version"]:
        fail("ERR_STALE_GROWER_VERSION", 412,
             "expected_grower_version does not match the grower's current version")
    if new_plan_id is not None:
        g["subscription_plan_id"] = new_plan_id
    if new_coverage is not None:
        g["liability_coverage_cents"] = new_coverage
    bump(g)
    return success(ser_grower(g))


@app.post("/ag-drone/growers/<gid>/suspend")
def suspend_grower(gid):
    require_roles({"OpsAdmin"})
    g = get_or_404("growers", gid, "grower")
    if g["status"] != "ACTIVE":
        fail("ERR_GROWER_NOT_ACTIVE", 409, "grower must be ACTIVE to suspend")
    g["status"] = "SUSPENDED"
    bump(g)
    for f in STORE["fields"].values():
        if f["grower_id"] == g["id"]:
            cancel_nonterminal_missions(field_missions(f["id"]))
    return success(ser_grower(g))


@app.post("/ag-drone/growers/<gid>/reinstate")
def reinstate_grower(gid):
    require_roles({"OpsAdmin"})
    g = get_or_404("growers", gid, "grower")
    if g["status"] != "SUSPENDED":
        fail("ERR_GROWER_NOT_SUSPENDED", 409, "grower must be SUSPENDED to reinstate")
    g["status"] = "ACTIVE"
    bump(g)
    return success(ser_grower(g))


@app.post("/ag-drone/growers/<gid>/terminate")
def terminate_grower(gid):
    require_roles({"OpsAdmin"})
    g = get_or_404("growers", gid, "grower")
    if g["status"] != "SUSPENDED":
        fail("ERR_GROWER_NOT_SUSPENDED", 409, "grower must be SUSPENDED to terminate")
    for f in STORE["fields"].values():
        if f["grower_id"] != g["id"]:
            continue
        for m in field_missions(f["id"]):
            if m["status"] == "IN_FLIGHT":
                fail("ERR_MISSION_IN_FLIGHT", 409,
                     "a mission on the grower's fields is IN_FLIGHT")
    g["status"] = "TERMINATED"
    bump(g)
    for f in STORE["fields"].values():
        if f["grower_id"] == g["id"]:
            cancel_nonterminal_missions(field_missions(f["id"]))
    for c in STORE["claims"].values():
        if c["grower_id"] == g["id"] and c["status"] in ("SUBMITTED", "UNDER_REVIEW", "APPROVED"):
            c["status"] = "DENIED"
            c["approved_amount_cents"] = 0
            bump(c)
    return success(ser_grower(g))


@app.post("/ag-drone/growers/<gid>/invoice")
def invoice_grower(gid):
    require_roles({"OpsAdmin"})
    g = get_or_404("growers", gid, "grower")
    b = body()
    period_start = parse_instant(b.get("period_start"), "period_start")
    period_end = parse_instant(b.get("period_end"), "period_end")
    plan = STORE["plans"].get(g["subscription_plan_id"])
    if plan is None:
        fail("ERR_NOT_FOUND", 404, "subscription plan not found")
    rate = plan["overage_rate_cents_per_acre"]
    included = plan["included_acres_per_year"]
    sub_start = g["subscription_started_on"]
    try:
        anniversary = sub_start.replace(year=sub_start.year + 1)
    except ValueError:
        anniversary = sub_start.replace(year=sub_start.year + 1, day=28)

    grower_field_ids = {f["id"] for f in STORE["fields"].values()
                        if f["grower_id"] == g["id"]}
    completed = [m for m in STORE["missions"].values()
                 if m["field_id"] in grower_field_ids and m["status"] == "COMPLETED"
                 and m.get("_completed_at") is not None]
    in_period = sorted(
        [m for m in completed
         if period_start <= m["_completed_at"] < period_end],
        key=lambda m: (m["_completed_at"], m["_seq"]),
    )

    discounted_rate = int((Decimal(rate) * TIER2_DISCOUNT).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))
    line_items = []
    invoice_cents = 0
    provisional_total = 0
    for m in in_period:
        prior = sum(
            x["acres_flown"] for x in completed
            if sub_start <= x["_completed_at"].date() < anniversary
            and (x["_completed_at"], x["_seq"]) < (m["_completed_at"], m["_seq"])
        )
        new_acres = m["acres_flown"]
        included_portion = max(0, min(new_acres, included - prior))
        overage = new_acres - included_portion
        t1 = min(overage, TIER1_OVERAGE_CAP)
        t2 = overage - t1
        final_cents = t1 * rate + t2 * discounted_rate
        provisional_cents = overage * rate
        invoice_cents += final_cents
        provisional_total += provisional_cents
        line_items.append({
            "mission_id": m["id"],
            "acres_flown": new_acres,
            "overage_acres": overage,
            "provisional_cents": provisional_cents,
            "final_cents": final_cents,
        })
    g["credit_balance_cents"] -= invoice_cents
    bump(g)
    return success({
        "invoice_cents": invoice_cents,
        "provisional_total_cents": provisional_total,
        "line_items": line_items,
    })


# ============================== Field ==============================

@app.post("/ag-drone/growers/<gid>/fields")
def create_field(gid):
    uid, role = require_roles({"OpsAdmin", "Grower"})
    g = get_or_404("growers", gid, "grower")
    check_grower_scope(role, uid, g["id"])
    b = body()
    field_name = req_str(b, "field_name")
    legal_acres = req_int(b, "legal_acres")
    if legal_acres <= 0:
        fail("ERR_INVALID_REQUEST", 400, "legal_acres must be a positive integer")
    airspace_class = b.get("airspace_class")
    if airspace_class not in ("G", "E", "D", "C", "B"):
        fail("ERR_INVALID_REQUEST", 400, "airspace_class must be one of G, E, D, C, B")
    insurance_policy_no = req_str(b, "insurance_policy_no")
    f = new_entity()
    f.update({
        "grower_id": g["id"],
        "field_name": field_name,
        "legal_acres": legal_acres,
        "surveyed_acres": legal_acres,
        "airspace_class": airspace_class,
        "laanc_required": airspace_class in CONTROLLED_AIRSPACE,
        "health_score": 100,
        "insurance_policy_no": insurance_policy_no,
    })
    STORE["fields"][f["id"]] = f
    return success(ser_field(f), 201)


@app.get("/ag-drone/fields/<fid>")
def get_field(fid):
    uid, role = require_roles(
        {"OpsAdmin", "FlightCoordinator", "Grower", "Agronomist", "RemotePilot"})
    f = get_or_404("fields", fid, "field")
    check_grower_scope(role, uid, f["grower_id"])
    return success(ser_field(f))


@app.get("/ag-drone/growers/<gid>/fields")
def list_grower_fields(gid):
    uid, role = require_roles({"OpsAdmin", "FlightCoordinator", "Grower"})
    g = get_or_404("growers", gid, "grower")
    check_grower_scope(role, uid, g["id"])
    items = [f for f in STORE["fields"].values() if f["grower_id"] == g["id"]]
    return list_response(items, ser_field)


# ============================== PilotProfile ==============================

@app.post("/ag-drone/pilots")
def create_pilot():
    require_roles({"OpsAdmin"})
    b = body()
    pilot_name = req_str(b, "pilot_name")
    cert_no = req_str(b, "part107_certificate_no")
    for p in STORE["pilots"].values():
        if p["part107_certificate_no"] == cert_no:
            fail("ERR_INVALID_REQUEST", 400,
                 "part107_certificate_no must be unique across the registry")
    expires = parse_date_value(b.get("part107_expires_on"), "part107_expires_on")
    applicator_no = opt_str(b, "applicator_license_no", "")
    if applicator_no:
        applicator_exp = parse_date_value(b.get("applicator_license_expires_on"),
                                          "applicator_license_expires_on").isoformat()
    else:
        applicator_exp = ""
    night_waiver = opt_bool(b, "night_waiver", False)
    p = new_entity()
    p.update({
        "pilot_name": pilot_name,
        "part107_certificate_no": cert_no,
        "part107_expires_on": expires,
        "applicator_license_no": applicator_no,
        "applicator_license_expires_on": applicator_exp,
        "night_waiver": night_waiver,
        "status": "ACTIVE",
    })
    STORE["pilots"][p["id"]] = p
    return success(ser_pilot(p), 201)


@app.get("/ag-drone/pilots/<pid>")
def get_pilot(pid):
    require_roles({"OpsAdmin", "FlightCoordinator", "RemotePilot", "Agronomist"})
    return success(ser_pilot(get_or_404("pilots", pid, "pilot")))


@app.get("/ag-drone/pilots")
def list_pilots():
    require_roles({"OpsAdmin", "FlightCoordinator"})
    items = list(STORE["pilots"].values())
    status = request.args.get("status")
    if status:
        items = [p for p in items if p["status"] == status]
    return list_response(items, ser_pilot)


# ============================== AirspaceAuthorization ==============================

@app.post("/ag-drone/airspace-authorizations")
def create_authorization():
    require_roles({"OpsAdmin", "FlightCoordinator"})
    b = body()
    field_id = req_str(b, "field_id")
    field = get_or_404("fields", field_id, "field")
    ref = req_str(b, "authorization_ref")
    max_alt = req_int(b, "max_altitude_ft")
    if max_alt > 400 or max_alt < 0:
        fail("ERR_INVALID_REQUEST", 400, "max_altitude_ft must be at most 400")
    eff_from = parse_instant(b.get("effective_from"), "effective_from")
    eff_until = parse_instant(b.get("effective_until"), "effective_until")
    a = new_entity(common=False)
    a.update({
        "field_id": field["id"],
        "authorization_ref": ref,
        "max_altitude_ft": max_alt,
        "effective_from": eff_from,
        "effective_until": eff_until,
        "status": "ACTIVE",
    })
    STORE["authorizations"][a["id"]] = a
    return success(ser_authorization(a), 201)


@app.get("/ag-drone/airspace-authorizations/<aid>")
def get_authorization(aid):
    require_roles({"OpsAdmin", "FlightCoordinator", "RemotePilot"})
    return success(ser_authorization(get_or_404("authorizations", aid, "authorization")))


@app.get("/ag-drone/airspace-authorizations")
def list_authorizations():
    require_roles({"OpsAdmin", "FlightCoordinator", "RemotePilot"})
    items = list(STORE["authorizations"].values())
    field_id = request.args.get("field_id")
    if field_id:
        items = [a for a in items if a["field_id"] == field_id]
    status = request.args.get("status")
    if status:
        items = [a for a in items if a["status"] == status]
    return list_response(items, ser_authorization)


@app.post("/ag-drone/airspace-authorizations/<aid>/revoke")
def revoke_authorization(aid):
    require_roles({"OpsAdmin"})
    a = get_or_404("authorizations", aid, "authorization")
    if a["status"] != "ACTIVE":
        fail("ERR_AUTH_NOT_ACTIVE", 409, "authorization must be ACTIVE to revoke")
    a["status"] = "REVOKED"
    for m in STORE["missions"].values():
        if m["authorization_id"] == a["id"] and m["status"] in ("PLANNED", "AUTHORIZED"):
            m["status"] = "CANCELLED"
            bump(m)
    return success(ser_authorization(a))


# ============================== FlightMission ==============================

def _validate_mission_window_shape(start, end):
    if end <= start:
        fail("ERR_INVALID_REQUEST", 400, "scheduled_end must be after scheduled_start")
    if end - start > timedelta(hours=6):
        fail("ERR_INVALID_REQUEST", 400, "mission window must not exceed 6 hours")


@app.post("/ag-drone/fields/<fid>/missions")
def create_mission(fid):
    require_roles({"FlightCoordinator"})
    field = get_or_404("fields", fid, "field")
    b = body()
    mission_type = b.get("mission_type")
    if mission_type not in ("SCOUT", "SPRAY"):
        fail("ERR_INVALID_REQUEST", 400, "mission_type must be SCOUT or SPRAY")
    pilot_id = req_str(b, "pilot_id")
    pilot = get_or_404("pilots", pilot_id, "pilot")
    authorization_id = b.get("authorization_id")
    if authorization_id is not None:
        if not isinstance(authorization_id, str):
            fail("ERR_INVALID_REQUEST", 400, "authorization_id must be a string")
        get_or_404("authorizations", authorization_id, "authorization")
    start = parse_instant(b.get("scheduled_start"), "scheduled_start")
    end = parse_instant(b.get("scheduled_end"), "scheduled_end")
    _validate_mission_window_shape(start, end)
    acres_planned = req_int(b, "acres_planned")
    if acres_planned <= 0:
        fail("ERR_INVALID_REQUEST", 400, "acres_planned must be a positive integer")
    if acres_planned > field["legal_acres"]:
        fail("ERR_INVALID_REQUEST", 400,
             "acres_planned must not exceed the field's legal_acres")
    chemical_product_label = opt_str(b, "chemical_product_label", "")
    wind = opt_int(b, "wind_kt_max_observed", 0)
    gallons = opt_num(b, "gallons_dispensed", 0)
    if start <= now_utc():
        fail("ERR_OUTSIDE_WINDOW", 422, "scheduled_start must be in the future")
    m = new_entity()
    m.update({
        "field_id": field["id"],
        "mission_type": mission_type,
        "pilot_id": pilot["id"],
        "authorization_id": authorization_id,
        "scheduled_start": start,
        "scheduled_end": end,
        "acres_planned": acres_planned,
        "acres_flown": 0,
        "wind_kt_max_observed": wind,
        "chemical_product_label": chemical_product_label,
        "gallons_dispensed": gallons,
        "status": "PLANNED",
        "_completed_at": None,
    })
    STORE["missions"][m["id"]] = m
    return success(ser_mission(m), 201)


@app.get("/ag-drone/missions/<mid>")
def get_mission(mid):
    uid, role = require_roles({"OpsAdmin", "FlightCoordinator", "Grower",
                               "RemotePilot", "Agronomist", "ClaimsAdjuster"})
    m = get_or_404("missions", mid, "mission")
    check_grower_scope(role, uid, grower_id_of_mission(m))
    return success(ser_mission(m))


@app.get("/ag-drone/fields/<fid>/missions")
def list_field_missions(fid):
    uid, role = require_roles({"OpsAdmin", "FlightCoordinator", "Grower", "RemotePilot"})
    field = get_or_404("fields", fid, "field")
    check_grower_scope(role, uid, field["grower_id"])
    items = field_missions(field["id"])
    status = request.args.get("status")
    if status:
        items = [m for m in items if m["status"] == status]
    return list_response(items, ser_mission)


@app.get("/ag-drone/missions")
def list_missions():
    require_roles({"OpsAdmin", "FlightCoordinator"})
    items = list(STORE["missions"].values())
    for param in ("status", "field_id", "pilot_id", "authorization_id"):
        v = request.args.get(param)
        if v:
            items = [m for m in items if m.get(param) == v]
    return list_response(items, ser_mission)


@app.post("/ag-drone/missions/<mid>/authorize")
def authorize_mission(mid):
    require_roles({"FlightCoordinator"})
    m = get_or_404("missions", mid, "mission")
    if m["status"] != "PLANNED":
        fail("ERR_MISSION_NOT_PLANNED", 409, "mission must be PLANNED to authorize")
    field = STORE["fields"][m["field_id"]]
    grower = STORE["growers"][field["grower_id"]]
    if grower["status"] != "ACTIVE":
        fail("ERR_GROWER_NOT_ACTIVE", 409, "grower must be ACTIVE to authorize")
    pilot = STORE["pilots"][m["pilot_id"]]
    end_date = m["scheduled_end"].date()
    # priority 5: pilot certificate / applicator license currency
    if pilot["status"] != "ACTIVE" or pilot["part107_expires_on"] < end_date:
        fail("ERR_PILOT_CERT_EXPIRED", 422,
             "pilot is not ACTIVE or Part 107 certificate expires before scheduled_end")
    if m["mission_type"] == "SPRAY":
        if (not pilot["applicator_license_no"]
                or not pilot["applicator_license_expires_on"]
                or pilot["applicator_license_expires_on"] < end_date.isoformat()
                or not m["chemical_product_label"]):
            fail("ERR_PILOT_CERT_EXPIRED", 422,
                 "SPRAY mission requires a current applicator license and a chemical_product_label")
    # priority 6: airspace authorization sufficiency
    if field["laanc_required"]:
        aid = m["authorization_id"]
        a = STORE["authorizations"].get(aid) if aid else None
        if a is None:
            fail("ERR_AUTH_WINDOW_INSUFFICIENT", 422,
                 "a LAANC authorization is required for controlled airspace")
        if a["status"] != "ACTIVE" or not (
                a["effective_from"] <= m["scheduled_start"]
                and m["scheduled_end"] < a["effective_until"]):
            fail("ERR_AUTH_WINDOW_INSUFFICIENT", 422,
                 "authorization window does not fully contain the mission window")
    else:
        if m["authorization_id"] is not None:
            fail("ERR_AUTH_NOT_PERMITTED", 422,
                 "authorization_id must be null for non-controlled airspace")
    # priority 7: spray plan entitlement
    if m["mission_type"] == "SPRAY":
        plan = STORE["plans"][grower["subscription_plan_id"]]
        if not plan["spray_allowed"]:
            fail("ERR_SPRAY_PLAN_FORBIDDEN", 422,
                 "the grower's plan does not allow SPRAY missions")
    # priority 9: same-field scheduling conflict
    if window_conflict(field["id"], m["scheduled_start"], m["scheduled_end"], m["id"]):
        fail("ERR_MISSION_WINDOW_CONFLICT", 409,
             "buffered mission window conflicts with another live mission on the field")
    m["status"] = "AUTHORIZED"
    bump(m)
    return success(ser_mission(m))


@app.post("/ag-drone/missions/<mid>/launch")
def launch_mission(mid):
    uid, role = require_roles({"RemotePilot"})
    m = get_or_404("missions", mid, "mission")
    if m["status"] != "AUTHORIZED":
        fail("ERR_MISSION_NOT_AUTHORIZED", 409, "mission must be AUTHORIZED to launch")
    if uid != m["pilot_id"]:
        fail("ERR_NOT_ASSIGNED_PILOT", 403, "only the assigned pilot may launch")
    now = now_utc()
    if not (m["scheduled_start"] <= now < m["scheduled_end"]):
        fail("ERR_OUTSIDE_WINDOW", 422,
             "current time is outside [scheduled_start, scheduled_end)")
    if m["authorization_id"]:
        a = STORE["authorizations"].get(m["authorization_id"])
        if a is None or a["status"] != "ACTIVE":
            fail("ERR_AUTH_NOT_ACTIVE", 409, "authorization is no longer ACTIVE")
    m["status"] = "IN_FLIGHT"
    bump(m)
    return success(ser_mission(m))


@app.post("/ag-drone/missions/<mid>/capture")
def capture_mission(mid):
    uid, role = require_roles({"RemotePilot"})
    m = get_or_404("missions", mid, "mission")
    b = body()
    acres_flown = req_int(b, "acres_flown")
    wind = req_int(b, "wind_kt_max_observed")
    gallons = opt_num(b, "gallons_dispensed", 0)
    if m["status"] != "IN_FLIGHT":
        fail("ERR_MISSION_NOT_IN_FLIGHT", 409, "mission must be IN_FLIGHT to capture")
    if wind > WIND_LIMIT_KT:
        fail("ERR_WEATHER_LIMIT_EXCEEDED", 422,
             "wind_kt_max_observed exceeds 20 kt; capture is not permitted")
    if acres_flown <= 0 or acres_flown > m["acres_planned"]:
        fail("ERR_ACRES_OUT_OF_RANGE", 422,
             "acres_flown must be greater than 0 and at most acres_planned")
    if uid != m["pilot_id"]:
        fail("ERR_NOT_ASSIGNED_PILOT", 403, "only the assigned pilot may capture")
    m["acres_flown"] = acres_flown
    m["wind_kt_max_observed"] = wind
    m["gallons_dispensed"] = gallons
    m["status"] = "CAPTURED"
    bump(m)
    return success(ser_mission(m))


@app.post("/ag-drone/missions/<mid>/abort-weather")
def abort_weather_mission(mid):
    uid, role = require_roles({"RemotePilot"})
    m = get_or_404("missions", mid, "mission")
    b = body()
    wind = req_int(b, "wind_kt_max_observed")
    if m["status"] != "IN_FLIGHT":
        fail("ERR_MISSION_NOT_IN_FLIGHT", 409, "mission must be IN_FLIGHT to abort")
    if wind <= WIND_LIMIT_KT:
        fail("ERR_WEATHER_LIMIT_NOT_EXCEEDED", 422,
             "weather abort requires wind_kt_max_observed greater than 20 kt")
    if uid != m["pilot_id"]:
        fail("ERR_NOT_ASSIGNED_PILOT", 403, "only the assigned pilot may abort")
    m["wind_kt_max_observed"] = wind
    m["status"] = "WEATHER_ABORTED"
    bump(m)
    return success(ser_mission(m))


@app.post("/ag-drone/missions/<mid>/complete")
def complete_mission(mid):
    require_roles({"FlightCoordinator"})
    m = get_or_404("missions", mid, "mission")
    b = body()
    kinds = b.get("deliverable_kinds")
    if (not isinstance(kinds, list) or not kinds
            or any(k not in ("NDVI", "PLANT_COUNT") for k in kinds)):
        fail("ERR_INVALID_REQUEST", 400,
             "deliverable_kinds must be a non-empty list of NDVI and/or PLANT_COUNT")
    rei = opt_int(b, "restricted_entry_interval_hours", 0)
    if m["status"] != "CAPTURED":
        fail("ERR_MISSION_NOT_CAPTURED", 409, "mission must be CAPTURED to complete")
    field = STORE["fields"][m["field_id"]]
    grower = STORE["growers"][field["grower_id"]]
    m["status"] = "COMPLETED"
    m["_completed_at"] = now_utc()
    bump(m)
    field["surveyed_acres"] = m["acres_flown"]
    bump(field)
    grower["acres_included_ytd"] += m["acres_flown"]
    bump(grower)
    for kind in kinds:
        d = new_entity()
        d.update({
            "mission_id": m["id"],
            "kind": kind,
            "ndvi_mean": None,
            "plant_count_per_acre": None,
            "anomaly_count": 0,
            "storage_uri": None,
            "accessible_until": None,
            "status": "PROCESSING",
        })
        STORE["deliverables"][d["id"]] = d
    if m["mission_type"] == "SPRAY":
        pilot = STORE["pilots"][m["pilot_id"]]
        r = new_entity(common=False)
        r.update({
            "mission_id": m["id"],
            "applicator_license_no": pilot["applicator_license_no"],
            "chemical_product_label": m["chemical_product_label"],
            "gallons_dispensed": m["gallons_dispensed"],
            "restricted_entry_interval_hours": rei,
            "record_locked": True,
        })
        STORE["spray_records"][r["id"]] = r
    return success(ser_mission(m))


@app.post("/ag-drone/missions/<mid>/cancel")
def cancel_mission(mid):
    require_roles({"FlightCoordinator"})
    m = get_or_404("missions", mid, "mission")
    if m["status"] not in ("PLANNED", "AUTHORIZED"):
        fail("ERR_MISSION_NOT_CANCELLABLE", 409,
             "only PLANNED or AUTHORIZED missions can be cancelled")
    m["status"] = "CANCELLED"
    bump(m)
    return success(ser_mission(m))


@app.post("/ag-drone/missions/<mid>/replan")
def replan_mission(mid):
    require_roles({"FlightCoordinator"})
    m = get_or_404("missions", mid, "mission")
    b = body()
    start = parse_instant(b.get("scheduled_start"), "scheduled_start")
    end = parse_instant(b.get("scheduled_end"), "scheduled_end")
    _validate_mission_window_shape(start, end)
    expected = req_int(b, "expected_mission_version")
    if m["status"] not in ("WEATHER_ABORTED", "CANCELLED"):
        fail("ERR_INVALID_STATE", 409,
             "only WEATHER_ABORTED or CANCELLED missions can be replanned")
    if expected != m["version"]:
        fail("ERR_STALE_MISSION_VERSION", 412,
             "expected_mission_version does not match the mission's current version")
    if window_conflict(m["field_id"], start, end, None):
        fail("ERR_MISSION_WINDOW_CONFLICT", 409,
             "buffered mission window conflicts with another live mission on the field")
    if start <= now_utc():
        fail("ERR_OUTSIDE_WINDOW", 422, "scheduled_start must be in the future")
    nm = new_entity()
    nm.update({
        "field_id": m["field_id"],
        "mission_type": m["mission_type"],
        "pilot_id": m["pilot_id"],
        "authorization_id": m["authorization_id"],
        "scheduled_start": start,
        "scheduled_end": end,
        "acres_planned": m["acres_planned"],
        "acres_flown": 0,
        "wind_kt_max_observed": 0,
        "chemical_product_label": m["chemical_product_label"],
        "gallons_dispensed": 0,
        "status": "PLANNED",
        "_completed_at": None,
    })
    STORE["missions"][nm["id"]] = nm
    bump(m)
    return success(ser_mission(nm), 201)


# ============================== ImageryDeliverable ==============================

def _deliverable_grower_id(d):
    m = STORE["missions"].get(d["mission_id"])
    return grower_id_of_mission(m) if m else None


@app.get("/ag-drone/deliverables/<did>")
def get_deliverable(did):
    uid, role = require_roles(
        {"OpsAdmin", "FlightCoordinator", "Grower", "Agronomist", "ProcessingEngine"})
    d = get_or_404("deliverables", did, "deliverable")
    check_grower_scope(role, uid, _deliverable_grower_id(d))
    if role == "Grower":
        if (d["status"] == "EXPIRED"
                or (d["accessible_until"] and now_utc() >= d["accessible_until"])):
            fail("ERR_DELIV_EXPIRED", 410, "deliverable access has expired")
    return success(ser_deliverable(d))


@app.get("/ag-drone/missions/<mid>/deliverables")
def list_mission_deliverables(mid):
    uid, role = require_roles(
        {"OpsAdmin", "FlightCoordinator", "Grower", "Agronomist", "ProcessingEngine"})
    m = get_or_404("missions", mid, "mission")
    check_grower_scope(role, uid, grower_id_of_mission(m))
    items = [d for d in STORE["deliverables"].values() if d["mission_id"] == m["id"]]
    return list_response(items, ser_deliverable)


@app.post("/ag-drone/deliverables/<did>/process")
def process_deliverable(did):
    require_roles({"ProcessingEngine"})
    d = get_or_404("deliverables", did, "deliverable")
    if d["status"] != "PROCESSING":
        fail("ERR_DELIV_NOT_PROCESSING", 409, "deliverable must be PROCESSING")
    b = body()
    m = STORE["missions"][d["mission_id"]]
    if d["kind"] == "NDVI":
        ndvi = b.get("ndvi_mean")
        if (isinstance(ndvi, bool) or not isinstance(ndvi, (int, float))
                or ndvi < 0 or ndvi > 1):
            fail("ERR_DELIV_INPUT_INVALID", 422,
                 "ndvi_mean is required and must lie in [0.000, 1.000]")
        cells = b.get("cells_below_threshold", 0)
        if isinstance(cells, bool) or not isinstance(cells, int) or cells < 0:
            fail("ERR_DELIV_INPUT_INVALID", 422,
                 "cells_below_threshold must be a non-negative integer")
        anomaly = rhu(Decimal(cells) * Decimal(m["acres_flown"]) / NDVI_STRESS_DIVISOR)
        d["ndvi_mean"] = round(float(ndvi), 3)
    else:
        pc = b.get("plant_count_per_acre")
        if isinstance(pc, bool) or not isinstance(pc, int) or pc <= 0:
            fail("ERR_DELIV_INPUT_INVALID", 422,
                 "plant_count_per_acre is required and must be greater than 0")
        anomaly = 0 if pc >= STAND_MIN_PLANTS else m["acres_flown"]
        d["plant_count_per_acre"] = pc
    d["anomaly_count"] = anomaly
    d["status"] = "READY"
    d["storage_uri"] = "s3://ag-drone-deliverables/{}/{}".format(m["id"], d["id"])
    field = STORE["fields"][m["field_id"]]
    grower = STORE["growers"][field["grower_id"]]
    plan = STORE["plans"][grower["subscription_plan_id"]]
    ready_instant = now_utc().replace(microsecond=0)
    d["accessible_until"] = ready_instant + timedelta(days=plan["storage_retention_days"])
    bump(d)
    if anomaly > 0:
        if anomaly >= 50:
            severity = "HIGH"
        elif anomaly >= 10:
            severity = "MEDIUM"
        else:
            severity = "LOW"
        a = new_entity()
        a.update({
            "field_id": field["id"],
            "deliverable_id": d["id"],
            "severity": severity,
            "reviewing_agronomist_id": None,
            "review_notes": "",
            "review_outcome": None,
            "status": "OPEN",
        })
        STORE["alerts"][a["id"]] = a
    recompute_health(field)
    return success(ser_deliverable(d))


@app.post("/ag-drone/deliverables/<did>/deliver")
def deliver_deliverable(did):
    require_roles({"FlightCoordinator"})
    d = get_or_404("deliverables", did, "deliverable")
    if d["status"] != "READY":
        fail("ERR_DELIV_NOT_READY", 409, "deliverable must be READY to deliver")
    d["status"] = "DELIVERED"
    bump(d)
    return success(ser_deliverable(d))


# ============================== ScoutingAlert ==============================

def _originating_mission(alert):
    d = STORE["deliverables"].get(alert["deliverable_id"])
    return STORE["missions"].get(d["mission_id"]) if d else None


@app.get("/ag-drone/alerts/<aid>")
def get_alert(aid):
    uid, role = require_roles({"OpsAdmin", "FlightCoordinator", "Grower", "Agronomist"})
    a = get_or_404("alerts", aid, "alert")
    field = STORE["fields"].get(a["field_id"])
    check_grower_scope(role, uid, field["grower_id"] if field else None)
    return success(ser_alert(a))


@app.get("/ag-drone/fields/<fid>/alerts")
def list_field_alerts(fid):
    uid, role = require_roles({"OpsAdmin", "FlightCoordinator", "Grower", "Agronomist"})
    field = get_or_404("fields", fid, "field")
    check_grower_scope(role, uid, field["grower_id"])
    items = [a for a in STORE["alerts"].values() if a["field_id"] == field["id"]]
    status = request.args.get("status")
    if status:
        items = [a for a in items if a["status"] == status]
    return list_response(items, ser_alert)


@app.get("/ag-drone/alerts")
def list_alerts():
    require_roles({"OpsAdmin", "FlightCoordinator", "Agronomist"})
    items = list(STORE["alerts"].values())
    for param in ("status", "field_id", "deliverable_id", "reviewing_agronomist_id"):
        v = request.args.get(param)
        if v:
            items = [a for a in items if a.get(param) == v]
    return list_response(items, ser_alert)


@app.post("/ag-drone/alerts/<aid>/claim")
def claim_alert(aid):
    uid, role = require_roles({"Agronomist"})
    a = get_or_404("alerts", aid, "alert")
    if a["status"] != "OPEN":
        fail("ERR_ALERT_NOT_OPEN", 409, "alert must be OPEN to claim")
    m = _originating_mission(a)
    if m is not None and uid == m["pilot_id"]:
        fail("ERR_SELF_REVIEW_FORBIDDEN", 422,
             "the mission's pilot may not review alerts raised from that mission")
    a["status"] = "UNDER_REVIEW"
    a["reviewing_agronomist_id"] = uid
    bump(a)
    return success(ser_alert(a))


@app.post("/ag-drone/alerts/<aid>/review")
def review_alert(aid):
    uid, role = require_roles({"Agronomist"})
    a = get_or_404("alerts", aid, "alert")
    if a["status"] != "UNDER_REVIEW":
        fail("ERR_ALERT_NOT_UNDER_REVIEW", 409, "alert must be UNDER_REVIEW to review")
    if uid != a["reviewing_agronomist_id"]:
        fail("ERR_NOT_CLAIMING_AGRONOMIST", 403,
             "only the claiming agronomist may review this alert")
    b = body()
    outcome = b.get("review_outcome")
    if outcome not in ("CONFIRMED", "DISMISSED", "NEEDS_REFLIGHT"):
        fail("ERR_REVIEW_OUTCOME_INVALID", 422,
             "review_outcome must be one of CONFIRMED, DISMISSED, NEEDS_REFLIGHT")
    notes = opt_str(b, "review_notes", "")
    a["review_outcome"] = outcome
    a["review_notes"] = notes
    a["status"] = "REVIEWED"
    bump(a)
    field = STORE["fields"].get(a["field_id"])
    if field is not None:
        if outcome == "DISMISSED":
            recompute_health(field)
        elif outcome == "NEEDS_REFLIGHT":
            recompute_health(field, double_alert=a)
    return success(ser_alert(a))


@app.post("/ag-drone/alerts/<aid>/release")
def release_alert(aid):
    uid, role = require_roles({"Agronomist"})
    a = get_or_404("alerts", aid, "alert")
    if a["status"] != "UNDER_REVIEW":
        fail("ERR_ALERT_NOT_UNDER_REVIEW", 409, "alert must be UNDER_REVIEW to release")
    if uid != a["reviewing_agronomist_id"]:
        fail("ERR_NOT_CLAIMING_AGRONOMIST", 403,
             "only the claiming agronomist may release this alert")
    a["status"] = "OPEN"
    a["reviewing_agronomist_id"] = None
    bump(a)
    return success(ser_alert(a))


# ============================== SprayMissionRecord ==============================

@app.get("/ag-drone/missions/<mid>/spray-record")
def get_spray_record(mid):
    uid, role = require_roles({"OpsAdmin", "FlightCoordinator", "Grower", "ClaimsAdjuster"})
    m = get_or_404("missions", mid, "mission")
    check_grower_scope(role, uid, grower_id_of_mission(m))
    items = [r for r in STORE["spray_records"].values() if r["mission_id"] == m["id"]]
    return list_response(items, ser_spray_record)


# ============================== InsuranceClaim ==============================

@app.post("/ag-drone/growers/<gid>/claims")
def submit_claim(gid):
    uid, role = require_roles({"Grower"})
    g = get_or_404("growers", gid, "grower")
    check_grower_scope(role, uid, g["id"])
    b = body()
    mission_id = req_str(b, "mission_id")
    mission = get_or_404("missions", mission_id, "mission")
    amount = req_int(b, "claim_amount_cents")
    if amount <= 0:
        fail("ERR_INVALID_REQUEST", 400, "claim_amount_cents must be a positive integer")
    c = new_entity()
    c.update({
        "grower_id": g["id"],
        "mission_id": mission["id"],
        "claim_amount_cents": amount,
        "approved_amount_cents": 0,
        "adjuster_user_id": None,
        "status": "SUBMITTED",
    })
    STORE["claims"][c["id"]] = c
    return success(ser_claim(c), 201)


@app.get("/ag-drone/claims/<cid>")
def get_claim(cid):
    uid, role = require_roles({"OpsAdmin", "Grower", "ClaimsAdjuster"})
    c = get_or_404("claims", cid, "claim")
    check_grower_scope(role, uid, c["grower_id"])
    return success(ser_claim(c))


@app.get("/ag-drone/claims")
def list_claims():
    require_roles({"OpsAdmin", "ClaimsAdjuster"})
    items = list(STORE["claims"].values())
    for param in ("status", "mission_id", "grower_id"):
        v = request.args.get(param)
        if v:
            items = [c for c in items if c.get(param) == v]
    return list_response(items, ser_claim)


@app.get("/ag-drone/growers/<gid>/claims")
def list_grower_claims(gid):
    uid, role = require_roles({"OpsAdmin", "Grower", "ClaimsAdjuster"})
    g = get_or_404("growers", gid, "grower")
    check_grower_scope(role, uid, g["id"])
    items = [c for c in STORE["claims"].values() if c["grower_id"] == g["id"]]
    status = request.args.get("status")
    if status:
        items = [c for c in items if c["status"] == status]
    return list_response(items, ser_claim)


@app.post("/ag-drone/claims/<cid>/open-review")
def open_review_claim(cid):
    uid, role = require_roles({"ClaimsAdjuster"})
    c = get_or_404("claims", cid, "claim")
    if c["status"] != "SUBMITTED":
        fail("ERR_CLAIM_NOT_SUBMITTED", 409, "claim must be SUBMITTED to open review")
    c["status"] = "UNDER_REVIEW"
    c["adjuster_user_id"] = uid
    bump(c)
    return success(ser_claim(c))


@app.post("/ag-drone/claims/<cid>/approve")
def approve_claim(cid):
    require_roles({"ClaimsAdjuster"})
    c = get_or_404("claims", cid, "claim")
    b = body()
    amount = req_int(b, "amount_cents")
    if c["status"] != "UNDER_REVIEW":
        fail("ERR_CLAIM_NOT_UNDER_REVIEW", 409, "claim must be UNDER_REVIEW to approve")
    grower = STORE["growers"][c["grower_id"]]
    already = sum(
        x["approved_amount_cents"] for x in STORE["claims"].values()
        if x["mission_id"] == c["mission_id"] and x["status"] in ("APPROVED", "PAID")
    )
    if amount <= 0 or already + amount > grower["liability_coverage_cents"]:
        fail("ERR_CLAIM_EXCEEDS_COVERAGE", 422,
             "amount exceeds the remaining liability coverage on this mission")
    mission = STORE["missions"][c["mission_id"]]
    if mission["status"] not in ("COMPLETED", "WEATHER_ABORTED"):
        fail("ERR_CLAIM_MISSION_NOT_FINAL", 409,
             "claim approval requires the mission to be COMPLETED or WEATHER_ABORTED")
    c["approved_amount_cents"] = amount
    c["status"] = "APPROVED"
    bump(c)
    return success(ser_claim(c))


@app.post("/ag-drone/claims/<cid>/deny")
def deny_claim(cid):
    require_roles({"ClaimsAdjuster"})
    c = get_or_404("claims", cid, "claim")
    if c["status"] != "UNDER_REVIEW":
        fail("ERR_CLAIM_NOT_UNDER_REVIEW", 409, "claim must be UNDER_REVIEW to deny")
    c["approved_amount_cents"] = 0
    c["status"] = "DENIED"
    bump(c)
    return success(ser_claim(c))


@app.post("/ag-drone/claims/<cid>/pay")
def pay_claim(cid):
    require_roles({"ClaimsAdjuster"})
    c = get_or_404("claims", cid, "claim")
    if c["status"] != "APPROVED":
        fail("ERR_CLAIM_NOT_APPROVED", 409, "claim must be APPROVED to pay")
    c["status"] = "PAID"
    bump(c)
    grower = STORE["growers"][c["grower_id"]]
    grower["credit_balance_cents"] += c["approved_amount_cents"]
    bump(grower)
    return success(ser_claim(c))


# ============================== logical clock ==============================

@app.post("/ag-drone/_clock/set_current_utc")
def set_current_utc():
    require_roles({"OpsAdmin"})
    b = body()
    to = parse_instant(b.get("to_iso8601"), "to_iso8601")
    _clock["now"] = to
    run_sweeps()
    return success({"current_utc": fmt_instant(to)})


# ============================== main ==============================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
