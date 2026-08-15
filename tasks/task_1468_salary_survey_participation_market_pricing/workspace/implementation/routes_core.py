"""Organizations, MarketStrategyPolicies, Jobs, Employees."""
from flask import Blueprint, request

from common import (
    ApiError, ALL_ROLES, body, db, filter_records, get_or_404, new_record, ok,
    ok_list, pub, require_roles, touch, v_date, v_enum, v_int, v_str,
)

bp = Blueprint("core", __name__)

GEO_POLICIES = ("NATIONAL", "METRO_TIER", "CUSTOM_GEO_INDEX")
INDUSTRY_CUTS = ("ALL_INDUSTRIES", "HIGH_TECH", "FINANCIAL_SERVICES",
                 "HEALTHCARE", "MANUFACTURING", "RETAIL")
CAREER_LEVELS = ("IC1", "IC2", "IC3", "IC4", "IC5", "M1", "M2", "M3")
FLSA_STATUSES = ("EXEMPT", "NON_EXEMPT")
TARGET_PERCENTILES = (25, 50, 65, 75, 90)


# ---------------------------------------------------------------------------
# Organizations
# ---------------------------------------------------------------------------
@bp.route("/orgs", methods=["POST"])
@require_roles("VendorAdmin")
def create_org():
    b = body()
    name = v_str(b, "name")
    currency = v_str(b, "base_currency")
    fym = v_int(b, "fiscal_year_start_month", required=False, min_v=1, max_v=12)
    if fym is None:
        fym = 1
    as_of = v_date(b, "market_as_of_date")
    rec = new_record()
    rec.update({
        "name": name,
        "base_currency": currency,
        "fiscal_year_start_month": fym,
        "market_as_of_date": as_of,
        "strategy_policy_id": None,
    })
    db["orgs"][rec["id"]] = rec
    return ok(pub(rec), 201)


@bp.route("/orgs/<oid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_org(oid):
    return ok(pub(get_or_404("orgs", oid)))


@bp.route("/orgs", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_orgs():
    return ok_list(filter_records("orgs", {
        "strategy_policy_id": request.args.get("strategy_policy_id"),
    }))


# ---------------------------------------------------------------------------
# Market strategy policies
# ---------------------------------------------------------------------------
@bp.route("/orgs/<oid>/strategies", methods=["POST"])
@require_roles("CompManager")
def create_strategy(oid):
    org = get_or_404("orgs", oid)
    b = body()
    rec = new_record()
    rec.update({
        "org_id": org["id"],
        "name": v_str(b, "name"),
        "target_percentile": v_int(b, "target_percentile", choices=TARGET_PERCENTILES),
        "geo_differential_policy": v_enum(b, "geo_differential_policy", GEO_POLICIES),
        "industry_cut": v_enum(b, "industry_cut", INDUSTRY_CUTS),
        "effective_from": v_date(b, "effective_from"),
        "effective_to": v_date(b, "effective_to"),
        "status": "DRAFT",
    })
    db["strategies"][rec["id"]] = rec
    return ok(pub(rec), 201)


@bp.route("/strategies/<sid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_strategy(sid):
    return ok(pub(get_or_404("strategies", sid)))


@bp.route("/strategies", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_strategies():
    return ok_list(filter_records("strategies", {
        "org_id": request.args.get("org_id"),
        "status": request.args.get("status"),
    }))


@bp.route("/orgs/<oid>/strategies", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_org_strategies(oid):
    org = get_or_404("orgs", oid)
    return ok_list(filter_records("strategies", {"org_id": org["id"]}))


@bp.route("/strategies/<sid>/activate", methods=["POST"])
@require_roles("CompManager")
def activate_strategy(sid):
    s = get_or_404("strategies", sid)
    # Ladder rung 4: window internally valid
    if not (s["effective_from"] < s["effective_to"]):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "effective_from must be strictly earlier than effective_to")
    # Rung 5: state
    if s["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       f"Cannot activate a strategy in status {s['status']}")
    # Rung 10: overlap of half-open [effective_from, effective_to) windows
    for o in db["strategies"].values():
        if o["org_id"] == s["org_id"] and o["id"] != s["id"] and o["status"] == "ACTIVE":
            if o["effective_from"] < s["effective_to"] and s["effective_from"] < o["effective_to"]:
                raise ApiError("ERR_STRATEGY_WINDOW_OVERLAP", 409,
                               "Another ACTIVE strategy has an overlapping window")
    s["status"] = "ACTIVE"
    touch(s)
    org = db["orgs"][s["org_id"]]
    org["strategy_policy_id"] = s["id"]
    touch(org)
    return ok(pub(s))


@bp.route("/strategies/<sid>/retire", methods=["POST"])
@require_roles("CompManager")
def retire_strategy(sid):
    s = get_or_404("strategies", sid)
    if s["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       f"Cannot retire a strategy in status {s['status']}")
    s["status"] = "RETIRED"
    touch(s)
    org = db["orgs"][s["org_id"]]
    if org["strategy_policy_id"] == s["id"]:
        org["strategy_policy_id"] = None
        touch(org)
    return ok(pub(s))


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------
@bp.route("/orgs/<oid>/jobs", methods=["POST"])
@require_roles("CompManager")
def create_job(oid):
    org = get_or_404("orgs", oid)
    b = body()
    job_code = v_str(b, "job_code")
    for j in db["jobs"].values():
        if j["org_id"] == org["id"] and j["job_code"] == job_code:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           f"job_code {job_code} already exists in this organization")
    rec = new_record()
    rec.update({
        "org_id": org["id"],
        "job_code": job_code,
        "title": v_str(b, "title"),
        "job_family": v_str(b, "job_family"),
        "career_level": v_enum(b, "career_level", CAREER_LEVELS),
        "flsa_status": v_enum(b, "flsa_status", FLSA_STATUSES),
        "current_market_composite_id": None,
    })
    db["jobs"][rec["id"]] = rec
    return ok(pub(rec), 201)


@bp.route("/jobs/<jid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_job(jid):
    return ok(pub(get_or_404("jobs", jid)))


@bp.route("/jobs", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_jobs():
    return ok_list(filter_records("jobs", {
        "org_id": request.args.get("org_id"),
        "job_family": request.args.get("job_family"),
        "career_level": request.args.get("career_level"),
        "current_market_composite_id": request.args.get("current_market_composite_id"),
    }))


@bp.route("/orgs/<oid>/jobs", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_org_jobs(oid):
    org = get_or_404("orgs", oid)
    return ok_list(filter_records("jobs", {"org_id": org["id"]}))


# ---------------------------------------------------------------------------
# Employees
# ---------------------------------------------------------------------------
@bp.route("/orgs/<oid>/employees", methods=["POST"])
@require_roles("CompManager", "HRDirector")
def create_employee(oid):
    org = get_or_404("orgs", oid)
    b = body()
    full_name = v_str(b, "full_name")
    email = v_str(b, "email")
    job_id = v_str(b, "job_id")
    geo_code = v_str(b, "geo_code")
    salary = v_int(b, "base_salary_annual_cents")
    hire_date = v_date(b, "hire_date")
    job = db["jobs"].get(job_id)
    if job is None or job["org_id"] != org["id"]:
        raise ApiError("ERR_NOT_FOUND", 404, f"Job {job_id} not found in this organization")
    for e in db["employees"].values():
        if e["org_id"] == org["id"] and e["email"] == email:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           f"email {email} already exists in this organization")
    rec = new_record()
    rec.update({
        "org_id": org["id"],
        "full_name": full_name,
        "email": email,
        "job_id": job_id,
        "geo_code": geo_code,
        "base_salary_annual_cents": salary,
        "hire_date": hire_date,
        "status": "ACTIVE",
    })
    db["employees"][rec["id"]] = rec
    return ok(pub(rec), 201)


@bp.route("/employees/<eid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_employee(eid):
    return ok(pub(get_or_404("employees", eid)))


@bp.route("/employees", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_employees():
    return ok_list(filter_records("employees", {
        "org_id": request.args.get("org_id"),
        "job_id": request.args.get("job_id"),
        "status": request.args.get("status"),
        "geo_code": request.args.get("geo_code"),
    }))


@bp.route("/orgs/<oid>/employees", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_org_employees(oid):
    org = get_or_404("orgs", oid)
    return ok_list(filter_records("employees", {"org_id": org["id"]}))


@bp.route("/jobs/<jid>/employees", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_job_employees(jid):
    job = get_or_404("jobs", jid)
    return ok_list(filter_records("employees", {"job_id": job["id"]}))
